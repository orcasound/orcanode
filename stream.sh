#/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC  
# Some environmental variables set by local .env file; others here:

FLAC_DURATION=10
SEGMENT_DURATION=10
LAG_SEGMENTS=6
LAG=$(( LAG_SEGMENTS*SEGMENT_DURATION ))
CHOP_M3U8_LINES=$(( LAG_SEGMENTS*(-2) ))

#### Set up and mount s3fs bucket

# Get current timestamp
timestamp=$(date +%s)

# Set up general output s3fs dirs locally
mkdir -p /mnt/archive-orcasound-net
mkdir -p /mnt/streaming-orcasound-net
mkdir -p /mnt/streaming-orcasound-net/$NODE_NAME
mkdir -p /mnt/streaming-orcasound-net/$NODE_NAME/hls
mkdir -p /mnt/streaming-orcasound-net/$NODE_NAME/hls/$timestamp

mkdir -p /mnt/dev-archive-orcasound-net
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME
mkdir -p /mnt/dev-streaming-orcasound-net
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls
mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp

# Start s3fs (with debug flags)
s3fs -o default_acl=public-read --debug -o dbglevel=info archive-orcasound-net /mnt/archive-orcasound-net/
s3fs -o default_acl=public-read --debug -o dbglevel=info streaming-orcasound-net /mnt/streaming-orcasound-net/
s3fs -o default_acl=public-read --debug -o dbglevel=info dev-archive-orcasound-net /mnt/dev-archive-orcasound-net/
s3fs -o default_acl=public-read --debug -o dbglevel=info dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/

#### Set up local output directories
mkdir -p /tmp/flac/
mkdir -p /tmp/flac/$NODE_NAME
mkdir -p /tmp/m3u8tmp
mkdir -p /tmp/m3u8tmp/$timestamp
mkdir -p /tmp/$NODE_NAME/hls
mkdir -p /tmp/$NODE_NAME/hls/$timestamp
#mkdir -p /tmp/$NODE_NAME/dash
#mkdir -p /tmp/$NODE_NAME/dash/$timestamp
#ln /tmp/$NODE_NAME/dash/$timestamp /tmp/dash_output_dir

# Output timestamp for this (latest) stream
echo $timestamp > /tmp/$NODE_NAME/latest.txt


#### Generate stream segments and manifests, and/or lossless archive

echo "Node started at $timestamp"
echo "Node is named $NODE_NAME and is of type $NODE_TYPE"
## NODE_TYPE set in .env filt to one of: 
## "research" -- writes FLAC files to archive bucket; 
## "dash-only" -- streams MPEG-DASH segments to streaming bucket;
## "hls-only" -- streams HLS segments to streaming bucket;
## "dev-virt-s3" -- loops local .wav file to virtual S3 bucket; 
## "dev-stable" -- streams FLAC and HLS to dev S3 buckets;  
## or default (FLAC+HLS+DASH), e.g. for improving Orcasite app/player features/encoding/browser-compatibilty etc...

if [ $NODE_TYPE = "research" ]; then
	SAMPLE_RATE=48000
	STREAM_RATE=48000 ## Is it efficient to specify this so mpegts isn't hit by 4x the uncompressed data?
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write $FLAC_DURATION second $SAMPLE_RATE Hz FLAC files..." 
	## Streaming HLS with FLAC archive 
	nice -n -10 ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time "00:00:$FLAC_DURATION.00" -strftime 1 "/tmp/flac/$NODE_NAME/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/m3u8tmp/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format \
       mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

elif [ $NODE_TYPE = "dash-only" ]; then
        SAMPLE_RATE=48000
        STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
        echo "Asking ffmpeg to stream DASH via mpegts at $STREAM_RATE Hz..." 
  	## Streaming DASH only via mpegts
  	nice -n -10 ffmpeg -t 0 -f alsa -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -ac $CHANNELS -f mpegts udp://127.0.0.1:1234 &
  	#### Stream with test engine live tools
	## May need to adjust segment length in config_audio.json to match $SEGMENT_DURATION...
  	nice -n -7 ./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234 &

