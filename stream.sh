#!/bin/bash
# Script for live DASH/HLS streaming lossy audio and/or archiving lossless audio as FLAC  


#### Set up and mount s3fs bucket

# Set up general output s3fs dirs locally
mkdir -p /mnt/dev-streaming-orcasound-net
mkdir -p /mnt/dev-archive-orcasound-net

# Start s3fs
s3fs -o default_acl=public-read --debug -o dbglevel=info dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/
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

# symlinks to s3 for output
rm /tmp/dash_output_dir
rm /tmp/hls
rm /tmp/flac
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/dash/$timestamp /tmp/dash_output_dir
ln -s /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp /tmp/hls
ln -s /mnt/dev-archive-orcasound-net/$NODE_NAME/ /tmp/flac


#### Generate stream segments and manifests, and/or lossless archive

echo "Node started at $timestamp"
echo "Node name is $NODE_NAME"
echo "Node type is $NODE_TYPE"

if [ $NODE_TYPE = "research" ]; then
	SAMPLE_RATE=192000
	STREAM_RATE=48000 ## Is it efficient to specify this so mpegts isn't hit by 4x the uncompressed data?
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write 30-second $SAMPLE_RATE Hz hi-res flac files..." 
	## Streaming DASH/HLS with hi-res flac archive 
	ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time 00:00:30.00 -strftime 1 "/tmp/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 5 -segment_format \
       mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/hls/live%03d.ts" \
       -f mpegts -ar $STREAM_RATE -ac 2 udp://127.0.0.1:1234 &
	#### Stream with test engine live tools
	./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234
elif [ $NODE_TYPE = "debug" ]; then
        SAMPLE_RATE=48000
        STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
        echo "Asking ffmpeg to stream via mpegts at $STREAM_RATE Hz..." 
  	## Streaming DASH only via mpegts
  	ffmpeg -t 0 -f alsa -i hw:$AUDIO_HW_ID -ac $CHANNELS -f mpegts udp://127.0.0.1:1234 &
  	#### Stream with test engine live tools
  	./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234
elif [ $NODE_TYPE = "hls-only" ]; then
  	SAMPLE_RATE=48000
  	STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
  	echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
  	## Streaming HLS only via mpegts
	ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -i hw:$AUDIO_HW_ID -ac $CHANNELS -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 10 -segment_format mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/hls/live%03d.ts"
else
	SAMPLE_RATE=48000
	STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write 30-second $SAMPLE_RATE Hz lo-res flac files while streaming in both DASH and HLS..." 
	## Streaming DASH/HLS with low-res flac archive 
	ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time 00:00:30.00 -strftime 1 "/tmp/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/hls/live.m3u8" -segment_list_flags +live -segment_time 5 -segment_format \
       mpegts -ac 2 -acodec aac "/tmp/hls/live%03d.ts" \
       -f mpegts -ac 2 udp://127.0.0.1:1234 &
	#### Stream with test engine live tools
	./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234
fi

