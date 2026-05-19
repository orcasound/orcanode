================================================================================
ORCASOUND HYDROPHONE NODE
================================================================================
Hardware:  Raspberry Pi 4 with Pisound HAT
OS:        Raspberry Pi OS (Bookworm or Trixie)
Container: orcasound/orcanode_val_docker (built locally from Dockerfile)
================================================================================

OVERVIEW
--------
This node captures audio from a Pisound HAT, segments it into HLS (.ts) files
using JACK + ffmpeg, and uploads them to S3. Everything except Docker runs
inside the container. Docker restarts the container automatically on crash or
reboot — no separate systemd service is needed.

On startup stream_sync.sh:
  1. Waits for a sane system clock
  2. Discovers the Pisound ALSA device
  3. Starts jackd with the discovered hw address
  4. Launches ffmpeg to capture from JACK and write HLS segments
  5. Launches upload_s3.py to stream segments to S3 as they are written
  6. Launches catchup_s3.py (nice -n 10) to recover segments missed during
     any internet outage


PREREQUISITES
-------------
  - Raspberry Pi 4 with Pisound HAT installed and recognized by the OS
  - Fresh Raspberry Pi OS image flashed to SD card
  - SSH enabled, Pi connected to the internet
  - AWS credentials with write access to the target S3 bucket


--------------------------------------------------------------------------------
STEP 1 - FIRST BOOT CONFIGURATION
--------------------------------------------------------------------------------

Flash your SD card with Raspberry Pi Imager and set:
  - Hostname (e.g. rpi-orcasound-lab)
  - SSH enabled
  - Username: pi  (or your preferred username)
  - Password
  - WiFi SSID and password (if not using ethernet)

Boot the Pi and SSH in:
  ssh pi@<pi-ip-address>


--------------------------------------------------------------------------------
STEP 2 - CLONE THE REPOSITORY
--------------------------------------------------------------------------------

  sudo apt-get install -y git
  git clone https://github.com/orcasound/orcanode.git ~/orcanode
  cd ~/orcanode/node_val_docker


--------------------------------------------------------------------------------
STEP 3 - CREATE THE .ENV FILE
--------------------------------------------------------------------------------

The .env file holds node-specific config and AWS credentials. It is never
baked into the Docker image — Docker Compose injects it at runtime.

  cp ~/orcanode/node_2026/.env.template ~/orcanode/node_2026/.env
  nano ~/orcanode/node_2026/.env

Required variables:

  NODE_NAME=rpi_orcasound_lab        # unique name for this node
  NODE_TYPE=hls-only                 # hls-only or research
  AUDIO_HW_ID=pisound               # sound card name — verify with: aplay -l
  SAMPLE_RATE=48000
  CHANNELS=2
  SEGMENT_DURATION=10               # HLS segment length in seconds
  FLAC_DURATION=30                  # FLAC archive chunk length (research mode)
  NODE_LOOPBACK=false               # true to monitor audio on local output
  BUCKET_TYPE=prod                  # prod, dev, or custom
  AWS_ACCESS_KEY_ID=<your-key>
  AWS_SECRET_ACCESS_KEY=<your-secret>
  AWS_METADATA_SERVICE_TIMEOUT=5
  AWS_METADATA_SERVICE_NUM_ATTEMPTS=0
  REGION=us-west-2
  SYSLOG_URL=syslog://syslog-a.logdna.com:37043
  SYSLOG_STRUCTURED_DATA='logdna@48950 key="<your-key>" tag="docker"'
  LC_ALL=C.UTF-8
  NO_UPLOAD=false                   # set to true to test pipeline without S3

NOTE: Set NO_UPLOAD=true during initial testing. Segments will accumulate
locally in /tmp/<NODE_NAME>/hls/ so you can verify the pipeline end-to-end
before enabling live uploads.


--------------------------------------------------------------------------------
STEP 4 - RUN SETUP SCRIPT
--------------------------------------------------------------------------------

setup.sh installs Docker, fixes the Docker Hub IPv6 issue (common on Pi OS
Trixie), and adds the user to the docker and audio groups:

  cd ~/orcanode/node_val_docker
  bash setup.sh

