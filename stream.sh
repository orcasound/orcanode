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

# SV added this, but then commented out for fear it was causing conflict with test-engine-live-tools...
# ...possibly during read/write/move interactions with s3fs
#mkdir -p /tmp/dash_segment_input_dir

# symlinks to s3 for output
rm /tmp/dash_output_dir
rm /tmp/hls
rm /tmp/flac
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/dash/$timestamp /tmp/dash_output_dir
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp /tmp/hls
ln -s /mnt/dev-archive-orcasound-net/$NODE_NAME/ /tmp/flac


#### Generate stream segments and/or lossless archive

echo "Node name is $NODE_NAME"
echo "Node type is $NODE_TYPE"

if [ $NODE_TYPE = "research" ]; then
	SAMPLE_RATE=192000
	STREAM_RATE=48000 ## Is it efficient to specify this so mpegts isn't hit by 4x the uncompressed data?
	echo "Asking ffmpeg to write 30-second $SAMPLE_RATE Hz hi-res flac files..." 
	## Streaming DASH/HLS with hi-res flac archive 
	ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time 00:00:30.00 -strftime 1 "/tmp/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 5 -segment_format \
       mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/hls/live%03d.ts" \
       -f mpegts -ar $STREAM_RATE -ac 2 udp://127.0.0.1:1234 &
else
	SAMPLE_RATE=48000
	STREAM_RATE=48000
	echo "Asking ffmpeg to write 30-second $SAMPLE_RATE Hz lo-res flac files..." 
	## Streaming DASH/HLS with low-res flac archive 
	ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time 00:00:30.00 -strftime 1 "/tmp/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 5 -segment_format \
       mpegts -ac 2 -acodec aac "/tmp/hls/live%03d.ts" \
       -f mpegts -ac 2 udp://127.0.0.1:1234 &
fi
echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."

#### Stream with test engine live tools
./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234
