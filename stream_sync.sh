#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC

# Ensure system binaries are in PATH (needed when run under systemd)
export PATH=/usr/bin:/usr/local/bin:/usr/sbin:/bin:$PATH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
    echo "Loaded .env from $SCRIPT_DIR"
else
    echo "WARNING: .env file not found at $SCRIPT_DIR/.env"
fi

# --- 0. PREFLIGHT CHECKS ---
if ! command -v jackd &> /dev/null; then
    echo "ERROR: jackd is not installed. Please run setup.sh first."
    exit 1
fi
if ! command -v jack_wait &> /dev/null; then
    echo "ERROR: jack_wait is not installed. Please run setup.sh first."
    exit 1
fi
if ! command -v jack_connect &> /dev/null; then
    echo "ERROR: jack_connect is not installed. Please run setup.sh first."
    exit 1
fi
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg is not installed. Please install it with: sudo apt-get install -y ffmpeg"
    exit 1
fi

# --- 1. TIME SYNCHRONIZATION ---
wait_for_sync() {
    echo "Waiting for time synchronization..."
    local max_wait=60
    local elapsed=0

    # If chrony is present (Raspberry Pi OS Bookworm default), use it
    if command -v chronyc &>/dev/null; then
        echo "Using chrony..."
        # waitsync args: max-tries interval min-skew clock-updates
        chronyc waitsync 30 0 0.01 1 && echo "Time synchronized." && return 0
        echo "ERROR: Time sync timed out, aborting."
        exit 1
    fi

    # Fall back to systemd-timesyncd (NTP already enabled by default on Pi OS)
    while [ $elapsed -lt $max_wait ]; do
        if timedatectl status 2>/dev/null | grep -q "System clock synchronized: yes"; then
            echo "Time synchronized."; return 0
        fi
        if timedatectl show -p SystemClockSynchronized --value 2>/dev/null | grep -q "yes"; then
            echo "Time synchronized."; return 0
        fi
        echo "Waiting for time sync... (${elapsed}s)"
        sleep 2; elapsed=$((elapsed + 2))
    done

    echo "ERROR: Time sync timed out after ${max_wait}s, aborting."
    exit 1
}

wait_for_sync
echo "Time synchronized successfully: $(date)"

# --- 2. ACTIVATE VIRTUAL ENVIRONMENT ---
# NOTE: venv must have boto3, inotify, and numpy installed:
#   /home/pi/venv/bin/pip install boto3 inotify numpy
source /home/pi/venv/bin/activate

# --- 3. VARIABLES (MOVED AFTER SYNC) ---
# Get current timestamp (Now that we are synced, this will be accurate)
timestamp=$(date +%s)

if [ -z ${NODE_NAME+x} ]; then echo "NODE_NAME is unset"; else echo "node name is set to '$NODE_NAME'"; fi
if [ -z ${SAMPLE_RATE+x} ]; then echo "SAMPLE_RATE is unset"; else echo "sample rate is set to '$SAMPLE_RATE'"; fi
if [ -z ${AUDIO_HW_ID+x} ]; then echo "AUDIO_HW_ID is unset"; else echo "sound card is set to '$AUDIO_HW_ID'"; fi
if [ -z ${CHANNELS+x} ]; then echo "CHANNELS is unset"; else echo "Number of audio channels is set to '$CHANNELS'"; fi
if [ -z ${NODE_TYPE+x} ]; then echo "NODE_TYPE is unset"; else echo "node type is set to '$NODE_TYPE'"; fi
if [ -z ${STREAM_RATE+x} ]; then echo "STREAM_RATE is unset"; else echo "stream rate is set to '$STREAM_RATE'"; fi
if [ -z ${SEGMENT_DURATION+x} ]; then echo "SEGMENT_DURATION is unset"; else echo "segment duration is set to '$SEGMENT_DURATION'"; fi
if [ -z ${NODE_LOOPBACK+x} ]; then echo "NODE_LOOPBACK is unset"; else echo "node loopback is set to '$NODE_LOOPBACK'"; fi

#### Set up local output directories
mkdir -p /tmp/$NODE_NAME/flac
mkdir -p /tmp/$NODE_NAME/hls/$timestamp

# Output timestamp for this (latest) stream
echo $timestamp > /tmp/$NODE_NAME/latest.txt

# --- DISK MANAGEMENT ---
# Maximum number of HLS session directories to keep in /tmp at once.
# Each 10-second segment is ~200 KB; a 1-hour outage accumulates ~72 MB per session.
# 8 sessions caps storage at roughly 600 MB worst-case.
MAX_HLS_DIRS=8

