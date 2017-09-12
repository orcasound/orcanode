# Node Dockerfile for hydrophone streaming

# Use phusion/baseimage as base image
# https://github.com/phusion/baseimage-docker
FROM phusion/baseimage:0.9.22
MAINTAINER Orcasound <contact@orcasound.net>

# Upgrade OS
RUN apt-get update && apt-get upgrade -y -o Dpkg::Options::="--force-confold"

# Use baseimage-docker's init system.
CMD ["/sbin/my_init"]

# Make sure we're the root user
USER root

# From https://github.com/phusion/baseimage-docker/issues/119:
#
#   We ignore HOME, SHELL, USER and a bunch of other environment variables on
#   purpose, because not ignoring them will break multi-user containers.
#
#   Workaround:
#
RUN echo /root > /etc/container_environment/HOME
WORKDIR /root

############################### Install GPAC ##############################

ENV GPAC_VERSION 0.7.1

# Install required libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    # GPAC official dependencies
    dvb-apps \
    firefox-dev \
    g++ \
    liba52-0.7.4-dev \
    libasound2-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavformat-dev \
    libavresample-dev \
    libavutil-dev \
    libfaad-dev \
    libfreetype6-dev \
    libgl1-mesa-dev \
    libjack-dev \
    libjpeg62-dev \
    libmad0-dev \
    libmozjs185-dev \
    libogg-dev \
    libopenjpeg-dev \
    libpng12-dev \
    libpulse-dev \
    libsdl1.2-dev \
    libssl-dev \
    libswscale-dev \
    libtheora-dev \
    libvorbis-dev \
    libxv-dev \
    libxvidcore-dev \
    linux-sound-base \
    make \
    pkg-config \
    x11proto-gl-dev \
    x11proto-video-dev \
    zlib1g-dev

# Install correct ffmpeg from Ubuntu Multimedia ppa
# https://launchpad.net/~jonathonf/+archive/ubuntu/ffmpeg-3
RUN \
  add-apt-repository -y ppa:jonathonf/ffmpeg-3 && \
  apt-get update && \
  apt-get install -y --no-install-recommends libx264-dev ffmpeg

RUN \
  git clone --branch v$GPAC_VERSION https://github.com/gpac/gpac.git && \
  cd gpac && \
  ./configure && \
  make && \
  make install && \
  make install-lib && \
  # Install dashcast manually, for some reason the make script fails to install it
  install  -m 755 bin/gcc/DashCast "/usr/local/bin"

# Install ALSA
RUN apt-get update && apt-get install -y --no-install-recommends \
  alsa-utils

# Install misc tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # General tools
    htop \
    nano \
    sox \
    wget

############################### Install s3fs ##############################

RUN apt-get update && apt-get install -y --no-install-recommends s3fs

################################# Miscellaneous ################################

# Clean up APT when done.
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

#
#  Add dashcast configuration file 
#
ADD . dashcast.conf
