#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC

# Ensure system binaries are in PATH
export PATH=/usr/bin:/usr/local/bin:/usr/sbin:/bin:$PATH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 0. PREFLIGHT CHECKS ---
# The .env sourcing is commented out because Docker Compose handles variable injection.
# if [ -f "$SCRIPT_DIR/.env" ]; then
#     set -a
#     source "$SCRIPT_DIR/.env"
#     set +a
#     echo "Loaded .env from $SCRIPT_DIR"
# fi

if ! command -v jackd &> /dev/null; then
    echo "ERROR: jackd is not installed."
    exit 1
fi
if ! command -v jack_wait &> /dev/null; then
    echo "ERROR: jack_wait is not installed."
    exit 1
fi
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg is not installed."
    exit 1
fi

# --- 1. TIME SYNCHRONIZATION ---
# timedatectl can't be used here: the container has no systemd. Instead ask
# the kernel directly via adjtimex() -- the container shares the host's
# kernel, and chrony/systemd-timesyncd on the host clear its STA_UNSYNC flag
# once the clock is really synchronized (the same flag timedatectl reports).
# adjtimex returns 5 (TIME_ERROR) while the clock is unsynchronized.
# REQUIRE_TIME_SYNC=false skips the wait, for hosts with no NTP daemon
# (e.g. a test machine).
clock_synced() {
    python3 -c '
import ctypes, sys
buf = ctypes.create_string_buffer(512)  # zeroed struct timex: modes=0, read-only
state = ctypes.CDLL(None, use_errno=True).adjtimex(buf)
sys.exit(0 if state not in (-1, 5) else 1)
'
}

wait_for_sync() {
    if [ "$(echo "${REQUIRE_TIME_SYNC:-true}" | tr '[:upper:]' '[:lower:]')" = "false" ]; then
        echo "REQUIRE_TIME_SYNC=false: not waiting for time sync. Clock: $(date)"
        return 0
    fi
    echo "Checking time synchronization..."
    local max_wait=60
    local elapsed=0

    while [ $elapsed -lt $max_wait ]; do
        if clock_synced; then
            echo "Time synchronized: $(date)"
            return 0
        fi
        echo "Waiting for time sync... (${elapsed}s)"
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "ERROR: Time sync timed out after ${max_wait}s, aborting."
    exit 1
}

wait_for_sync

# --- 2. ACTIVATE VIRTUAL ENVIRONMENT ---
# Updated to use the absolute path within the container.
source /venv/bin/activate

# --- 3. DYNAMIC AUDIO DEVICE DISCOVERY ---
echo "Searching for ALSA device: $AUDIO_HW_ID..."

# Loop to find the hardware index (e.g., card 3) and set the correct hw address.
for i in $(seq 1 30); do
    if aplay -l 2>/dev/null | grep -qi "$AUDIO_HW_ID"; then
        # Extracts the number from a line like "card 3: pisound [pisound]".
        CARD_NUM=$(aplay -l | grep -i "$AUDIO_HW_ID" | head -n 1 | awk -F'[: ]+' '{print $2}')
        
        if [ -n "$CARD_NUM" ]; then
            SOUND_CARD="hw:$CARD_NUM,0"
            echo "Success! $AUDIO_HW_ID found at index $CARD_NUM. Using address: $SOUND_CARD"
            break
        fi
    fi
    echo "Audio device $AUDIO_HW_ID not ready yet, attempt $i..."
    sleep 1
done

if [ -z "$SOUND_CARD" ]; then
    echo "ERROR: ALSA device $AUDIO_HW_ID not found after 30s, aborting."
    exit 1
fi

# --- 4. VARIABLES & DIRECTORIES ---
timestamp=$(date +%s)
echo "Node started at $timestamp. Node name: $NODE_NAME. Sound card address: $SOUND_CARD"

mkdir -p /tmp/$NODE_NAME/flac
mkdir -p /tmp/$NODE_NAME/hls/$timestamp
echo $timestamp > /tmp/$NODE_NAME/latest.txt