prune_old_hls_dirs() {
    local current_ts="$1"
    local hls_base="/tmp/$NODE_NAME/hls"

    # List all numeric timestamp dirs except the current session, newest-first
    mapfile -t old_dirs < <(ls -dt "$hls_base"/[0-9]* 2>/dev/null | grep -v "/$current_ts$")

    local max_old=$(( MAX_HLS_DIRS - 1 ))
    if (( ${#old_dirs[@]} > max_old )); then
        local to_delete=$(( ${#old_dirs[@]} - max_old ))
        # Oldest dirs are at the end of a newest-first list; delete them first
        for dir in "${old_dirs[@]: -$to_delete}"; do
            echo "Pruning oldest HLS dir (MAX_HLS_DIRS=$MAX_HLS_DIRS exceeded): $dir"
            rm -rf "$dir"
        done
    fi
    echo "HLS dirs: ${#old_dirs[@]} old session(s) + 1 current (limit: $MAX_HLS_DIRS)"
}

prune_old_hls_dirs "$timestamp"

STREAM_RATE=48000

if [ -z ${SAMPLE_RATE+48000} ]; then
    echo "setting sampling rate to 48000"
else
    echo "sample rate is set to $SAMPLE_RATE"
fi

# --- 4. SETUP JACK ---
# NOTE: limits.conf must be configured once manually as root (see setup.sh):
#   echo '@audio - memlock 256000' | sudo tee -a /etc/security/limits.conf
#   echo '@audio - rtprio 75' | sudo tee -a /etc/security/limits.conf

# Wait for pisound ALSA device to be ready (important at boot)
echo "Waiting for ALSA device hw:$AUDIO_HW_ID..."
for i in $(seq 1 30); do
    aplay -l 2>/dev/null | grep -qi "$AUDIO_HW_ID" && break
    echo "Audio device not ready yet, attempt $i..."
    sleep 1
done
if ! aplay -l 2>/dev/null | grep -qi "$AUDIO_HW_ID"; then
    echo "ERROR: ALSA device hw:$AUDIO_HW_ID not found after 30s, aborting."
    exit 1
fi
echo "Audio device ready."

# Start jackd in background
JACK_NO_AUDIO_RESERVATION=1 jackd -t 2000 -P 75 -d alsa -d hw:$AUDIO_HW_ID -r $SAMPLE_RATE -p 1024 -n 10 -s &

# Wait until JACK server is ready before proceeding
echo "Waiting for JACK server to be ready..."
for i in $(seq 1 15); do
    jack_wait -w -t 1 && break
    echo "JACK not ready yet, attempt $i..."
    if [ $i -eq 15 ]; then
        echo "ERROR: JACK failed to start after 15s, aborting."
        exit 1
    fi
    sleep 1
done
echo "JACK is ready."

#### Generate stream segments and manifests, and/or lossless archive

echo "Node started at $timestamp"
echo "Node is named $NODE_NAME and is of type $NODE_TYPE"
## NODE_TYPE set in .env file to one of: "research"; "debug" (DASH-only); "hls-only"; "dev-virt-s3"

FFMPEG_PID=""

if [ $NODE_TYPE = "research" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write $FLAC_DURATION second $SAMPLE_RATE Hz FLAC files..."
	## Streaming HLS with FLAC archive
	nice -n -10 ffmpeg -f jack -i ffjack \
       -f segment -segment_time "00:00:$FLAC_DURATION.00" -strftime 1 "/tmp/$NODE_NAME/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_list_size 5 -segment_time $SEGMENT_DURATION -segment_format \
       mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
       >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
	FFMPEG_PID=$!
elif [ $NODE_TYPE = "debug" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
        echo "Asking ffmpeg to stream DASH via mpegts at $STREAM_RATE Hz..."
  	nice -n -10 ffmpeg -t 0 -f jack -i ffjack -f mpegts udp://127.0.0.1:1234 \
       >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
	FFMPEG_PID=$!
  	nice -n -7 ./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234 &
elif [ $NODE_TYPE = "hls-only" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
  	echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......"
	nice -n -10 ffmpeg -f jack -i ffjack -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_list_size 5 -segment_time $SEGMENT_DURATION -segment_format mpegts -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
       >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
	FFMPEG_PID=$!
elif [ $NODE_TYPE = "dev-virt-s3" ]; then
    SAMPLE_RATE=48000
    STREAM_RATE=48000
    echo "Sampling from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
    echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......"
    nice -n -10 ffmpeg -re -fflags +genpts -stream_loop -1 -i "samples/haro-strait_2005.wav" \
      -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts \
      -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
      >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
    FFMPEG_PID=$!
else
        echo "unsupported please pick hls-only, research, or dev-virt-s3"
fi

# --- 5. CONNECT JACK PORTS ---
# Wait for ffmpeg to register ffjack ports with JACK before connecting
echo "Waiting for ffjack ports to be available..."
for i in $(seq 1 15); do
    if ! kill -0 $FFMPEG_PID 2>/dev/null; then
        echo "ERROR: ffmpeg died before registering JACK ports. Check /tmp/$NODE_NAME/ffmpeg.log"
        cat /tmp/$NODE_NAME/ffmpeg.log
        exit 1
    fi
    jack_lsp | grep -q "ffjack:input_1" && break
    echo "ffjack ports not ready yet, attempt $i..."
    sleep 1
done

if ! jack_lsp | grep -q "ffjack:input_1"; then
    echo "ERROR: ffjack ports never appeared. Available JACK ports:"
    jack_lsp
    echo "--- ffmpeg log ---"
    cat /tmp/$NODE_NAME/ffmpeg.log
    exit 1
fi
echo "ffjack ports are ready, connecting..."

jack_connect -s default system:capture_1 ffjack:input_1
jack_connect -s default system:capture_2 ffjack:input_2

if [ $NODE_LOOPBACK = "true" ]; then
    jack_connect system:capture_1 system:playback_1
    jack_connect system:capture_2 system:playback_2
fi

if [ $NODE_LOOPBACK = "hls" ]; then
    sleep 20
    ffplay -nodisp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8
fi

# Background: upload any HLS directories left from previous sessions, then clean them up.
# Runs at lower CPU priority (nice +10) so it never competes with the real-time uploader.
nice -n 10 python3 "$SCRIPT_DIR/upload_old_hls.py" &

if [ $NODE_TYPE = "research" ]; then
    python3 "$SCRIPT_DIR/upload_s3.py" &
    python3 "$SCRIPT_DIR/upload_flac_s3.py"
else
    python3 "$SCRIPT_DIR/upload_s3.py"
fi

echo "all done"
