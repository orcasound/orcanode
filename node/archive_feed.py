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

    archive_feed.py | ffmpeg -re -f s16le -ar $OUT_RATE -ac <patterns> -i pipe:0 ...

One output channel per pattern, in the order listed: each source is decoded to
mono and interleaved, so several sensors become one multichannel stream.

Config (env / flag):
  ARCHIVE_DIR          directory holding the files
  ARCHIVE_PATTERNS     comma-separated strptime patterns for WHOLE filenames, one
                       per output channel; a pattern both selects its files and
                       parses their start time, e.g. "site_%Y%m%d_%H%M%S.wav"
  ARCHIVE_GAINS        gain dB, one value per channel or one for all (default 0 = off);
                       keep peaks below 0 dBFS to avoid clipping
  ARCHIVE_LABELS       comma-separated name per channel, logged for the record
  ARCHIVE_FILE_SECONDS nominal length of each file, seconds (default 300)
  ARCHIVE_DELAY        seconds to stay behind wall-clock (default 3600)
  ARCHIVE_REINDEX      seconds between directory re-scans (default 60)
  OUT_RATE             output PCM sample rate (default from STREAM_RATE or 48000)
  FFMPEG               ffmpeg binary (default "ffmpeg")

Timestamps in filenames are treated as UTC (the common case for such archives).
"""

import argparse
import array
import calendar
import os
import subprocess
import sys
import time

SAMPLE_BYTES = 2  # s16le
BLOCK_FRAMES = 4800  # interleave in small blocks so memory stays flat


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def log(msg):
    sys.stderr.write("archive_feed: %s\n" % msg)
    sys.stderr.flush()


# --- Pure helpers (unit-tested in test_archive.py) ---------------------------

def parse_timestamp(name, pattern):
    """Return the UTC epoch parsed from `name` via the strptime `pattern`, or
    None if the whole filename doesn't match the pattern."""
    try:
        return calendar.timegm(time.strptime(name, pattern))
    except ValueError:
        return None


def build_index(names, pattern, rate=1):
    """Map filenames -> sorted list of (start, name), keeping only the names that
    match `pattern`. `start` is in frames at `rate`. Sorted ascending."""
    out = []
    for name in names:
        ts = parse_timestamp(name, pattern)
        if ts is not None:
            out.append((ts * rate, name))
    out.sort()
    return out


def find_slot(index, play_pos, file_len):
    """Decide what to emit for `play_pos` given the sorted index.

    Whole frames throughout, so a slot lands exactly on a boundary.

    Returns (name_or_None, offset, duration):
      - a file covering play_pos -> (name, offset into file, remaining dur)
      - a gap before the next file -> (None, 0, frames of silence until it)
      - nothing ahead             -> (None, 0, file_len)  # bounded silence
    """
    if not index:
        return None, 0, file_len
    # latest file whose start <= play_pos
    cur = None
    nxt = None
    for start, name in index:
        if start <= play_pos:
            cur = (start, name)
        else:
            nxt = (start, name)
            break
    if cur is not None:
        start, name = cur
        end = start + file_len
        if play_pos < end:
            return name, play_pos - start, end - play_pos
    # in a gap: silence until the next known file, or one bounded slot
    if nxt is not None:
        return None, 0, max(0, nxt[0] - play_pos)
    return None, 0, file_len


