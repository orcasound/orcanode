# Node Dockerfile for hydrophone streaming
# use base image for project

FROM orcastream/orcabase:latest
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

###### hack to get ffmpeg to build
# RUN apt-get update && apt-get install -y --no-install-recommends libraspberrypi-dev raspberrypi-kernel-headers
# RUN git clone https://github.com/raspberrypi/userland.git
# RUN cd userland/host_applications/linux/apps/hello_pi && ./rebuild.sh


###### Install Jack  #################################

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends jack-capture
RUN apt-get update && apt-get install -y --no-install-recommends jackd1

# Install ALSA and GPAC
#RUN apt-get update && apt-get install -y --no-install-recommends \
#  alsa-utils \
#  gpac

############################### Copy files #####################################

COPY . .

################################## TODO ########################################
# Do the following:
#   - Add pisound driver curl command  
#   - Add other audio drivers and configure via CLI if possible?
#   - Remove "misc tools" and other installs no longer needed (upon Resin.io deployment)?

################################# Miscellaneous ################################

# Clean up APT when done.
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
