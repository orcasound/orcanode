#!/usr/bin/env python3
"""
Catches up HLS segment and FLAC uploads missed during internet outages.
Runs alongside upload_s3.py (and upload_flac_s3.py on research nodes) at
low priority (launched with nice -n 10).

Segments that upload_s3.py failed to upload stay on disk.
Every SCAN_INTERVAL seconds this script finds segments older than
STALE_AGE, waits for connectivity, generates a VOD manifest, then
uploads everything at a throttled rate before deleting local copies.

Disk guard: if stranded segments exceed MAX_STRANDED_BYTES, oldest
segments are deleted to protect the SD card.

FLAC files that upload_flac_s3.py failed to upload are handled the same
way (minus the manifest), with their own disk guard of MAX_STRANDED_FLAC_BYTES.
"""

import os
import sys
import time
import glob
import logging
import urllib.request
import boto3

from logdna_handler import attach_logdna_handler

NODE = os.environ["NODE_NAME"]
SEGMENT_DURATION = int(os.environ.get("SEGMENT_DURATION", "10").strip())
BASEPATH = os.path.join("/tmp", NODE)
HLS_PATH = os.path.join(BASEPATH, "hls")
FLAC_PATH = os.path.join(BASEPATH, "flac")
FLAC_DURATION = int(os.environ.get("FLAC_DURATION", "30").strip())

BUCKET = ""
if "BUCKET_TYPE" in os.environ:
    if os.environ["BUCKET_TYPE"] == "prod":
        BUCKET = "audio-orcasound-net"
    elif os.environ["BUCKET_TYPE"] == "custom":
        BUCKET = os.environ["BUCKET_STREAMING"]
    else:
        BUCKET = "dev-streaming-orcasound-net"

# Same bucket selection as upload_flac_s3.py. .get() for the custom case so
# hls-only nodes without BUCKET_ARCHIVE set don't crash; FLAC catch-up is
# simply skipped when ARCHIVE_BUCKET is empty.
ARCHIVE_BUCKET = ""
if "BUCKET_TYPE" in os.environ:
    if os.environ["BUCKET_TYPE"] == "prod":
        ARCHIVE_BUCKET = "archive-orcasound-net"
    elif os.environ["BUCKET_TYPE"] == "custom":
        ARCHIVE_BUCKET = os.environ.get("BUCKET_ARCHIVE", "")
    else:
        ARCHIVE_BUCKET = "dev-archive-orcasound-net"

# A segment is stranded if it is older than this — gives upload_s3.py
# enough time to handle it first before catchup touches it.
STALE_AGE = SEGMENT_DURATION * 3
# Same idea for FLAC. ffmpeg keeps writing to the current FLAC file, so its
# mtime stays fresh and it is never picked up while still being recorded.
FLAC_STALE_AGE = FLAC_DURATION * 3

SCAN_INTERVAL = 30       # seconds between directory scans
CATCHUP_SLEEP = 2.0      # seconds between individual catch-up uploads
MAX_STRANDED_BYTES = 500 * 1024 * 1024  # 500 MB disk guard
MAX_STRANDED_FLAC_BYTES = 500 * 1024 * 1024  # separate 500 MB guard for FLAC

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("catchup.%(funcName)s: %(message)s"))
log.addHandler(handler)
# INFO here (vs upload_s3.py's default WARNING) — catch-up activity itself
# (stranded segments found, disk guard deletions) is worth centralizing,
# since it signals the node had connectivity trouble.
attach_logdna_handler(log, NODE, app="catchup_s3", level=logging.INFO)


def is_connected():
    try:
        urllib.request.urlopen("https://s3.amazonaws.com", timeout=5)
        return True
    except Exception:
        return False


def find_stale_files(pattern, stale_age):
    """Return sorted list of paths matching pattern older than stale_age."""
    now = time.time()
    found = []
    for path in glob.glob(pattern):
        try:
            if now - os.path.getmtime(path) > stale_age:
                found.append(path)
        except FileNotFoundError:
            pass
    return sorted(found)


def find_stranded_segments():
    """Return sorted list of .ts paths older than STALE_AGE."""
    return find_stale_files(os.path.join(HLS_PATH, "*", "*.ts"), STALE_AGE)


def find_stranded_flac():
    """Return sorted list of .flac paths older than FLAC_STALE_AGE."""
    return find_stale_files(os.path.join(FLAC_PATH, "*.flac"), FLAC_STALE_AGE)


def total_size(paths):
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except FileNotFoundError:
            pass
    return total


