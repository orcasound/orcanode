# Node Dockerfile for hydrophone streaming

# Use official debian image, but pull the armhf (v7+) image explicitly because
# Docker currently has a bug where armel is used instead when relying on
# multiarch manifest: https://github.com/moby/moby/issues/34875
# When this is fixed, this can be changed to just `FROM debian:stretch-slim`
FROM orcastream/orcabase:latest
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

RUN pip3 install numpy
RUN pip3 install obspy

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
