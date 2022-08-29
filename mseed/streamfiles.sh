#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC  
if [ -z ${NODE_NAME+x} ]; then echo "NODE_NAME is unset"; else echo "node name is set to '$NODE_NAME'"; fi
if [ -z ${NODE_LOOPBACK+x} ]; then echo "NODE_LOOPBACK is unset"; else echo "node loopback is set to '$NODE_LOOPBACK'"; fi


# Get current timestamp
if [ -z ${TEST_DATETIME_START+x} ];
then echo "TEST_DATETIME_START is unset, using local time";
timestamp=$(date '+%Y-%m-%d')
else echo "TEST_DATETIME_START is set, using set time";
IFS='T'
read -a datetime <<< $TEST_DATETIME_START
timestamp=${datetime[0]}
echo "Using timestamp '$timestamp'"
fi


#### Set up local output directories
mkdir -p /tmp/$NODE_NAME
mkdir -p /tmp/$NODE_NAME/hls
mkdir -p /tmp/$NODE_NAME/hls/$timestamp
# Output timestamp for this (latest) stream
echo $timestamp > /tmp/$NODE_NAME/latest.txt
#mkdir -p /root/data
# Create a starting dummy file so you will always at least get a tone
# sox -n -r 64000 /root/data/dummy.wav synth 60 sine 500
# rm dummy.ts
# ffmpeg -i dummy.wav -f mpegts -ar 64000 -acodec aac dummy.ts
# force new file 
# rm ./data/dummy.ts

# while [ ! -f ./data/dummy.ts ]
# do
#     echo "waiting for dummy.ts"
#     sleep 30
# done

# if [ $NODE_LOOPBACK = "hls" ]; then
#     sleep 20
#     ffplay -nodisp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8    
# fi

# echo "starting ffmpeg"

# ffmpeg -re -stream_loop -1 -i files.txt -flush_packets 0 -f segment -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time 10 -segment_format mpegts -ar 64000 -ac 1 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

python3 upload_s3.py

echo "all done"
