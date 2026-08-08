# repair_manifests.py — HLS Manifest Repair Tool

## Background

Each recording session creates a timestamp directory on S3 such as:

```
s3://audio-orcasound-net/rpi_orcasound_lab/hls/1748383745/
```

Inside that directory, `upload_s3.py` uploads every `.ts` audio segment and
a `live.m3u8` playlist.  Until May 2026 the playlist was a **rolling window**
(ffmpeg flag `-hls_list_size 5`), meaning it only ever listed the 5 most
recent segments.  As new segments arrived, old ones were silently dropped from
the manifest and the manifest was overwritten on S3.

The result: every session directory contains dozens or hundreds of `.ts` files
but a `live.m3u8` that references only the **last few** of them.  The
orcasite server reads `live.m3u8` to discover segments for spectrogram
generation, so those early segments were effectively invisible.

`repair_manifests.py` fixes this by reconstructing a complete `live.m3u8`
for every affected session directory.

---

## How the repair works

For each timestamp directory the script:

1. **Lists all `.ts` objects** on S3 and sorts them by sequence number
   (e.g. `live000.ts`, `live001.ts`, …).

2. **Fetches the existing `live.m3u8`** and parses it for:
   - `EXT-X-PROGRAM-DATE-TIME` — exact UTC timestamps for the segments that
     were still in the rolling window when the session ended.
   - `EXTINF` durations — used to compute the average segment length
     (typically ~10.005 s).

3. **Finds the anchor**: the earliest segment in the existing manifest that
   has an exact `EXT-X-PROGRAM-DATE-TIME` tag.  If no tag exists, the Unix
   timestamp embedded in the directory name is used as a fallback anchor at
   sequence 0.

4. **Derives approximate times** for every missing segment by stepping from
   the anchor:

   ```
   time(N) ≈ anchor_time + (N − anchor_seq) × avg_duration
   ```

   Segments that were already in the manifest keep their **exact** timestamps.
   Earlier segments get timestamps marked `.000Z` (whole-second precision) to
   signal they are approximate.

5. **Writes a new complete `live.m3u8`** covering every `.ts` file,
   with `EXT-X-MEDIA-SEQUENCE:0` and, for completed sessions,
   `#EXT-X-ENDLIST`.  The live (most recent) directory never gets
   `EXT-X-ENDLIST` since recording is still in progress.

6. **Uploads the repaired manifest** back to S3, overwriting the old one.
   Read operations use the public bucket endpoint (no credentials needed).
   Write operations require AWS credentials (see below).

---

## Prerequisites

```bash
pip3 install boto3
```

AWS credentials must be configured for write access to the bucket.
The standard locations work: `~/.aws/credentials`, environment variables
(`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`), or an IAM instance role.

---

## Usage

```
python3 repair_manifests.py [--node NODE] [--bucket BUCKET]
                            [--days N] [--stop-at TIMESTAMP]
                            [--dry-run]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--node` | `rpi_orcasound_lab` | Node name (S3 path prefix) |
| `--bucket` | `audio-orcasound-net` | S3 bucket name |
| `--days N` | 0 (all) | Only examine directories from the last N days |
| `--stop-at TIMESTAMP` | — | Stop when reaching directories older than this Unix timestamp |
| `--dry-run` | off | Show what would change without uploading anything |

### Typical workflow

```bash
# 1. Preview — see what is broken without changing anything
python3 repair_manifests.py --dry-run

# 2. Repair just the last two weeks first as a sanity check
python3 repair_manifests.py --days 14 --dry-run
python3 repair_manifests.py --days 14

# 3. Repair everything
python3 repair_manifests.py
```

### Sample output

```
Scanning s3://audio-orcasound-net/rpi_orcasound_lab/hls/  (dry_run=False)
Found 47 directories to examine

  [fixed] *live* 1779942622: fixed: 18 → 18 segments
  [fixed]        1779856222: fixed: 5 → 8640 segments
  [fixed]        1779769822: fixed: 5 → 8637 segments
  [ok   ]        1779683422: 8640 segments, manifest complete
  [skip ]        1748383745: no .ts files
  ...

Done. fixed=44  ok=2  skip=1  error=0
```

Status meanings:

| Status | Meaning |
|---|---|
| `fixed` | Manifest was incomplete — now repaired and uploaded |
| `ok` | Manifest already covered all segments — untouched |
| `skip` | Directory has no `.ts` files or an unparseable name |
| `error` | Upload failed — check AWS credentials and bucket permissions |

---

## Accuracy of approximate timestamps

Timestamps for segments that fell outside the old rolling window are
approximate.  The error accumulates at roughly the difference between the
actual segment duration and the average:

- ffmpeg produces very consistent segment lengths (~10.005 s ± 0.001 s)
- For a session that lost 8 000 segments before the anchor, the accumulated
  error at segment 0 is typically **under 10 seconds**

This is sufficient for the orcasite server to locate segments by time and
generate spectrograms.  Exact timestamps are preserved for the tail of each
session (whatever was still in the original rolling manifest).

---

## Going forward

As of the May 2026 update, `stream_sync.sh` uses `-hls_list_size 0` and the
container restarts at midnight via crontab.  Each calendar day now gets its
own timestamp directory with a `live.m3u8` that grows to include every segment
for that day.  `repair_manifests.py` is only needed for sessions recorded
before that change.
