# Node Dockerfile for hydrophone streaming

# Use raspbian image since x86 images won't work
# https://docs.resin.io/runtime/resin-base-images/
FROM resin/rpi-raspbian:stretch-20171108
MAINTAINER Orcasound <contact@orcasound.net>

# Upgrade OS
RUN apt-get update && apt-get upgrade -y -o Dpkg::Options::="--force-confold"

# Set default command to bash as a placeholder
CMD ["/bin/bash"]

# Make sure we're the root user
USER root

WORKDIR /root

############################### Install GPAC ##############################

# Install required libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    software-properties-common \
    curl \
    git

# Install ffmpeg
RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends libx264-dev ffmpeg

# Install ALSA and GPAC
RUN apt-get update && apt-get install -y --no-install-recommends \
  alsa-utils \
  gpac

# Install npm and http-server for testing
# Based on https://nodesource.com/blog/installing-node-js-tutorial-ubuntu/
RUN curl -sL https://deb.nodesource.com/setup_6.x | bash - && \
  apt-get update && apt-get install -y --no-install-recommends nodejs

RUN npm install -g \
  http-server \
  jsonlint

# install test-engine-live-tools
RUN git clone https://github.com/ebu/test-engine-live-tools.git && \
  cd test-engine-live-tools && \
  npm install


# Install misc tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # General tools
    htop \
    nano \
    sox \
    wget

############################### Install s3fs ###################################

RUN apt-get update && apt-get install -y --no-install-recommends s3fs

############################### Copy files #####################################

COPY . .

################################## TODO ########################################
# Add the following commands:
#   - http-server -p 8080 --cors -c-1
#   - DashCast -af alsa -a plughw:0,0 -seg-dur 5000 -conf dashcast.conf -live
#   - s3fs dev-streaming-orcasound-net /mnt/dev-streaming-orcasound-net/

################################# Miscellaneous ################################

# Clean up APT when done.
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
