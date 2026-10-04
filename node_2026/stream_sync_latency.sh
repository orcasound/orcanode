#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC
#
# This is a copy of stream_sync.sh with an added CHECK_LATENCY test marker
# (see section 8) for measuring end-to-end latency from capture to S3/player.

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
wait_for_sync() {
    echo "Checking time synchronization..."
    local max_wait=60
    local elapsed=0

    while [ $elapsed -lt $max_wait ]; do
        # Compatible with older Pi OS versions
        if timedatectl status 2>/dev/null | grep -q "System clock synchronized: yes"; then
            echo "Time synchronized: $(date)"
            return 0
        fi
        # Also try the newer 'show' syntax as fallback
        if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q "yes"; then
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

if [ "$NODE_TYPE" = "research" ]; then
	nice -n -10 ffmpeg -f jack -i ffjack \
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
	nice -n -10 ffmpeg -f jack -i ffjack \
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

# --- 8. LATENCY TEST MARKER INJECTION (optional) ---
# When CHECK_LATENCY=true, mixes a short full-scale tone burst into the live
# feed at the top of every minute (wall-clock :00), on top of the real
# capture signal, via JACK's normal additive port mixing (ffjack:input_1/2
# already receive system:capture_1/2 above; JACK sums whatever else is also
# connected there).
#
# This uses a short tone (default 50ms) rather than a literal single sample:
# an isolated one-sample impulse can be smoothed away by AAC's lossy
# psychoacoustic encoding, whereas a brief full-scale tone survives
# transcoding and is easy to pick out by ear or on a waveform/spectrogram in
# both the archived FLAC/HLS output in S3 and in live playback. Compare the
# "LATENCY MARKER injected at ..." timestamp below against the wall-clock
# time the marker is actually observed in S3 / the player to get the
# end-to-end latency.
#
# Each marker's timing is freshly computed from the system clock right
# before it fires, so there's no cumulative drift over a long-running
# session. The only timing noise is the one-off delay of spawning ffmpeg and
# wiring it into JACK (normally well under a second) — negligible next to
# the multi-second S3/player latencies this is meant to measure.
CHECK_LATENCY=${CHECK_LATENCY:-false}
LATENCY_PULSE_DURATION_MS=${LATENCY_PULSE_DURATION_MS:-50}
LATENCY_PULSE_FREQ_HZ=${LATENCY_PULSE_FREQ_HZ:-1000}

inject_latency_markers() {
    local pulse_seconds
    pulse_seconds=$(awk "BEGIN { printf \"%.3f\", $LATENCY_PULSE_DURATION_MS / 1000 }")

    while true; do
        local now next_minute sleep_time client_name ports p i
        now=$(date +%s.%N)
        next_minute=$(( ( $(date +%s) / 60 + 1 ) * 60 ))
        sleep_time=$(awk "BEGIN { printf \"%.3f\", $next_minute - $now }")
        sleep "$sleep_time"

        client_name="latency_marker_$(date +%s)"
        nice -n -10 ffmpeg -loglevel error -f lavfi \
            -i "sine=frequency=${LATENCY_PULSE_FREQ_HZ}:duration=${pulse_seconds}:sample_rate=${STREAM_RATE}:amp=1" \
            -ac "$CHANNELS" -f jack "$client_name" \
            >>/tmp/$NODE_NAME/latency_marker.log 2>&1 &

        # Wire whichever output ports this marker client registers into
        # ffjack's inputs, in order, as soon as they appear.
        ports=""
        for i in $(seq 1 100); do
            ports=$(jack_lsp 2>/dev/null | grep "^${client_name}:")
            [ -n "$ports" ] && break
            sleep 0.02
        done

        if [ -z "$ports" ]; then
            echo "WARNING: latency marker ports never appeared, skipping this marker."
            continue
        fi

        i=1
        for p in $ports; do
            jack_connect -s default "$p" "ffjack:input_$i" 2>/dev/null
            i=$((i + 1))
        done

        echo "LATENCY MARKER injected at $(date -Iseconds) (epoch $(date +%s))"
    done
}

if [ "$CHECK_LATENCY" = "true" ]; then
    echo "CHECK_LATENCY=true: injecting a full-scale ${LATENCY_PULSE_DURATION_MS}ms, ${LATENCY_PULSE_FREQ_HZ}Hz marker tone at the top of every minute."
    inject_latency_markers &
fi

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

echo "All processes started successfully."
