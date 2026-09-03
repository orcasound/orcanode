#!/usr/bin/env python3
"""Feed a rolling archive of timestamped, fixed-length audio files to stdout as
one continuous real-time PCM stream, held a fixed delay behind wall-clock.

Use case: a network share is filling with short audio files named with their
recording start time (e.g. "<id>_YYYYMMDD_HHMMSS.wav"), landing some minutes
after they were recorded. This plays them back as a single live-ish stream that
trails real time by a configurable delay, so downstream (ffmpeg -> HLS) always
has a complete file to read. Missing/late files become silence so the stream
never stalls; it is restart-safe because the play position is derived from the
wall clock, not from any saved state.

Everything is configured via environment variables (or CLI flags) — nothing
about any particular site, sensor, or filename scheme is hardcoded.

Output: raw interleaved little-endian 16-bit PCM on stdout, intended to be
piped into ffmpeg, e.g.:

    archive_feed.py | ffmpeg -re -f s16le -ar $OUT_RATE -ac $OUT_CHANNELS -i pipe:0 ...

Config (env / flag):
  ARCHIVE_DIR          directory holding the files
  ARCHIVE_GLOB         filename glob within the dir (default "*.wav")
  ARCHIVE_PREFIX       optional filename prefix to select one source among many
  ARCHIVE_TIME_REGEX   regex with one group capturing the timestamp substring of
                       the filename (default r"(\\d{8}_\\d{6})")
  ARCHIVE_TIME_FORMAT  strptime format for that substring (default "%Y%m%d_%H%M%S")
  ARCHIVE_FILE_SECONDS nominal length of each file, seconds (default 300)
  ARCHIVE_DELAY        seconds to stay behind wall-clock (default 3600)
  ARCHIVE_REINDEX      seconds between directory re-scans (default 60)
  OUT_RATE             output PCM sample rate (default from STREAM_RATE or 48000)
  OUT_CHANNELS         output channel count (default from CHANNELS or 1)
  FFMPEG               ffmpeg binary (default "ffmpeg")

Timestamps in filenames are treated as UTC (the common case for such archives).
"""

import argparse
import calendar
import glob as globmod
import os
import re
import shutil
import subprocess
import sys
import time

SAMPLE_BYTES = 2  # s16le


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def log(msg):
    sys.stderr.write("archive_feed: %s\n" % msg)
    sys.stderr.flush()


# --- Pure helpers (unit-tested in test_archive.py) ---------------------------

def parse_timestamp(name, regex, time_format):
    """Return the UTC epoch for a filename, or None if it doesn't match."""
    m = regex.search(name)
    if not m:
        return None
    try:
        return calendar.timegm(time.strptime(m.group(1), time_format))
    except ValueError:
        return None


def build_index(names, regex, time_format, prefix=None):
    """Map filenames -> sorted list of (start_epoch, name).

    `names` is an iterable of basenames. Non-matching / wrong-prefix names are
    dropped. Result is sorted ascending by start time.
    """
    out = []
    for name in names:
        if prefix and not name.startswith(prefix):
            continue
        ts = parse_timestamp(name, regex, time_format)
        if ts is not None:
            out.append((ts, name))
    out.sort()
    return out


def find_slot(index, play_time, file_seconds):
    """Decide what to emit for `play_time` given the sorted index.

    Returns (name_or_None, offset_seconds, duration_seconds):
      - a file covering play_time  -> (name, offset into file, remaining dur)
      - a gap before the next file -> (None, 0, seconds of silence until it)
      - nothing ahead              -> (None, 0, file_seconds)  # bounded silence
    """
    if not index:
        return None, 0.0, float(file_seconds)
    # latest file whose start <= play_time
    cur = None
    nxt = None
    for start, name in index:
        if start <= play_time:
            cur = (start, name)
        else:
            nxt = (start, name)
            break
    if cur is not None:
        start, name = cur
        end = start + file_seconds
        if play_time < end:
            return name, play_time - start, end - play_time
    # in a gap: silence until the next known file, or one bounded slot
    if nxt is not None:
        return None, 0.0, max(0.0, nxt[0] - play_time)
    return None, 0.0, float(file_seconds)


# --- IO -----------------------------------------------------------------------

def write_silence(out, seconds, rate, channels):
    total = int(round(seconds * rate)) * channels * SAMPLE_BYTES
    zeros = bytes(65536)
    while total > 0:
        n = min(total, len(zeros))
        out.write(zeros[:n])
        total -= n
    out.flush()


