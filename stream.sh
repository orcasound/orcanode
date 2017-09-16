#!/bin/bash
# Make sure s3fs is mounted and start streaming

mkdir -p /mnt/dev-streaming-orcasound-net
s3fs dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/ && \
  mkdir -p /mnt/dev-streaming-orcasound-net/$NODE_NAME && \
  DashCast -af alsa -a plughw:$AUDIO_HW_ID -conf dashcast.conf -time-shift -1 -out /mnt/dev-streaming-orcasound-net/$NODE_NAME -live