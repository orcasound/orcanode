#!/usr/bin/env python3
"""
repair_manifests.py

Scans S3 timestamp directories for a node and repairs any live.m3u8 that
covers fewer segments than the directory actually contains.  This fixes
sessions recorded when hls_list_size was small (e.g. 5), leaving most
segments with no manifest entry.

For each missing segment the script derives an approximate
EXT-X-PROGRAM-DATE-TIME by anchoring on the exact timestamp of the first
segment already in the manifest and stepping backwards by the average
EXTINF duration.  Fallback: use the Unix timestamp in the directory name.

The most recent (live) directory is never given EXT-X-ENDLIST.
All older directories receive it so players know the stream is complete.

Usage:
    python3 repair_manifests.py [--node NODE_NAME] [--bucket BUCKET]
                                [--days N] [--dry-run]

Defaults:
    --node   rpi_orcasound_lab
    --bucket audio-orcasound-net
    --days   all directories
"""

import argparse
import re
import sys
from datetime import datetime, timezone, timedelta

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

SEGMENT_DURATION_DEFAULT = 10.0


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def list_timestamp_dirs(s3, bucket, node_name):
    """Return sorted list of timestamp prefixes like 'node/hls/1748383745/'."""
    prefixes = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=f"{node_name}/hls/",
        Delimiter='/'
    ):
        for cp in page.get('CommonPrefixes', []):
            prefixes.append(cp['Prefix'])
    return sorted(prefixes)


def list_ts_files(s3, bucket, prefix):
    """Return .ts filenames in prefix, sorted by embedded sequence number."""
    files = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            name = obj['Key'].split('/')[-1]
            if name.endswith('.ts'):
                files.append(name)

    def seq(name):
        m = re.search(r'(\d+)', name)
        return int(m.group(1)) if m else 0

    return sorted(files, key=seq)


