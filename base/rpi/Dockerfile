# Node Dockerfile for hydrophone streaming

# Use official debian image, but pull the armhf (v7+) image explicitly because
# Docker currently has a bug where armel is used instead when relying on
# multiarch manifest: https://github.com/moby/moby/issues/34875
# When this is fixed, this can be changed to just `FROM debian:stretch-slim`
# FROM python:3.6-slim-buster
FROM arm32v7/debian:buster-slim
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

RUN apt-get update && apt-get install -y --no-install-recommends \
    git\
    build-essential \
    software-properties-common \
    curl \
    gnupg \
    wget 

####################### Build ffmpeg with Jack #####################################################
# Note this doesn't work with amd64 because of the --arch-arme1 command

RUN git clone git://source.ffmpeg.org/ffmpeg.git 
RUN apt-get update && apt-get install -y --no-install-recommends libomxil-bellagio-dev libjack-dev 
RUN cd ffmpeg && ./configure --arch=armel --target-os=linux --enable-gpl --enable-nonfree --enable-libjack 
RUN cd ffmpeg && make -j4
# Hack to patch jack.c with slightly longer timeout
COPY ./jack.c ./ffmpeg/libavdevice/jack.c 
RUN cd ffmpeg && make
RUN cd ffmpeg && make install 
