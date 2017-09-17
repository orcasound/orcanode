#!/bin/bash
# Make sure s3fs is mounted and start streaming

# Increase alsa capture buffer size to 4096kb
echo 4096 | tee /proc/asound/card0/pcm0c/sub0/prealloc
# Make output s3fs dir
mkdir -p /mnt/dev-streaming-orcasound-net
s3fs -o default_acl=public-read dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/ && \
  mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME && \
  DashCast -af alsa -a plughw:$AUDIO_HW_ID -conf dashcast.conf -time-shift -1 -out /mnt/dev-streaming-orcasound-net/$NODE_NAME -live