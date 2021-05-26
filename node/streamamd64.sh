#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC  

# Exit immediately if any command exits with non zero status 
set -e

source ./streamsetup.sh
#  Setup jack
   
#### Generate stream segments and manifests, and/or lossless archive

echo "Node started at $timestamp"
echo "Node is named $NODE_NAME and is of type $NODE_TYPE"
## NODE_TYPE set in .env filt to one of: "research"; "debug" (DASH-only); "hls-only"; or default (FLAC+HLS+DASH) 

if [ $NODE_TYPE = "research" ]; then
	echo "Research Node only supported on RPI 4"
        exit 1
elif [ $NODE_TYPE = "hls-only" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
  	echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
  	## Streaming HLS only via mpegts
	    ## amd64 alsa
	nice -n -10 ffmpeg -f alsa -ac 2 -ar $SAMPLE_RATE -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &
  
elif [ $NODE_TYPE = "dev-virt-s3" ]; then
    SAMPLE_RATE=48000
    STREAM_RATE=48000
    echo "Sampling from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
    echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
    ## Streaming HLS only via mpegts
    nice -n -10 ffmpeg -re -fflags +genpts -stream_loop -1 -i "samples/haro-strait_2005.wav" \
    -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts \
    -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &
else
        echo "unsupported please pick hls-only, research, or dev-virt-s3"
fi

# takes a second for ffmpeg to make ffjack connection before we can connect


if [ $NODE_LOOPBACK = "hls" ]; then
    sleep 20
    ffplay -nodisp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8    
fi

python3 upload_s3.py

echo "all done"
