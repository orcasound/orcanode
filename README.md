# Orcanode — Dockerless Hydrophone Streaming Node (with /tmp Queue Management)

A lightweight, Docker-free streaming node for the [Orcasound](https://www.orcasound.net) hydrophone network. Audio is captured from a [Pisound HAT](https://blokas.io/pisound/) (or any ALSA-compatible device), encoded to HLS by ffmpeg, and uploaded in near-real-time to AWS S3 for playback in the Orcasound web app.

This variant adds **bounded /tmp storage** and **background catchup uploads** to handle intermittent connectivity on a Raspberry Pi with a 32–64 GB SD card.

---

## The /tmp storage problem and solution

### What goes wrong without queue management

Each service session creates a new timestamped HLS directory in `/tmp/<NODE_NAME>/hls/<timestamp>/`. ffmpeg writes 10-second MPEG-TS segments there continuously; `upload_s3.py` removes each file after a successful S3 upload. Under normal conditions, only a handful of segments ever accumulate locally.

When internet connectivity drops, uploads fail but ffmpeg keeps writing. Segments pile up in the current session's directory. When the service restarts (e.g. on reboot or after a JACK crash), a **new** session directory is created — but the old directory, with all its unuploaded segments, is never touched again. Over days or weeks of intermittent connectivity, these orphaned directories can fill the SD card.

### How this version solves it

Two mechanisms work together:

**1. Hard disk limit at startup (`prune_old_hls_dirs` in `stream_sync.sh`)**

Before starting the new session, the script counts existing old HLS directories. If there are more than `MAX_HLS_DIRS - 1` (default: 7 old + 1 current = 8 total), the oldest directories are deleted immediately. This is a hard safety valve that guarantees `/tmp` stays bounded even after extended outages.

**2. Background catchup uploader (`upload_old_hls.py`)**

After pruning, a background process scans for old HLS directories and uploads their content to S3, then deletes each directory. It runs at a lower CPU priority (`nice +10`) so it never competes with the real-time uploader.

For each old directory it:
- Builds a **proper VOD HLS manifest** (`vod.m3u8`) listing all remaining `.ts` files — the original `live.m3u8` written by ffmpeg is a rolling 5-segment live manifest and is incomplete for historical playback.
- Uploads segments newest-directory-first (most recent audio reaches S3 soonest after an outage).
- Sleeps briefly between file uploads so the real-time uploader has priority on the network connection.
- Deletes the directory only after every upload succeeds. If any upload fails, the directory is left in place and retried on the next service start.

---

## Architecture

```
stream_sync.sh (on service start)
  │
  ├─ [1] prune_old_hls_dirs()
  │       • counts HLS session dirs in /tmp
  │       • deletes oldest if count > MAX_HLS_DIRS
  │
  ├─ [2] jackd  ──────────────────────────────────────────────────┐
  │         system:capture_1/2 → ffjack:input_1/2                 │
  │                                                         [optional
  ├─ [3] ffmpeg (-f jack -i ffjack)                        loopback]
  │         PCM → AAC @ 48 kHz, 10-second MPEG-TS segments
  │         writes to /tmp/<NODE_NAME>/hls/<current_ts>/
  │              live.m3u8  (rolling, 5-segment live manifest)
  │              live000.ts, live001.ts, …
  │
  ├─ [4] upload_s3.py  (foreground, real-time priority)
  │         inotify IN_CLOSE_WRITE / IN_MOVED_TO on current_ts dir
  │         • validates file size
  │         • computes RMS (warns on silence)
  │         • uploads to S3: <NODE_NAME>/hls/<current_ts>/<file>
  │         • removes local file after confirmed upload
  │         • after first .ts: uploads latest.txt so player can find stream
  │
  └─ [5] upload_old_hls.py  (background, nice +10)
            scans /tmp/<NODE_NAME>/hls/ for dirs != current_ts
            for each old dir (newest-first):
              • builds vod.m3u8 from remaining .ts files
              • uploads segments + manifests to S3
              • deletes directory after all uploads confirmed
            exits when backlog is clear
```

### Disk space bounds

With default `MAX_HLS_DIRS=8` and 10-second segments at ~160 kbps AAC:

| Scenario | Storage |
|---|---|
| Normal operation (uploads keeping up) | < 5 MB |
| 1-hour internet outage (one session) | ~72 MB |
| 8 sessions capped by MAX_HLS_DIRS | ~576 MB worst case |

Adjust `MAX_HLS_DIRS` in `stream_sync.sh` to trade off historical coverage vs. disk safety. A value of 4–6 is conservative for a 32 GB card.

---

## Key files

| File | Purpose |
|---|---|
| `stream_sync.sh` | Main orchestration. Prunes old HLS dirs, starts jackd + ffmpeg, launches uploaders. |
| `upload_s3.py` | Real-time uploader. Watches current session dir via inotify; uploads and deletes each segment as it is written. |
| `upload_old_hls.py` | Background catchup uploader. Processes old session directories on startup, builds VOD manifests, uploads, and deletes. |
| `orcanode.service` | Systemd unit that runs `stream_sync.sh` as the `pi` user on boot. |
| `setup.sh` | One-time dependency installer (jackd2, ffmpeg, Python venv). |
| `limits.conf` | PAM limits that grant the `audio` group real-time scheduling priority (required by JACK). |
| `.env` | Node configuration — credentials, node name, sample rate, bucket. **Never commit this file.** |
| `jack.c` | Reference copy of ffmpeg's JACK input device source (informational only; not built locally). |

### Node types (`NODE_TYPE` in `.env`)

| Value | Behavior |
|---|---|
| `hls-only` | HLS segments only (AAC/MPEG-TS). Normal production mode. |
| `research` | HLS segments **plus** 30-second FLAC archives uploaded to a separate S3 path. |
| `debug` | Streams raw MPEG-TS over UDP to localhost for local inspection. |
| `dev-virt-s3` | Loops a local `.wav` file instead of live audio — useful for offline testing. |

### Timestamp-based stream versioning

Each time the service starts, `stream_sync.sh` records a Unix timestamp and creates `/tmp/<NODE_NAME>/hls/<timestamp>/`. This directory becomes the S3 key prefix for that session. The Orcasound player reads `latest.txt` (uploaded after the first segment) to find the current session timestamp, so it always plays the live stream regardless of restarts.

---

## Setup on a fresh Raspberry Pi 4

These steps assume **Raspberry Pi OS Trixie (64-bit)** and a Pisound HAT (or compatible ALSA audio interface). Bookworm also works. Run all commands as the `pi` user unless otherwise noted.

### 1. Flash and first boot

Flash Raspberry Pi OS (Trixie Lite recommended) using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Enable SSH and set hostname/credentials in the imager's advanced settings before writing.

### 2. Update the system

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 3. Install dependencies

```bash
# JACK audio server
sudo apt-get install -y jackd2

# ffmpeg (for HLS encoding)
sudo apt-get install -y ffmpeg

# Python virtual environment
sudo apt-get install -y python3-venv python3-pip

# Create venv and install Python dependencies
python3 -m venv ~/venv
~/venv/bin/pip install --upgrade pip
~/venv/bin/pip install boto3 inotify numpy
```

When the JACK installer asks **"Enable realtime process priority?"**, answer **Yes**.

### 4. Add the pi user to the audio group

```bash
sudo usermod -aG audio pi
```

### 5. Configure real-time audio limits

Copy `limits.conf` from this repo to `/etc/security/limits.conf`, or append the following lines manually:

```
* soft    memlock    unlimited
* hard    memlock    unlimited
@audio - memlock 256000
@audio - rtprio 75
```

These lines allow JACK to lock memory and run at real-time priority — both required for glitch-free audio.

### 6. Clone this repo

```bash
mkdir -p ~/orcanode
cd ~/orcanode
git clone https://github.com/orcasound/orcanode.git node
cd node
```

### 7. Create the `.env` file

Copy the template and fill in your values:

```bash
cp .env.example .env   # or create from scratch
nano .env
```

Required variables:

```bash
NODE_NAME=rpi_orcasound_lab      # S3 key prefix — must be unique per node
AUDIO_HW_ID=pisound              # ALSA card name (check with: aplay -l)
SAMPLE_RATE=48000
CHANNELS=2
SEGMENT_DURATION=10
FLAC_DURATION=30
NODE_TYPE=hls-only               # see node types above
NODE_LOOPBACK=false

BUCKET_TYPE=prod                 # prod | dev | custom
# BUCKET_STREAMING=my-bucket     # only needed when BUCKET_TYPE=custom

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
REGION=us-west-2
```

**Never commit `.env`** — it is listed in `.gitignore`.

### 8. Install the systemd service

```bash
sudo cp orcanode.service /etc/systemd/system/orcanode.service
```

Open the file and verify the paths match your setup:

```bash
sudo nano /etc/systemd/system/orcanode.service
```

Key lines to check:
```ini
WorkingDirectory=/home/pi/orcanode/node
ExecStart=/bin/bash /home/pi/orcanode/node/stream_sync.sh
```

Enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable orcanode
```

### 9. Reboot

```bash
sudo reboot
```

Group membership changes (audio) and PAM limits require a full reboot to take effect.

### 10. Verify streaming

After reboot, check that everything started cleanly:

```bash
# Watch live logs
journalctl -u orcanode -f

# Confirm ffmpeg is running
ps aux | grep ffmpeg

# Check HLS session directories (should see current + any being caught up)
ls -lt /tmp/rpi_orcasound_lab/hls/

# Check ffmpeg's own log
cat /tmp/rpi_orcasound_lab/ffmpeg.log

# Check for out-of-memory kills
sudo dmesg | grep -E "oom|killed|Out of memory" | tail -10
```

To monitor disk usage of the HLS queue:

```bash
du -sh /tmp/rpi_orcasound_lab/hls/*/
```

---

## Day-to-day operations

```bash
sudo systemctl start orcanode      # start
sudo systemctl stop orcanode       # stop
sudo systemctl restart orcanode    # restart
sudo systemctl status orcanode     # quick status

journalctl -u orcanode -f          # live logs
journalctl -u orcanode | grep upload_s3 | tail -30        # real-time upload activity
journalctl -u orcanode | grep upload_old_hls | tail -30   # backlog upload activity
```

### SSH access via Tailscale

```bash
ssh pi@<your-node>.tail70a76c.ts.net
```

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Service won't start | `journalctl -u orcanode -f` |
| No audio / silence warnings | `cat /tmp/<NODE_NAME>/ffmpeg.log` |
| S3 uploads failing | `journalctl -u orcanode \| grep upload_s3` |
| Old session dirs not being cleaned up | `journalctl -u orcanode \| grep upload_old_hls` — check for upload errors |
| /tmp still growing despite MAX_HLS_DIRS | Lower `MAX_HLS_DIRS` in `stream_sync.sh`; check that pruning log lines appear at startup |
| JACK won't start | Check `limits.conf` was applied and reboot was done; check `aplay -l` shows the device |
| HLS segments exist but player can't find stream | Check `latest.txt` was uploaded to S3 |
| Out of memory | `sudo dmesg \| grep -E "oom\|killed"` — reduce ffmpeg thread count in `stream_sync.sh` |

---

## Contributing

Pull requests welcome. Please keep `.env` out of commits — it holds credentials.
