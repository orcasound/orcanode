#/bin/bash

function fail {
    printf '%s\n' "$1" >&2  ## Send message to stderr. Exclude >&2 if you don't want it that way.
    printf "mandatory env variable not set, exiting now"  >&2 
    exit "${2-1}"  ## Return a code specified by $2 or 1 by default.
    }

#
# Check for all enviorment variables and fail if mandatory ones are not set
#
if [ -z ${NODE_NAME+x} ]; then fail "NODE_NAME is unset"; else echo "node name is set to '$NODE_NAME'"; fi
if [ -z ${SAMPLE_RATE+x} ]; then fail "SAMPLE_RATE is unset"; else echo "sample rate is set to '$SAMPLE_RATE'"; fi
if [ -z ${AUDIO_HW_ID+x} ]; then fail "AUDIO_HW_ID is unset"; else echo "sound card is set to '$AUDIO_HW_ID'"; fi
if [ -z ${CHANNELS+x} ]; then fail "CHANNELS is unset"; else echo "Number of audio channels is set to '$CHANNELS'"; fi
if [ -z ${NODE_TYPE+x} ]; then fail "NODE_TYPE is unset"; else echo "node type is set to '$NODE_TYPE'"; fi
if [ -z ${STREAM_RATE+x} ]; then fail "STREAM_RATE is unset"; else echo "stream rate is set to '$STREAM_RATE'"; fi
if [ -z ${SEGMENT_DURATION+x} ]; then fail "SEGMENT_DURATION is unset"; else echo "segment duration is set to '$SEGMENT_DURATION'"; fi 
if [ -z ${NODE_ARCH+x} ]; then fail "NODE_ARCH is unset"; else echo "node architecture is set to '$NODE_ARCH'"; fi
if [ -z ${NODE_LOOPBACK+x} ]; then echo "NODE_LOOPBACK is unset"; else echo "node loopback is set to '$NODE_LOOPBACK'"; fi

# Get current timestamp
timestamp=$(date +%s)


#### Set up local output directories
mkdir -p /tmp/$NODE_NAME
mkdir -p /tmp/$NODE_NAME/flac
mkdir -p /tmp/$NODE_NAME/hls
mkdir -p /tmp/$NODE_NAME/hls/$timestamp
#mkdir -p /tmp/$NODE_NAME/dash
#mkdir -p /tmp/$NODE_NAME/dash/$timestamp
#ln /tmp/$NODE_NAME/dash/$timestamp /tmp/dash_output_dir

# Output timestamp for this (latest) stream
echo $timestamp > /tmp/$NODE_NAME/latest.txt
