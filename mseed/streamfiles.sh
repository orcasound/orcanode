#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC  

# Get current timestamp
timestamp=$(date +%s)

#### Set up local output directories
mkdir -p /tmp/$NODE_NAME
mkdir -p /tmp/$NODE_NAME/hls
mkdir -p /tmp/$NODE_NAME/hls/$timestamp
# Output timestamp for this (latest) stream
echo $timestamp > /tmp/$NODE_NAME/latest.txt
mkdir -p /root/data
# Create a starting dummy file so you will always at least get a tone
sox -n -r 64000 /root/data/dummy.wav synth 60 sine 500

ffmpeg -re -stream_loop -1 -safe 0 -i files.txt -f segment -segment_list "/tmp/live.m3u8" -segment_list_flags +live -segment_time 10 -segment_format mpegts -ar 64000 -ac 2 -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

python3 upload_s3.py

echo "all done"