The script reboots the Pi when complete. Wait for reboot, then SSH back in.

Note: jackd, ffmpeg, and Python run inside the Docker container — setup.sh
does not install them on the host.


--------------------------------------------------------------------------------
STEP 5 - BUILD AND START THE CONTAINER
--------------------------------------------------------------------------------

Build the image and start (first time only, or after code changes):

  cd ~/orcanode/node_val_docker
  docker compose up -d --build

After the first build, Docker manages the container automatically:
  - restart: always  — restarts on crash without any action needed
  - Docker enabled at boot — container starts on every reboot

Watch the startup logs:

  docker compose logs -f

Healthy startup looks like:
  Time looks sane: <date>
  Success! pisound found at index N. Using address: hw:N,0
  JACK is ready.
  (then silence — ffmpeg and the uploaders run quietly)


--------------------------------------------------------------------------------
STEP 6 - VERIFY THE PIPELINE
--------------------------------------------------------------------------------

Check that HLS segments are being generated locally:

  docker compose exec streaming ls -lh /tmp/<NODE_NAME>/hls/

Each .ts segment should be 150-300 KB. Watch them appear in real time:

  docker compose exec streaming watch -n 1 'ls -lh /tmp/<NODE_NAME>/hls/*/'

If NO_UPLOAD=false, verify segments are reaching S3:

  aws s3 ls s3://audio-orcasound-net/<NODE_NAME>/hls/ --human-readable

Check the upload log for RMS values (healthy signal = RMS > 100):

  docker compose logs -f


--------------------------------------------------------------------------------
CONTAINER MANAGEMENT
--------------------------------------------------------------------------------

  docker compose up -d        # start (after first build)
  docker compose down         # stop
  docker compose restart      # restart
  docker compose logs -f      # follow live logs
  docker compose up -d --build  # rebuild image and restart (after code changes)

Open a shell inside the running container:
  docker compose exec streaming /bin/bash

Check JACK port connections from inside the container:
  docker compose exec streaming jack_lsp -c

You should see system:capture_1/2 connected to ffjack:input_1/2.


--------------------------------------------------------------------------------
INTERNET OUTAGE RECOVERY
--------------------------------------------------------------------------------

upload_s3.py leaves segments on disk when uploads fail. When connectivity
returns, catchup_s3.py finds stranded segments, generates a VOD manifest
(catchup.m3u8), and uploads everything at low priority (2s between segments).

Disk guard: if stranded segments exceed 500 MB, the oldest are deleted first
to protect the SD card.

No configuration required — this runs automatically alongside upload_s3.py.


--------------------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------------------

Docker pull/push fails ("network is unreachable"):
  IPv6 issue on Pi OS Trixie. setup.sh fixes this automatically. If it
  recurs, re-run setup.sh or manually add the Docker Hub IPv4 to /etc/hosts:
    curl -4 -v https://registry-1.docker.io/v2/ 2>&1 | grep "Connected to"
    echo "<IP>    registry-1.docker.io" | sudo tee -a /etc/hosts

JACK "Bus error" or "Cannot lock down memory":
  The container needs a larger /dev/shm. Verify docker-compose.yml contains:
    shm_size: '256m'
  Rebuild and restart if you change it.

Audio device not found (pisound):
  Check the device is visible on the host:
    aplay -l
  Verify AUDIO_HW_ID in .env matches the card name shown by aplay -l.

Segments are silent (RMS near 0):
  JACK ports are not connected. Reconnect manually and restart:
    docker compose exec streaming jack_connect system:capture_1 ffjack:input_1
    docker compose exec streaming jack_connect system:capture_2 ffjack:input_2
    docker compose restart

.env not loading:
  Verify no Windows line endings:
    file ~/orcanode/node_val_docker/.env
  If it shows "CRLF", convert it:
    sed -i 's/\r//' ~/orcanode/node_val_docker/.env

================================================================================
For help, open an issue at: https://github.com/orcasound/orcanode
================================================================================
