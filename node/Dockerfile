# Node Dockerfile for hydrophone streaming
# Multi-arch self-contained build for CI/CD deployment

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/orcasound/orcanode"
LABEL org.opencontainers.image.description="Orcasound hydrophone streaming node"
LABEL org.opencontainers.image.authors="Orcasound <orcanode-devs@orcasound.net>"

# Install system dependencies
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    jack-capture \
    jackd2 \
    alsa-utils \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    boto3 \
    inotify

# Set working directory
WORKDIR /app

# Copy node application files first
COPY node/ ./

# Copy Python upload scripts from base directory (overwrites if they exist in node/)
COPY base/upload_s3.py ./
COPY base/upload_flac_s3.py ./

# Set environment defaults
ENV SAMPLE_RATE=48000 \
    STREAM_RATE=48000 \
    CHANNELS=1 \
    NODE_TYPE=hls-only

# Make scripts executable
RUN chmod +x *.sh

# Ensure .env.example is available for reference
RUN if [ -f .env.example ]; then \
        echo ".env.example is available at /app/.env.example"; \
    else \
        echo "Warning: .env.example not found"; \
    fi

# Run the streaming script
CMD ["./stream.sh"]