STREAM_RATE=48000
SAMPLE_RATE=${SAMPLE_RATE:-48000}

# --- 5. SETUP JACK ---
# Start jackd using the discovered $SOUND_CARD index.
JACK_NO_AUDIO_RESERVATION=1 jackd -t 2000 -P 75 -m -s -d alsa -d $SOUND_CARD -r $SAMPLE_RATE -p 1024 -n 10 &

echo "Waiting for JACK server to be ready..."
for i in $(seq 1 15); do
    jack_wait -w -t 1 && break
    if [ $i -eq 15 ]; then
        echo "ERROR: JACK failed to start after 15s."
        exit 1
    fi
    sleep 1
done
echo "JACK is ready."

# --- 6. FFMPEG STREAMING ---
FFMPEG_PID=""

# UTC_TIME=true runs ffmpeg with TZ=UTC so FLAC filenames (and HLS
# EXT-X-PROGRAM-DATE-TIME offsets) use UTC; otherwise the Pi's local time.
FFMPEG_TZ=()
if [ "$(echo "${UTC_TIME:-false}" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
    FFMPEG_TZ=(env TZ=UTC)
    echo "UTC_TIME=true: ffmpeg timestamps and FLAC filenames use UTC."
else
    echo "UTC_TIME=false: ffmpeg timestamps and FLAC filenames use local time ($(date +%Z))."
fi

if [ "$NODE_TYPE" = "research" ]; then
	"${FFMPEG_TZ[@]}" nice -n -10 ffmpeg -f jack -i ffjack \
	  -f segment \
	  -segment_time "00:00:$FLAC_DURATION.00" \
	  -strftime 1 "/tmp/$NODE_NAME/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
	  -ar $STREAM_RATE -ac $CHANNELS -acodec aac \
	  -f hls \
	  -hls_time $SEGMENT_DURATION \
	  -hls_list_size 0 \
	  -hls_flags program_date_time \
	  -hls_segment_filename "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
	  "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" \
	  >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
	FFMPEG_PID=$!
elif [ "$NODE_TYPE" = "hls-only" ]; then
	"${FFMPEG_TZ[@]}" nice -n -10 ffmpeg -f jack -i ffjack \
	  -ar $STREAM_RATE \
	  -ac $CHANNELS \
	  -acodec aac \
	  -f hls \
	  -hls_time $SEGMENT_DURATION \
	  -hls_list_size 0 \
	  -hls_flags program_date_time \
	  -hls_segment_filename "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
	  "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" \
	  >/tmp/$NODE_NAME/ffmpeg.log 2>&1 &
	FFMPEG_PID=$!
else
    echo "Unsupported NODE_TYPE. Please use research or hls-only."
    exit 1
fi

# --- 7. CONNECT JACK PORTS ---
echo "Waiting for ffjack ports..."
for i in $(seq 1 15); do
    jack_lsp | grep -q "ffjack:input_1" && break
    sleep 1
done

if ! jack_lsp | grep -q "ffjack:input_1"; then
    echo "ERROR: ffjack ports never appeared."
    cat /tmp/$NODE_NAME/ffmpeg.log
    exit 1
fi

jack_connect -s default system:capture_1 ffjack:input_1
jack_connect -s default system:capture_2 ffjack:input_2

if [ "$NODE_LOOPBACK" = "true" ]; then
    jack_connect system:capture_1 system:playback_1
    jack_connect system:capture_2 system:playback_2
fi

echo "JACK, ffmpeg and port connections are up."

# Launch Python uploaders
if [ "${NO_UPLOAD:-false}" = "true" ]; then
    echo "NO_UPLOAD=true, skipping S3 upload. Segments will accumulate in /tmp/$NODE_NAME/hls/"
    wait $FFMPEG_PID
elif [ "$NODE_TYPE" = "research" ]; then
    nice -n 10 python3 catchup_s3.py &
    python3 upload_s3.py &
    python3 upload_flac_s3.py
else
    nice -n 10 python3 catchup_s3.py &
    python3 upload_s3.py
fi