#!/bin/bash
# Script for live DASH/HLS streaming lossy audio and/or archiving lossless audio as FLAC  


#### Set up and mount s3fs bucket

# Set up general output s3fs dirs locally
mkdir -p /mnt/dev-streaming-orcasound-net
mkdir -p /mnt/dev-archive-orcasound-net

# Start s3fs
s3fs -o default_acl=public-read dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/
s3fs -o default_acl=public-read dev-archive-orcasound-net /mnt/dev-archive-orcasound-net/

# Get current timestamp
timestamp=$(date +%s)

# Make output dirs
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME/dash/$timestamp
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp
mkdir -p /mnt/dev-archive-orcasound-net/$NODE_NAME

# Output timestamp for this (latest) stream
echo $timestamp > /mnt/dev-streaming-orcasound-net/$NODE_NAME/latest.txt


#### Set up temporary directories and symbolic links

mkdir -p /tmp/dash_segment_input_dir

# symlinks to s3 for output
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/dash/$timestamp /tmp/dash_output_dir
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp /tmp/hls
ln -s /mnt/dev-archive-orcasound-net/$NODE_NAME/ /tmp/flac


#### Generate stream segments and/or lossless archive

## Streaming DASH/HLS with flac archive 
# mono input
ffmpeg -f alsa -i hw:$AUDIO_HW_ID -ac 1 -ar 44100 -sample_fmt s32 -acodec flac \
       -f segment -segment_time 00:00:05.00 -strftime 1 "/tmp/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME_192-32.flac" \
       -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 5 -segment_format \
       mpegts -ac 1 -acodec aac "/tmp/hls/live%03d.ts" \
       -f mpegts -ac 1 udp://127.0.0.1:1234 &

#### Stream with test engine live tools
./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234
