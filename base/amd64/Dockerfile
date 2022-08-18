# Node Dockerfile for hydrophone streaming

# Use official debian image, but pull the armhf (v7+) image explicitly because
# Docker currently has a bug where armel is used instead when relying on
# multiarch manifest: https://github.com/moby/moby/issues/34875
# When this is fixed, this can be changed to just `FROM debian:stretch-slim`
FROM python:3.6-slim-buster
# FROM arm32v7/debian:buster-slim
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

####################### Install FFMPEG #####################################################

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg


RUN apt-get update && apt-get install -y --no-install-recommends \
    # General tools
    htop \
    nano \
    sox \
    tmux \
    wget \
    curl \
    git  

# Upgrade OS
RUN apt-get update && apt-get upgrade -y -o Dpkg::Options::="--force-confold"

# Set default command to bash as a placeholder
CMD ["/bin/bash"]

# Make sure we're the root user
USER root

WORKDIR /root


############################### Install boto and inotify libraies  ###################################

RUN apt-get update && apt-get install -y python3-pip
RUN pip3 install -U boto3 inotify

############################## Copy common scripts ##################################################

COPY . .

# Clean up APT when done.
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
