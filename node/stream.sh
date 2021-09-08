#!/bin/bash
# Script for live DASH/HLS streaming lossy audio as AAC and/or archiving lossless audio as FLAC  

# Get current timestamp
timestamp=$(date +%s)

if [ -z ${NODE_NAME+x} ]; then echo "NODE_NAME is unset"; else echo "node name is set to '$NODE_NAME'"; fi
if [ -z ${SAMPLE_RATE+x} ]; then echo "SAMPLE_RATE is unset"; else echo "sample rate is set to '$SAMPLE_RATE'"; fi
if [ -z ${AUDIO_HW_ID+x} ]; then echo "AUDIO_HW_ID is unset"; else echo "sound card is set to '$AUDIO_HW_ID'"; fi
if [ -z ${CHANNELS+x} ]; then echo "CHANNELS is unset"; else echo "Number of audio channels is set to '$CHANNELS'"; fi
if [ -z ${NODE_TYPE+x} ]; then echo "NODE_TYPE is unset"; else echo "node type is set to '$NODE_TYPE'"; fi
if [ -z ${STREAM_RATE+x} ]; then echo "STREAM_RATE is unset"; else echo "stream rate is set to '$STREAM_RATE'"; fi
if [ -z ${SEGMENT_DURATION+x} ]; then echo "SEGMENT_DURATION is unset"; else echo "segment duration is set to '$SEGMENT_DURATION'"; fi
if [ -z ${NODE_LOOPBACK+x} ]; then echo "NODE_LOOPBACK is unset"; else echo "node loopback is set to '$NODE_LOOPBACK'"; fi



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

STREAM_RATE=48000

if [ -z ${SAMPLE_RATE+48000}]; then
    echo "setting sampling rate to 48000"
else
    echo "sample rate is set to $SAMPLE_RATE";
fi

#  Setup jack 
echo @audio - memlock 256000 >> /etc/security/limits.conf
echo @audio - rtprio 75 >> /etc/security/limits.co
JACK_NO_AUDIO_RESERVATION=1 jackd -t 2000 -P 75 -d alsa -d hw:$AUDIO_HW_ID -r $SAMPLE_RATE -p 1024 -n 10 -s &

#### Generate stream segments and manifests, and/or lossless archive

echo "Node started at $timestamp"
echo "Node is named $NODE_NAME and is of type $NODE_TYPE"
## NODE_TYPE set in .env filt to one of: "research"; "debug" (DASH-only); "hls-only"; or default (FLAC+HLS+DASH) 

if [ $NODE_TYPE = "research" ]; then
        #SAMPLE_RATE=192000
	## Setup Jack Audio outside for now
	# sudo echo @audio - memlock 256000 >> /etc/security/limits.conf
        # sudo echo @audio - rtprio 75 >> /etc/security/limits.co
        # sudo JACK_NO_AUDIO_RESERVATION=1 jackd -t 2000 -P 75 -d alsa -d hw:pisound -r 192000 -p 1024 -n 10 -s
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
	echo "Asking ffmpeg to write $FLAC_DURATION second $SAMPLE_RATE Hz FLAC files..." 
	## Streaming HLS with FLAC archive 
	nice -n -10 ffmpeg -f jack -i ffjack \
       -f segment -segment_time "00:00:$FLAC_DURATION.00" -strftime 1 "/tmp/$NODE_NAME/flac/%Y-%m-%d_%H-%M-%S_$NODE_NAME-$SAMPLE_RATE-$CHANNELS.flac" \
       -f segment -strftime 1 -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format \
       mpegts -ar $STREAM_RATE -ac 2 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/%Y-%m-%d_%H-%M-%S.ts" >/dev/null 2>/dev/null &
elif [ $NODE_TYPE = "debug" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz with bitrate of 32 bits/sample..."
        echo "Asking ffmpeg to stream DASH via mpegts at $STREAM_RATE Hz..." 
  	## Streaming DASH only via mpegts
  	nice -n -10 ffmpeg -t 0 -f jack -i ffjack -f mpegts udp://127.0.0.1:1234 &
  	#### Stream with test engine live tools
	## May need to adjust segment length in config_audio.json to match $SEGMENT_DURATION...
  	nice -n -7 ./test-engine-live-tools/bin/live-stream -c ./config_audio.json udp://127.0.0.1:1234 &
elif [ $NODE_TYPE = "hls-only" ]; then
	echo "Sampling $CHANNELS channels from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
  	echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
  	## Streaming HLS only via mpegts
	nice -n -10 ffmpeg -f jack -i ffjack -f segment -strftime 1 -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/%Y-%m-%d_%H-%M-%S.ts" &
elif [ $NODE_TYPE = "dev-virt-s3" ]; then
    SAMPLE_RATE=48000
    STREAM_RATE=48000
  echo "Sampling from $AUDIO_HW_ID at $SAMPLE_RATE Hz..."
    echo "Asking ffmpeg to stream only HLS segments at $STREAM_RATE Hz......" 
    ## Streaming HLS only via mpegts
  nice -n -10 ffmpeg -re -fflags +genpts -stream_loop -1 -i "samples/haro-strait_2005.wav" \
    -f segment -strftime 1 -segment_list "/tmp/$NODE_NAME/hls/$timestamp/live.m3u8" -segment_list_flags +live -segment_time $SEGMENT_DURATION -segment_format mpegts \
    -ar $STREAM_RATE -ac $CHANNELS -threads 3 -acodec aac "/tmp/$NODE_NAME/hls/$timestamp/%Y-%m-%d_%H-%M-%S.ts" &
else
        echo "unsupported please pick hls-only, research, or dev-virt-s3"
fi

# takes a second for ffmpeg to make ffjack connection before we can connect
sleep 3
jack_connect system:capture_1 ffjack:input_1
jack_connect system:capture_2 ffjack:input_2

if [ $NODE_LOOPBACK = "true" ]; then
    jack_connect system:capture_1 system:playback_1
    jack_connect system:capture_2 system:playback_2
fi

if [ $NODE_LOOPBACK = "hls" ]; then
    sleep 20
    ffplay -nodisp /tmp/$NODE_NAME/hls/$timestamp/live.m3u8    
fi

if [ $NODE_TYPE = "research" ]; then
    python3 upload_s3.py &
    python3 upload_flac_s3.py
else
    python3 upload_s3.py
fi

echo "all done"
