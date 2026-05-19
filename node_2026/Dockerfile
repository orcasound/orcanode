# Node Dockerfile for hydrophone streaming
# Builds on standard Debian Trixie slim base (replaces unavailable orcastream/orcabase)

FROM debian:trixie

LABEL maintainer="Orcasound <orcanode-devs@orcasound.net>"

ENV DEBIAN_FRONTEND=noninteractive

###### Install system dependencies #####################################

RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    jackd2 \
    jack-example-tools \
    libzita-alsa-pcmi0 \
    ffmpeg \
    python3-venv \
    python3-pip \
    python3 \
    curl \
    sudo \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

###### Set up Python virtual environment ###############################

RUN python3 -m venv /venv
RUN /venv/bin/pip install --upgrade pip
RUN /venv/bin/pip install boto3 inotify numpy

# Make venv the default Python environment
ENV PATH="/venv/bin:$PATH"

###### Audio group permissions #########################################

RUN usermod -aG audio root

###### Set working directory and copy files ############################

WORKDIR /app
COPY . .

RUN chmod +x stream_sync.sh
###### Runtime #########################################################

CMD ["./stream_sync.sh"]
