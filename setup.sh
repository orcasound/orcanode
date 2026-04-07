#!/bin/bash
# One-time setup script for hydrophone streaming node (dockerless)
# Run once on a fresh Raspberry Pi OS (Bookworm or later)

set -e  # Exit immediately if any command fails

echo "=== Hydrophone Node Setup ==="
echo "Starting at $(date)"

# --- 1. SYSTEM UPDATE ---
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# --- 2. JACK AUDIO ---
# When prompted "Enable realtime process priority?", answer Yes.
echo "Installing JACK audio..."
sudo apt-get install -y jackd2

# --- 3. FFMPEG ---
echo "Installing ffmpeg..."
sudo apt-get install -y ffmpeg

# --- 4. PYTHON VIRTUAL ENVIRONMENT ---
echo "Setting up Python virtual environment..."
sudo apt-get install -y python3-venv python3-pip
python3 -m venv ~/venv
~/venv/bin/pip install --upgrade pip
~/venv/bin/pip install boto3 inotify numpy

# --- 5. AUDIO GROUP PERMISSIONS ---
# Add pi user to audio group for JACK realtime access
echo "Adding pi to audio group..."
sudo usermod -aG audio pi

# --- 6. REAL-TIME AUDIO LIMITS ---
# Allow the audio group to lock memory and use real-time scheduling.
# JACK requires both to run without xruns.
echo "Configuring real-time audio limits in /etc/security/limits.conf..."
grep -qF '* soft    memlock    unlimited' /etc/security/limits.conf || \
    echo '* soft    memlock    unlimited' | sudo tee -a /etc/security/limits.conf
grep -qF '* hard    memlock    unlimited' /etc/security/limits.conf || \
    echo '* hard    memlock    unlimited' | sudo tee -a /etc/security/limits.conf
grep -qF '@audio - memlock 256000' /etc/security/limits.conf || \
    echo '@audio - memlock 256000' | sudo tee -a /etc/security/limits.conf
grep -qF '@audio - rtprio 75' /etc/security/limits.conf || \
    echo '@audio - rtprio 75' | sudo tee -a /etc/security/limits.conf

# --- 7. INSTALL SYSTEMD SERVICE ---
echo "Installing orcanode systemd service..."
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$REPO_DIR/orcanode.service" /etc/systemd/system/orcanode.service

# Update paths in the service file to match this machine
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" /etc/systemd/system/orcanode.service
sudo sed -i "s|ExecStart=.*stream_sync.sh|ExecStart=/bin/bash $REPO_DIR/stream_sync.sh|" /etc/systemd/system/orcanode.service

sudo systemctl daemon-reload
sudo systemctl enable orcanode.service

echo ""
echo "=== Setup Complete ==="
echo "IMPORTANT: You must reboot before starting the service."
echo "  Group membership (audio) and PAM limits require a reboot to take effect."
echo ""
echo "Before rebooting, create your .env file:"
echo "  cp $REPO_DIR/.env.example $REPO_DIR/.env"
echo "  nano $REPO_DIR/.env"
echo ""
echo "After rebooting, start the service with:"
echo "  sudo systemctl start orcanode"
echo "  journalctl -u orcanode -f"
echo ""
echo "Rebooting in 10 seconds... (Ctrl-C to cancel)"
sleep 10
sudo reboot
