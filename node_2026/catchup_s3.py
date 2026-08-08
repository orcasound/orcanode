#!/usr/bin/env python3
"""
Catches up HLS segment uploads missed during internet outages.
Runs alongside upload_s3.py at low priority (launched with nice -n 10).

Segments that upload_s3.py failed to upload stay on disk.
Every SCAN_INTERVAL seconds this script finds segments older than
STALE_AGE, waits for connectivity, generates a VOD manifest, then
uploads everything at a throttled rate before deleting local copies.

Disk guard: if stranded segments exceed MAX_STRANDED_BYTES, oldest
segments are deleted to protect the SD card.
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

BUCKET = ""
if "BUCKET_TYPE" in os.environ:
    if os.environ["BUCKET_TYPE"] == "prod":
        BUCKET = "audio-orcasound-net"
    elif os.environ["BUCKET_TYPE"] == "custom":
        BUCKET = os.environ["BUCKET_STREAMING"]
    else:
        BUCKET = "dev-streaming-orcasound-net"

# A segment is stranded if it is older than this — gives upload_s3.py
# enough time to handle it first before catchup touches it.
STALE_AGE = SEGMENT_DURATION * 3

SCAN_INTERVAL = 30       # seconds between directory scans
CATCHUP_SLEEP = 2.0      # seconds between individual catch-up uploads
MAX_STRANDED_BYTES = 500 * 1024 * 1024  # 500 MB disk guard

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


def find_stranded_segments():
    """Return sorted list of .ts paths older than STALE_AGE."""
    now = time.time()
    found = []
    for path in glob.glob(os.path.join(HLS_PATH, "*", "*.ts")):
        try:
            if now - os.path.getmtime(path) > STALE_AGE:
                found.append(path)
        except FileNotFoundError:
            pass
    return sorted(found)


def total_size(paths):
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except FileNotFoundError:
            pass
    return total


def enforce_disk_guard(stranded):
    """Delete oldest stranded segments if total exceeds MAX_STRANDED_BYTES."""
    # Sort oldest first (by mtime)
    aged = sorted(stranded, key=lambda p: os.path.getmtime(p))
    while total_size(aged) > MAX_STRANDED_BYTES and aged:
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


def s3_upload(local_path, s3_key):
    """Upload one file; return True on success."""
    try:
        boto3.resource("s3").meta.client.upload_file(local_path, BUCKET, s3_key)
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


def _main():
    log.info("Catchup uploader started.")
    while True:
        time.sleep(SCAN_INTERVAL)

        stranded = find_stranded_segments()
        if not stranded:
            continue

        log.info(f"Found {len(stranded)} stranded segment(s), "
                 f"{total_size(stranded) // 1024} KB total.")

        stranded = enforce_disk_guard(stranded)
        if not stranded:
            continue

        if not is_connected():
            log.info("No internet yet, will retry.")
            continue

        # Group by timestamp directory
        by_dir: dict = {}
        for f in stranded:
            by_dir.setdefault(os.path.dirname(f), []).append(f)

        for ts_dir, ts_files in sorted(by_dir.items()):
            if not is_connected():
                log.info("Lost connectivity, stopping catch-up round.")
                break
            catchup_session(ts_dir, ts_files)


if __name__ == "__main__":
    _main()