def decode_file(out, ffmpeg, path, offset, dur, rate, channels):
    """Decode `dur` seconds from `path` starting at `offset`, as s16le, to out.

    Returns True on success, False if the file could not be read (caller then
    substitutes silence)."""
    cmd = [ffmpeg, "-nostdin", "-loglevel", "error",
           "-ss", "%.3f" % offset, "-i", path, "-t", "%.3f" % dur,
           "-f", "s16le", "-ar", str(rate), "-ac", str(channels), "pipe:1"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    except OSError as exc:
        log("ffmpeg spawn failed: %s" % exc)
        return False
    try:
        shutil.copyfileobj(proc.stdout, out)
        out.flush()
    finally:
        proc.stdout.close()
        rc = proc.wait()
    if rc != 0:
        log("ffmpeg decode rc=%d for %s" % (rc, os.path.basename(path)))
        return False
    return True


# --- Main loop ----------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=env("ARCHIVE_DIR"))
    p.add_argument("--glob", default=env("ARCHIVE_GLOB", "*.wav"))
    p.add_argument("--prefix", default=env("ARCHIVE_PREFIX"))
    p.add_argument("--time-regex", default=env("ARCHIVE_TIME_REGEX", r"(\d{8}_\d{6})"))
    p.add_argument("--time-format", default=env("ARCHIVE_TIME_FORMAT", "%Y%m%d_%H%M%S"))
    p.add_argument("--file-seconds", type=float, default=float(env("ARCHIVE_FILE_SECONDS", "300")))
    p.add_argument("--delay", type=float, default=float(env("ARCHIVE_DELAY", "3600")))
    p.add_argument("--reindex", type=float, default=float(env("ARCHIVE_REINDEX", "60")))
    p.add_argument("--rate", type=int, default=int(env("OUT_RATE", env("STREAM_RATE", "48000"))))
    p.add_argument("--channels", type=int, default=int(env("OUT_CHANNELS", env("CHANNELS", "1"))))
    p.add_argument("--ffmpeg", default=env("FFMPEG", "ffmpeg"))
    args = p.parse_args(argv)

    if not args.dir:
        p.error("ARCHIVE_DIR is required")
    regex = re.compile(args.time_regex)
    out = sys.stdout.buffer

    log("dir=%s glob=%s prefix=%s delay=%ss file=%ss out=%dHz/%dch"
        % (args.dir, args.glob, args.prefix, args.delay, args.file_seconds,
           args.rate, args.channels))

    play_time = time.time() - args.delay
    index = []
    last_index = 0.0

    while True:
        try:
            now = time.time()
            if now - last_index >= args.reindex or not index:
                names = []
                if os.path.isdir(args.dir):
                    names = [os.path.basename(x) for x in
                             globmod.glob(os.path.join(args.dir, args.glob))]
                index = build_index(names, regex, args.time_format, args.prefix)
                last_index = now
                # Report how far the archive trails real time, so an archive that
                # slips past the delay (-> silence) is visible in logs
                if index:
                    lag = now - (index[-1][0] + args.file_seconds)
                    margin = args.delay - lag
                    if margin < 0:
                        log("NAS lag %ds EXCEEDS delay %ds (short by %ds) -> stream is silence until it catches up"
                            % (int(lag), int(args.delay), int(-margin)))
                    else:
                        log("archive %ds behind real time; delay %ds; margin %ds"
                            % (int(lag), int(args.delay), int(margin)))
                else:
                    log("no matching files found under %s" % args.dir)

            name, offset, dur = find_slot(index, play_time, args.file_seconds)
            if dur <= 0:
                dur = args.file_seconds  # never spin with zero duration

            ok = False
            if name is not None:
                ok = decode_file(out, args.ffmpeg, os.path.join(args.dir, name),
                                 offset, dur, args.rate, args.channels)
            if not ok:
                write_silence(out, dur, args.rate, args.channels)
            play_time += dur
        except BrokenPipeError:
            log("downstream closed; exiting")
            return 0
        except Exception as exc:  # never crash the feed on a transient error
            log("iteration error: %s" % exc)
            try:
                write_silence(out, args.file_seconds, args.rate, args.channels)
            except BrokenPipeError:
                return 0
            play_time += args.file_seconds


if __name__ == "__main__":
    sys.exit(main())