elif [ $NODE_TYPE = "hls-only" ]; then
  	SAMPLE_RATE=48000
  	STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
  	echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
  	## Streaming HLS only via mpegts
	nice -n -10 ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -ac $CHANNELS -f segment -segment_list "/tmp/m3u8tmp/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts -ar $STREAM_RATE -ac 2 -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

elif [ $NODE_TYPE = "dev-virt-s3" ]; then
    SAMPLE_RATE=48000
    STREAM_RATE=48000
  echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
    echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
    ## Streaming HLS only via mpegts
  nice -n -10 ffmpeg -re -fflags +genpts -stream_loop -1 -i "samples/haro-strait_2005.wav" \
    -f segment -segment_list "/tmp/m3u8tmp/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts \
    -ar $STREAM_RATE -ac 2 -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

elif [ $NODE_TYPE = "dev-stable" ]; then
	SAMPLE_RATE=48000
	STREAM_RATE=48000 
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
	echo "Asking ffmpeg to write $FLAC_DURATION second $SAMPLE_RATE Hz FLAC files..." 
	## Streaming HLS with FLAC archive 
	nice -n -10 ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac -f segment -segment_time "00:00:$FLAC_DURATION.00" -strftime 1 "/tmp/flac/$NODE_NAME/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" -f segment -segment_list "/tmp/m3u8tmp/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" &

## Default NODE_TYPE settings
else
	SAMPLE_RATE=48000
	STREAM_RATE=48000
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write $FLAC_DURATION second $SAMPLE_RATE Hz lo-res flac files while streaming in both DASH and HLS..." 
	## Streaming DASH/HLS with low-res flac archive 
	nice -n -10 ffmpeg -f alsa -ac $CHANNELS -ar $SAMPLE_RATE -thread_queue_size 1024 -i hw:$AUDIO_HW_ID -ac $CHANNELS -ar $SAMPLE_RATE -sample_fmt s32 -acodec flac \
       -f segment -segment_time "00:00:$FLAC_DURATION.00" -strftime 1 "/tmp/flac/$NODE_NAME/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -segment_list "/tmp/m3u8tmp/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format \
       mpegts -ac 2 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts" \
       -f mpegts -ac 2 udp://127.0.0.1:1234 &
	#### Stream with test engine live tools
	## May need to adjust segment length in config_audio.json to match $SEGMENT_DURATION...
	nice -n -7 ./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234 &
fi

sleep $LAG

while true; do
  inotifywait -r -e close_write,create,moved_to /tmp/$NODE_NAME /tmp/flac/$NODE_NAME
  echo "Inotify wait triggered; copy $NODE_NAME with lag of $LAG_SEGMENTS segments, or $LAG seconds..."
  head -n $CHOP_M3U8_LINES /tmp/m3u8tmp/$timestamp/live.m3u8 > /tmp/$NODE_NAME/hls/$timestamp/live.m3u8
  if [ $NODE_TYPE = "dev-stable" ] || [ $NODE_TYPE = "dev-virt-s3" ] ; then
    cp /tmp/$NODE_NAME/latest.txt /mnt/dev-streaming-orcasound-net/$NODE_NAME/latest.txt
    cp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8 /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp/live.m3u8
    mv /tmp/$NODE_NAME/hls/$timestamp/*.ts /mnt/dev-streaming-orcasound-net/$NODE_NAME/hls/$timestamp
    ##nice -n -5 rsync -avW --progress --inplace --size-only /tmp/flac/$NODE_NAME /mnt/dev-archive-orcasound-net
    ##nice -n -5 rsync -avW --progress --inplace --size-only --exclude='*.tmp' --exclude '.live*' /tmp/$NODE_NAME /mnt/dev-streaming-orcasound-net
  else
    cp /tmp/$NODE_NAME/latest.txt /mnt/streaming-orcasound-net/$NODE_NAME/latest.txt
    cp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8 /mnt/streaming-orcasound-net/$NODE_NAME/hls/$timestamp/live.m3u8
    nice -n -5 rsync -avW --progress --inplace --size-only /tmp/flac/$NODE_NAME /mnt/archive-orcasound-net
    nice -n -5 rsync -avW --progress --inplace --size-only --exclude='*.tmp' --exclude '.live*' /tmp/$NODE_NAME /mnt/streaming-orcasound-net
fi
    
done