def fetch_object(s3, bucket, key):
    """Return object body as str, or None if not found."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp['Body'].read().decode('utf-8')
    except ClientError as e:
        if e.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def put_object(s3, bucket, key, body):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode('utf-8'),
        ContentType='application/x-mpegurl',
    )


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------

def parse_manifest(content):
    """
    Returns dict:
        target_duration : int
        media_sequence  : int
        segments        : list of {filename, duration, pdt}
                          pdt is the EXT-X-PROGRAM-DATE-TIME string or None
    """
    segments = []
    target_duration = 10
    media_sequence = 0
    pending_pdt = None
    pending_duration = None

    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith('#EXT-X-TARGETDURATION:'):
            try:
                target_duration = int(line.split(':', 1)[1])
            except ValueError:
                pass
        elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                media_sequence = int(line.split(':', 1)[1])
            except ValueError:
                pass
        elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
            pending_pdt = line.split(':', 1)[1]
        elif line.startswith('#EXTINF:'):
            try:
                pending_duration = float(line[8:].split(',')[0])
            except ValueError:
                pending_duration = SEGMENT_DURATION_DEFAULT
        elif line.endswith('.ts') and not line.startswith('#'):
            segments.append({
                'filename': line,
                'duration': pending_duration or SEGMENT_DURATION_DEFAULT,
                'pdt': pending_pdt,
            })
            pending_pdt = None
            pending_duration = None

    return {
        'target_duration': target_duration,
        'media_sequence': media_sequence,
        'segments': segments,
    }


# ---------------------------------------------------------------------------
# Manifest reconstruction
# ---------------------------------------------------------------------------

def seq_num(filename):
    m = re.search(r'(\d+)', filename)
    return int(m.group(1)) if m else 0


def build_manifest(all_ts, parsed, session_unix, add_endlist):
    """
    Build a complete manifest string covering every file in all_ts.

    Exact PDT tags are kept for segments already in parsed['segments'].
    Approximate PDTs are derived for the rest by anchoring on the earliest
    known exact time and stepping by the average EXTINF duration.
    """
    target_duration = parsed['target_duration']
    existing = {s['filename']: s for s in parsed['segments']}

    # Average duration from existing entries
    durations = [s['duration'] for s in parsed['segments']]
    avg_dur = sum(durations) / len(durations) if durations else SEGMENT_DURATION_DEFAULT

    # Anchor: earliest segment in the existing manifest that has a PDT tag
    ref_dt = None
    ref_sn = None
    for seg in parsed['segments']:
        if seg['pdt']:
            try:
                dt = datetime.fromisoformat(seg['pdt'].replace('Z', '+00:00'))
                sn = seq_num(seg['filename'])
                if ref_dt is None or sn < ref_sn:
                    ref_dt = dt
                    ref_sn = sn
            except ValueError:
                pass

    # Fallback anchor: directory Unix timestamp → seq 0
    if ref_dt is None:
        ref_dt = datetime.fromtimestamp(session_unix, tz=timezone.utc)
        ref_sn = 0

    lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        f'#EXT-X-TARGETDURATION:{target_duration}',
        '#EXT-X-MEDIA-SEQUENCE:0',
    ]

    for filename in all_ts:
        sn = seq_num(filename)
        if filename in existing and existing[filename]['pdt']:
            pdt = existing[filename]['pdt']
            duration = existing[filename]['duration']
        else:
            offset = (sn - ref_sn) * avg_dur
            approx = ref_dt + timedelta(seconds=offset)
            pdt = approx.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            duration = avg_dur

        lines.append(f'#EXT-X-PROGRAM-DATE-TIME:{pdt}')
        lines.append(f'#EXTINF:{duration:.6f},')
        lines.append(filename)

    if add_endlist:
        lines.append('#EXT-X-ENDLIST')

    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Per-directory processing
# ---------------------------------------------------------------------------

def process_dir(s3, bucket, prefix, is_live, dry_run, s3_write=None):
    """
    Returns (status, message) where status is one of:
        'fixed'  — manifest was incomplete and has been repaired
        'ok'     — manifest already covers all segments
        'skip'   — directory skipped (no .ts files or bad name)
        'error'  — something went wrong
    """
    parts = prefix.rstrip('/').split('/')
    try:
        session_unix = int(parts[-1])
    except ValueError:
        return 'skip', f'cannot parse timestamp from {prefix}'

    all_ts = list_ts_files(s3, bucket, prefix)
    if not all_ts:
        return 'skip', 'no .ts files'

    manifest_key = prefix + 'live.m3u8'
    content = fetch_object(s3, bucket, manifest_key)

    if content:
        parsed = parse_manifest(content)
    else:
        parsed = {'target_duration': 10, 'media_sequence': 0, 'segments': []}

    have = len(parsed['segments'])
    need = len(all_ts)

    if have >= need:
        return 'ok', f'{need} segments, manifest complete'

    add_endlist = not is_live
    new_content = build_manifest(all_ts, parsed, session_unix, add_endlist)

    if not dry_run:
        try:
            put_object(s3_write or s3, bucket, manifest_key, new_content)
        except Exception as e:
            return 'error', str(e)

    verb = 'would fix' if dry_run else 'fixed'
    return 'fixed', f'{verb}: {have} → {need} segments'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--node',   default='rpi_orcasound_lab',
                        help='Node name (S3 prefix, default: rpi_orcasound_lab)')
    parser.add_argument('--bucket', default='audio-orcasound-net',
                        help='S3 bucket (default: audio-orcasound-net)')
    parser.add_argument('--days',   type=int, default=0,
                        help='Only process directories from the last N days (0 = all)')
    parser.add_argument('--stop-at', type=int, default=0, metavar='TIMESTAMP',
                        help='Stop processing at this directory timestamp (inclusive); '
                             'directories older than this are skipped')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without uploading anything')
    args = parser.parse_args()

    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    s3_write = None if args.dry_run else boto3.client('s3')

    print(f"Scanning s3://{args.bucket}/{args.node}/hls/  (dry_run={args.dry_run})")
    dirs = list_timestamp_dirs(s3, args.bucket, args.node)
    if not dirs:
        print("No timestamp directories found.")
        sys.exit(0)

    # Optionally limit to recent N days
    if args.days > 0:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
        cutoff_unix = int(cutoff.timestamp())
        dirs = [d for d in dirs
                if _dir_unix(d) >= cutoff_unix]

    print(f"Found {len(dirs)} director{'y' if len(dirs)==1 else 'ies'} to examine\n")

    most_recent = dirs[-1] if dirs else None
    dirs = list(reversed(dirs))
    counts = {'fixed': 0, 'ok': 0, 'skip': 0, 'error': 0}

    for prefix in dirs:
        ts_str = prefix.rstrip('/').split('/')[-1]
        if args.stop_at and _dir_unix(prefix) < args.stop_at:
            print(f"  Reached stop-at threshold ({args.stop_at}), stopping.")
            break
        is_live = (prefix == most_recent)
        status, msg = process_dir(s3, args.bucket, prefix, is_live, args.dry_run, s3_write)
        tag = '*live*' if is_live else '      '
        print(f"  [{status:5s}] {tag} {ts_str}: {msg}")
        counts[status] += 1

    print(f"\nDone. fixed={counts['fixed']}  ok={counts['ok']}  "
          f"skip={counts['skip']}  error={counts['error']}")


def _dir_unix(prefix):
    try:
        return int(prefix.rstrip('/').split('/')[-1])
    except ValueError:
        return 0


if __name__ == '__main__':
    main()
