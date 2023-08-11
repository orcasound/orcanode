# Node Dockerfile for hydrophone streaming

# Use official debian image, but pull the armhf (v7+) image explicitly because
# Docker currently has a bug where armel is used instead when relying on
# multiarch manifest: https://github.com/moby/moby/issues/34875
# When this is fixed, this can be changed to just `FROM debian:stretch-slim`
FROM arm32v7/debian:buster-slim
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

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
    gnupg \
    wget \
    git \
    htop \
    tmux \
    nano \
    sox

# Install inotify-tools and rsync
RUN apt-get update && apt-get install -y --no-install-recommends inotify-tools rsync


###### hack to get ffmpeg to build
# RUN apt-get update && apt-get install -y --no-install-recommends libraspberrypi-dev raspberrypi-kernel-headers
# RUN git clone https://github.com/raspberrypi/userland.git
# RUN cd userland/host_applications/linux/apps/hello_pi && ./rebuild.sh


####################### Build ffmpeg with Jack #####################################################


RUN git clone git://source.ffmpeg.org/ffmpeg.git 
RUN apt-get update && apt-get install -y --no-install-recommends libomxil-bellagio-dev libjack-dev 
RUN cd ffmpeg && ./configure --arch=armel --target-os=linux --enable-gpl --enable-nonfree --enable-libjack 
RUN cd ffmpeg && make -j4
# Hack to patch jack.c with slightly longer timeout
COPY ./jack.c ./ffmpeg/libavdevice/jack.c 
RUN cd ffmpeg && make
RUN cd ffmpeg && make install 

###### Install Jack  #################################

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends jack-capture
RUN apt-get update && apt-get install -y --no-install-recommends jackd1

# Install ALSA and GPAC
RUN apt-get update && apt-get install -y --no-install-recommends \
  alsa-utils \
  gpac

# Install npm and http-server for testing
# Based on https://nodesource.com/blog/installing-node-js-tutorial-debian-linux/
RUN curl -sL https://deb.nodesource.com/setup_6.x | bash - && \
  apt-get update && apt-get install -y --no-install-recommends nodejs

RUN apt-get update && apt-get install -y --no-install-recommends  npm

RUN npm install -g \
  http-server \
  jsonlint

# Not needed for flac
# Install test-engine-live-tools
# RUN git clone https://github.com/ebu/test-engine-live-tools.git && \
#  cd test-engine-live-tools && \
#   npm install


############################### Install boto and inotify libraies  ###################################

RUN apt-get update && apt-get install -y python3-pip
RUN pip3 install -U boto3
RUN pip3 install inotify

############################### Copy files #####################################

COPY . .

RUN /bin/bash -c "source setenv.sh"      # read in the environment varibles
################################## TODO ########################################
# Do the following:
#   - Add pisound driver curl command  
#   - Add other audio drivers and configure via CLI if possible?
#   - Remove "misc tools" and other installs no longer needed (upon Resin.io deployment)?

################################# Miscellaneous ################################

# Clean up APT when done.
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