def enforce_disk_guard(stranded, max_bytes=MAX_STRANDED_BYTES):
    """Delete oldest stranded files if total exceeds max_bytes."""
    # Sort oldest first (by mtime)
    aged = sorted(stranded, key=lambda p: os.path.getmtime(p))
    while total_size(aged) > max_bytes and aged:
        victim = aged.pop(0)
        try:
            os.remove(victim)
            log.warning(f"Disk guard: deleted {os.path.basename(victim)}")
        except FileNotFoundError:
            pass
    return aged  # updated list after deletions


def write_catchup_manifest(ts_files, manifest_path):
    """Write a VOD HLS manifest for the given segment files."""
    with open(manifest_path, "w") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION}\n")
        for ts_file in ts_files:
            f.write(f"#EXTINF:{SEGMENT_DURATION}.0,\n")
            f.write(os.path.basename(ts_file) + "\n")
        f.write("#EXT-X-ENDLIST\n")


def s3_upload(local_path, s3_key, bucket=BUCKET, extra_args=None):
    """Upload one file; return True on success."""
    try:
        boto3.resource("s3").meta.client.upload_file(
            local_path, bucket, s3_key, ExtraArgs=extra_args)
        return True
    except Exception as e:
        log.warning(f"Upload failed {os.path.basename(local_path)}: {e}")
        return False


def s3_key_for(local_path):
    return os.path.relpath(local_path, "/tmp")


def catchup_session(ts_dir, ts_files):
    """Upload the catchup manifest + segments for one timestamp directory."""
    timestamp = os.path.basename(ts_dir)

    manifest_path = os.path.join(ts_dir, "catchup.m3u8")
    write_catchup_manifest(ts_files, manifest_path)

    manifest_key = s3_key_for(manifest_path)
    if not s3_upload(manifest_path, manifest_key):
        os.remove(manifest_path)
        return False
    os.remove(manifest_path)
    log.info(f"Catchup manifest uploaded for {timestamp} ({len(ts_files)} segments)")

    for ts_file in ts_files:
        if not is_connected():
            log.warning("Connectivity lost mid-catchup, pausing.")
            return False
        if s3_upload(ts_file, s3_key_for(ts_file)):
            try:
                os.remove(ts_file)
            except FileNotFoundError:
                pass
            log.debug(f"Caught up: {os.path.basename(ts_file)}")
        else:
            return False
        time.sleep(CATCHUP_SLEEP)

    return True


def catchup_hls_round():
    """One scan + catch-up pass over the HLS timestamp directories."""
    stranded = find_stranded_segments()
    if not stranded:
        return

    log.info(f"Found {len(stranded)} stranded segment(s), "
             f"{total_size(stranded) // 1024} KB total.")

    stranded = enforce_disk_guard(stranded)
    if not stranded:
        return

    if not is_connected():
        log.info("No internet yet, will retry.")
        return

    # Group by timestamp directory
    by_dir: dict = {}
    for f in stranded:
        by_dir.setdefault(os.path.dirname(f), []).append(f)

    for ts_dir, ts_files in sorted(by_dir.items()):
        if not is_connected():
            log.info("Lost connectivity, stopping catch-up round.")
            break
        catchup_session(ts_dir, ts_files)


def catchup_flac(flac_files):
    """Upload stranded FLAC files to the archive bucket, oldest first."""
    for flac_file in flac_files:
        if not is_connected():
            log.warning("Connectivity lost mid-FLAC-catchup, pausing.")
            return False
        if s3_upload(flac_file, s3_key_for(flac_file), bucket=ARCHIVE_BUCKET,
                     extra_args={"ContentType": "audio/flac"}):
            try:
                os.remove(flac_file)
            except FileNotFoundError:
                pass
            log.debug(f"Caught up: {os.path.basename(flac_file)}")
        else:
            return False
        time.sleep(CATCHUP_SLEEP)
    log.info(f"FLAC catch-up complete ({len(flac_files)} file(s))")
    return True


def catchup_flac_round():
    """One scan + catch-up pass over the FLAC directory."""
    stranded = find_stranded_flac()
    if not stranded:
        return

    log.info(f"Found {len(stranded)} stranded FLAC file(s), "
             f"{total_size(stranded) // 1024} KB total.")

    stranded = enforce_disk_guard(stranded, MAX_STRANDED_FLAC_BYTES)
    if not stranded:
        return

    if not ARCHIVE_BUCKET:
        log.warning("No archive bucket configured (BUCKET_TYPE/BUCKET_ARCHIVE), "
                    "leaving FLAC files on disk.")
        return

    if not is_connected():
        log.info("No internet yet, will retry FLAC.")
        return

    catchup_flac(stranded)


def _main():
    log.info("Catchup uploader started.")
    while True:
        time.sleep(SCAN_INTERVAL)
        catchup_hls_round()
        catchup_flac_round()


if __name__ == "__main__":
    _main()