def split_per_channel(value, count, name):
    """Split a comma-separated value into `count` items; one value applies to all."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) == 1:
        return parts * count
    if len(parts) != count:
        raise ValueError("%s has %d values, expected 1 or %d" % (name, len(parts), count))
    return parts


def find_slots(indexes, play_pos, file_len):
    """Per-channel slot for `play_pos`, and the frames they all share.

    The earliest boundary wins, so each channel still fills its own gaps."""
    slots = [find_slot(ix, play_pos, file_len) for ix in indexes]
    dur = min(s[2] for s in slots)
    return slots, dur if dur > 0 else file_len


def interleave(chunks, frames):
    """Interleave equal-length mono s16le `chunks` into one frame-interleaved block."""
    # array("h") is native-endian, which matches s16le on x86/ARM
    if len(chunks) == 1:
        return chunks[0]
    out = array.array("h", bytes(frames * len(chunks) * SAMPLE_BYTES))
    for c, chunk in enumerate(chunks):
        mono = array.array("h")
        mono.frombytes(chunk)
        out[c::len(chunks)] = mono
    return out.tobytes()


# --- IO -----------------------------------------------------------------------

def write_silence(out, frames, channels):
    total = frames * channels * SAMPLE_BYTES
    zeros = bytes(65536)
    while total > 0:
        n = min(total, len(zeros))
        out.write(zeros[:n])
        total -= n
    out.flush()


def spawn_decode(ffmpeg, path, offset, dur, rate, gain_db=0.0):
    """Start ffmpeg decoding `dur` seconds from `path` at `offset` as mono s16le.

    Returns the process, or None if it could not be started."""
    cmd = [ffmpeg, "-nostdin", "-loglevel", "error",
           "-ss", "%.6f" % offset, "-i", path, "-t", "%.6f" % dur]
    if gain_db:
        # set gain here (pre-s16le) so it's applied at full resolution, not after quantizing
        cmd += ["-af", "volume=%gdB" % gain_db]
    cmd += ["-f", "s16le", "-ar", str(rate), "-ac", "1", "pipe:1"]
    try:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE)
    except OSError as exc:
        log("ffmpeg spawn failed: %s" % exc)
        return None


def read_padded(proc, nbytes):
    """Read exactly `nbytes` from `proc`, zero-filling a missing or short source."""
    if proc is None:
        return bytes(nbytes)
    buf = proc.stdout.read(nbytes)
    if len(buf) < nbytes:
        buf += bytes(nbytes - len(buf))
    return buf


def play_slot(out, procs, frames):
    """Write exactly `frames` frames from `procs` (one per channel) to `out`.

    Lockstep reads and padding keep the channels from drifting apart."""
    remaining = frames
    while remaining > 0:
        n = min(BLOCK_FRAMES, remaining)
        chunks = [read_padded(p, n * SAMPLE_BYTES) for p in procs]
        out.write(interleave(chunks, n))
        remaining -= n
    out.flush()


def reap(procs, slots):
    """Close out finished decoders, logging any that failed."""
    for proc, (name, _, _) in zip(procs, slots):
        if proc is None:
            continue
        proc.stdout.close()
        rc = proc.wait()
        if rc != 0:
            log("ffmpeg decode rc=%d for %s" % (rc, name))


# --- Main loop ----------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=env("ARCHIVE_DIR"))
    p.add_argument("--patterns", default=env("ARCHIVE_PATTERNS"))
    p.add_argument("--gains", default=env("ARCHIVE_GAINS"))
    p.add_argument("--labels", default=env("ARCHIVE_LABELS"))
    p.add_argument("--file-seconds", type=float, default=float(env("ARCHIVE_FILE_SECONDS", "300")))
    p.add_argument("--delay", type=float, default=float(env("ARCHIVE_DELAY", "3600")))
    p.add_argument("--reindex", type=float, default=float(env("ARCHIVE_REINDEX", "60")))
    p.add_argument("--rate", type=int, default=int(env("OUT_RATE", env("STREAM_RATE", "48000"))))
    p.add_argument("--ffmpeg", default=env("FFMPEG", "ffmpeg"))
    args = p.parse_args(argv)

    if not args.dir:
        p.error("ARCHIVE_DIR is required")
    if not args.patterns:
        p.error("ARCHIVE_PATTERNS is required")

    patterns = [s.strip() for s in args.patterns.split(",")]
    channels = len(patterns)
    rate = args.rate
    file_frames = int(round(args.file_seconds * rate))

    try:
        gains = [float(g) for g in
                 split_per_channel(args.gains or "0", channels, "ARCHIVE_GAINS")]
        labels = (split_per_channel(args.labels, channels, "ARCHIVE_LABELS")
                  if args.labels else [""] * channels)
    except ValueError as exc:
        p.error(str(exc))

    out = sys.stdout.buffer

    log("dir=%s delay=%ss file=%ss out=%dHz/%dch"
        % (args.dir, args.delay, args.file_seconds, rate, channels))
    for i, pattern in enumerate(patterns):
        log("channel %d: %spattern=%s" % (i, labels[i] and "%s " % labels[i], pattern))
    # Log the gain applied so anyone reusing this audio knows how it was changed.
    if any(gains):
        log("audio processing config: linear gain %s dB"
            % ", ".join("%+g" % g for g in gains))
    else:
        log("audio processing config: none")

    start_frame = int(round((time.time() - args.delay) * rate))
    played_frames = 0
    indexes = [[] for _ in patterns]
    last_index = 0.0

    while True:
        try:
            now = time.time()
            play_pos = start_frame + played_frames

            if now - last_index >= args.reindex or not any(indexes):
                names = os.listdir(args.dir) if os.path.isdir(args.dir) else []
                for i, pattern in enumerate(patterns):
                    indexes[i] = build_index(names, pattern, rate)
                last_index = now
                # Report how far the archive trails real time, so an archive that
                # slips past the delay (-> silence) is visible in logs
                newest = [ix[-1][0] for ix in indexes if ix]
                if newest:
                    lag = now - (min(newest) + file_frames) / float(rate)
                    margin = args.delay - lag
                    if margin < 0:
                        log("archive lag %ds EXCEEDS delay %ds (short by %ds) -> stream is silence until it catches up"
                            % (int(lag), int(args.delay), int(-margin)))
                    else:
                        log("archive %ds behind real time; delay %ds; margin %ds"
                            % (int(lag), int(args.delay), int(margin)))
                for i, ix in enumerate(indexes):
                    if not ix:
                        log("no matching files for channel %d (%s)" % (i, patterns[i]))

            slots, frames = find_slots(indexes, play_pos, file_frames)

            procs = []
            for i, (name, offset, _) in enumerate(slots):
                if name is None:
                    procs.append(None)
                else:
                    procs.append(spawn_decode(args.ffmpeg, os.path.join(args.dir, name),
                                              offset / float(rate), frames / float(rate),
                                              rate, gains[i]))
            log("playing %s (offset %ds, %ds)"
                % (", ".join(s[0] or "-" for s in slots),
                   slots[0][1] // rate, frames // rate))
            try:
                play_slot(out, procs, frames)
            finally:
                reap(procs, slots)
            played_frames += frames
        except BrokenPipeError:
            log("downstream closed; exiting")
            return 0
        except Exception as exc:  # never crash the feed on a transient error
            log("iteration error: %s" % exc)
            try:
                write_silence(out, file_frames, channels)
            except BrokenPipeError:
                return 0
            played_frames += file_frames


if __name__ == "__main__":
    sys.exit(main())
