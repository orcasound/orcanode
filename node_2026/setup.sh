#!/bin/bash
# One-time setup script for hydrophone streaming node (Docker version)
# Run once on a fresh Raspberry Pi OS (Bullseye, Bookworm, or Trixie)

set -e  # Exit immediately if any command fails

# Detect the actual user (works whether run as root or with sudo)
REAL_USER=${SUDO_USER:-$USER}
REAL_HOME=$(eval echo "~$REAL_USER")
PROJECT_DIR="$REAL_HOME/orcanode/node_val_docker"

echo "=== Hydrophone Node Setup (Docker) ==="
echo "Starting at $(date)"
echo "Setting up for user: $REAL_USER"

# --- 1. SYSTEM UPDATE ---
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# --- 2. DOCKER ---
echo "Installing Docker..."
curl -fsSL https://get.docker.com | sudo sh

# Add user to docker group so docker runs without sudo
sudo usermod -aG docker "$REAL_USER"

# Enable Docker to start on boot
sudo systemctl enable docker
sudo systemctl start docker

# --- 3. FIX DOCKER IPV6 ISSUE ---
# Raspberry Pi OS Trixie resolves Docker Hub to IPv6 which is unreachable.
# This forces Docker to use IPv4 addresses instead.
echo "Fixing Docker IPv4 connectivity..."

DOCKER_IP=$(curl -4 -s -v https://registry-1.docker.io/v2/ 2>&1 | grep "Connected to" | awk '{print $4}' | tr -d '()')
if [ -n "$DOCKER_IP" ]; then
    grep -qF "registry-1.docker.io" /etc/hosts || echo "$DOCKER_IP    registry-1.docker.io" | sudo tee -a /etc/hosts
    echo "Added $DOCKER_IP for registry-1.docker.io to /etc/hosts"
else
    echo "WARNING: Could not determine registry-1.docker.io IPv4 address."
fi

DOCKER_AUTH_IP=$(curl -4 -s -v https://auth.docker.io/token 2>&1 | grep "Connected to" | awk '{print $4}' | tr -d '()')
if [ -n "$DOCKER_AUTH_IP" ]; then
    grep -qF "auth.docker.io" /etc/hosts || echo "$DOCKER_AUTH_IP    auth.docker.io" | sudo tee -a /etc/hosts
    echo "Added $DOCKER_AUTH_IP for auth.docker.io to /etc/hosts"
else
    echo "WARNING: Could not determine auth.docker.io IPv4 address."
fi

sudo tee /etc/docker/daemon.json > /dev/null << 'DAEMONJSON'
{
  "ipv6": false,
  "dns": ["8.8.8.8", "8.8.4.4"]
}
DAEMONJSON
sudo systemctl restart docker

# --- 4. AUDIO GROUP PERMISSIONS ---
# Needed for /dev/snd device passthrough into the Docker container
sudo usermod -aG audio "$REAL_USER"

echo ""
echo "=== Setup Complete ==="
echo "IMPORTANT: You must reboot before starting the container."
echo "  Group membership changes (audio, docker) require a reboot to take effect."
echo ""
echo "After rebooting, build and start the container once:"
echo "  cd $PROJECT_DIR"
echo "  docker compose up -d --build"
echo ""
echo "After the first build, Docker manages the container automatically:"
echo "  restart: always  — restarts on crash"
echo "  Docker enabled at boot — starts on every reboot"
echo ""
echo "Container management:"
echo "  docker compose up -d     # start"
echo "  docker compose down      # stop"
echo "  docker compose logs -f   # logs"
echo ""
echo "Rebooting in 10 seconds... (Ctrl-C to cancel)"
sleep 10
sudo reboot
