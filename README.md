# Orcanode — Dockerless Hydrophone Streaming Node

A lightweight, Docker-free streaming node for the [Orcasound](https://www.orcasound.net) hydrophone network. Audio is captured from a [Pisound HAT](https://blokas.io/pisound/) (or any ALSA-compatible device), encoded to HLS by ffmpeg, and uploaded in near-real-time to AWS S3 for playback in the Orcasound web app.

---

## How it works

```
Hydrophone
    │
    ▼
Pisound HAT (USB or I2S audio interface)
    │  ALSA (hw:pisound)
    ▼
jackd  ─────────────────────────────────────────────────────────────┐
    │  JACK audio graph                                              │
    │  system:capture_1/2  →  ffjack:input_1/2                      │
    ▼                                                                │
ffmpeg (-f jack -i ffjack)                                  [loopback]
    │                                                       system:playback
    │  Encode: PCM → AAC @ 48 kHz
    │  Segment: 10-second MPEG-TS chunks
    ▼
/tmp/<NODE_NAME>/hls/<timestamp>/
    ├── live.m3u8          ← rolling HLS manifest (5 segments)
    ├── live000.ts
    ├── live001.ts
    └── ...
    │
    ▼ (inotify IN_CLOSE_WRITE / IN_MOVED_TO)
upload_s3.py
    │  • Checks file size (skips empties)
    │  • Computes RMS audio level (warns on silence)
    │  • Uploads to S3 with key: <NODE_NAME>/hls/<timestamp>/<file>
    │  • After first .ts segment: uploads latest.txt
    ▼
S3 bucket  (audio-orcasound-net  or  dev-streaming-orcasound-net)
    └── <NODE_NAME>/hls/<timestamp>/live.m3u8  ← Orcasound player reads this
```

### Key files

| File | Purpose |
|---|---|
| `stream_sync.sh` | Main orchestration script. Waits for NTP sync, starts jackd, runs ffmpeg, connects JACK ports, launches uploader. |
| `upload_s3.py` | Watches HLS output dir with inotify; uploads each completed segment and manifest to S3. |
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

Flash Raspberry Pi OS (Bookworm Lite recommended) using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Enable SSH and set hostname/credentials in the imager's advanced settings before writing.

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

# Check that HLS segments are being created
ls -la /tmp/rpi_orcasound_lab/hls/

# Check ffmpeg's own log
cat /tmp/rpi_orcasound_lab/ffmpeg.log

# Check for out-of-memory kills
sudo dmesg | grep -E "oom|killed|Out of memory" | tail -10
```

---

## Day-to-day operations

```bash
sudo systemctl start orcanode      # start
sudo systemctl stop orcanode       # stop
sudo systemctl restart orcanode    # restart
sudo systemctl status orcanode     # quick status

journalctl -u orcanode -f          # live logs
journalctl -u orcanode | grep upload_s3 | tail -30   # upload activity
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
| JACK won't start | Check `limits.conf` was applied and reboot was done; check `aplay -l` shows the device |
| HLS segments exist but player can't find stream | Check `latest.txt` was uploaded to S3 |
| Out of memory | `sudo dmesg \| grep -E "oom\|killed"` — reduce ffmpeg thread count in `stream_sync.sh` |

---

## Contributing

Pull requests welcome. Please keep `.env` out of commits — it holds credentials.
