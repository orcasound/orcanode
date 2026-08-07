# Orcasound Hydrophone Node

| | |
|---|---|
| **Hardware** | Raspberry Pi 4 with Pisound HAT |
| **OS** | Raspberry Pi OS (Bookworm or Trixie) |
| **Container** | `orcasound/orcanode_val_docker` (built locally from `Dockerfile`) |

## Overview

This node captures audio from a Pisound HAT, segments it into HLS
(`.ts`) files using JACK + ffmpeg, and uploads them to S3. Everything
except Docker (and Tailscale, for remote access) runs inside the
container. Docker restarts the container automatically on crash or
reboot — no separate systemd service is needed.

On startup `stream_sync.sh`:

1. Waits for a sane system clock
2. Discovers the Pisound ALSA device
3. Starts `jackd` with the discovered hw address
4. Launches ffmpeg to capture from JACK and write:
   - **hls-only**: HLS segments (`.ts`) + growing `live.m3u8` (all
     segments for the day)
   - **research**: same HLS output, plus lossless FLAC archive chunks

   Both modes embed absolute UTC timestamps (`EXT-X-PROGRAM-DATE-TIME`)
   in the manifest so players and researchers can locate segments by
   time.
5. Launches `upload_s3.py` to stream segments to S3 as they are written
6. Launches `catchup_s3.py` (`nice -n 10`) to recover segments missed
   during any internet outage

## Prerequisites

- Raspberry Pi 4 with Pisound HAT installed and recognized by the OS
- Fresh Raspberry Pi OS image flashed to SD card
- SSH enabled, Pi connected to the internet
- AWS credentials with write access to the target S3 bucket
- A [Tailscale](https://tailscale.com) account (free tier is fine) —
  used for remote SSH access once the node is deployed in the field

---

## Step 1 — First Boot Configuration

Flash your SD card with Raspberry Pi Imager and set:

- Hostname (e.g. `rpi-orcasound-lab`) — pick this now; you'll reuse it
  as the Tailscale machine name in Step 2 and as `NODE_NAME` in Step 4
- SSH enabled
- Username: `pi` (or your preferred username)
- Password
- WiFi SSID and password — **only if using WiFi.** Ethernet is
  recommended: it's more reliable for an unattended field node, and
  skips WiFi setup entirely. If you're wiring Ethernet, leave the
  Wireless LAN tab blank.

**Using Ethernet:** plug the cable into the Pi and your router/switch
*before* first power-on, so DHCP negotiation happens cleanly at boot.
Then boot the Pi and find it — no monitor needed:

```bash
ping rpi-orcasound-lab.local     # mDNS/Avahi, on by default
ssh pi@rpi-orcasound-lab.local
```

If `.local` doesn't resolve from your machine, check your router's
DHCP client list for the hostname/IP instead. A DHCP reservation (by
MAC address) is worth setting up once you see the IP, so it stays
consistent for direct LAN troubleshooting later — day-to-day remote
access will go through Tailscale instead (Step 2), so this is a
convenience, not a requirement.

**Optional — disable the onboard WiFi radio.** If this Pi will only
ever use Ethernet, disabling WiFi entirely avoids it hunting for
networks, logging noise, or drawing power for nothing:

```bash
echo "dtoverlay=disable-wifi" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

(`/boot/firmware/config.txt` is the Bookworm/Trixie path — not the
older `/boot/config.txt`.)

**Using WiFi instead:** boot the Pi and SSH in directly:

```bash
ssh pi@<pi-ip-address>
```

---

## Step 2 — Install and Configure Tailscale

Field-deployed nodes are usually headless and behind a NAT you don't
control, so plain SSH to a LAN IP stops working the moment the Pi
leaves your bench. Tailscale gives the node a stable address on your
private tailnet that works from anywhere, without port forwarding.

Install and bring it up: ( sudo tailscale up --force-reauth to re-authorize connection to tailscale)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up        # --force-reauth  
sudo tailscale set --operator=$USER
tailscale set --ssh

```

This prints an authentication URL. Open it in a browser and approve
the device against your tailnet.

Once approved, rename the machine in the
[Tailscale admin console](https://login.tailscale.com/admin/machines)
to match the hostname you chose in Step 1 (e.g. `rpi-orcasound-lab`) —
keeping the LAN hostname, Tailscale name, and later `NODE_NAME` all in
sync makes the node much easier to identify once you have several
deployed.

Confirm the node is up and get its tailnet address:

```bash
tailscale status
tailscale ip -4
```

The Pi should now appear as its own entry in the admin console with a
`100.x.x.x` address and a "last seen" time that keeps ticking forward.

In the admin console, click the three dots next to the new machine and
choose **Edit ACL tags** to tag it with its role (e.g. `research`,
`production`, `veirs`) — useful once you have several nodes and want
to filter or write ACLs by tag.

From here on you can SSH in over Tailscale instead of the LAN IP —
useful for the rest of this setup, and essential once the node is
shipped to its deployment site:

```bash
ssh pi@rpi-orcasound-lab
# or
ssh pi@$(tailscale ip -4)
```

---

## Step 3 — Clone the Repository

This node currently lives on the `node_2026` branch, not yet merged
into `main` — clone that branch directly, or `cd ~/orcanode/node_2026`
will fail with no such directory:

```bash
sudo apt-get install -y git
git clone -b node_2026 https://github.com/orcasound/orcanode.git ~/orcanode
cd ~/orcanode/node_2026
```

---

## Step 4 — Create the `.env` File

The `.env` file holds node-specific config and AWS credentials. It is
never baked into the Docker image — Docker Compose injects it at
runtime.

```bash
cp ~/orcanode/node_2026/.env.template ~/orcanode/node_2026/.env
nano ~/orcanode/node_2026/.env
```

Required variables:

| Variable | Description |
|---|---|
| `NODE_NAME` | Unique name for this node — also used as the S3 path prefix. Match it to the Tailscale/LAN hostname from Steps 1–2 to keep node identity consistent everywhere. |
| `NODE_TYPE` | `hls-only` or `research` |
| `AUDIO_HW_ID` | Sound card name — verify with `aplay -l` |
| `SAMPLE_RATE` | `48000` |
| `CHANNELS` | `2` |
| `SEGMENT_DURATION` | HLS segment length in seconds |
| `FLAC_DURATION` | FLAC archive chunk length (research mode) |
| `NODE_LOOPBACK` | `true` to monitor audio on local output |
| `BUCKET_TYPE` | `prod`, `dev`, or `custom` |
| `AWS_ACCESS_KEY_ID` | Your AWS access key |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key |
| `AWS_METADATA_SERVICE_TIMEOUT` | `5` |
| `AWS_METADATA_SERVICE_NUM_ATTEMPTS` | `0` |
| `REGION` | `us-west-2` |
| `SYSLOG_URL` | `syslog://syslog-a.logdna.com:37043` |
| `SYSLOG_STRUCTURED_DATA` | `logdna@48950 key="<your-key>" tag="docker"` |
| `LC_ALL` | `C.UTF-8` |
| `NO_UPLOAD` | `false` — set `true` to test the pipeline without S3 |

> **Note:** Set `NO_UPLOAD=true` during initial testing. Segments will
> accumulate locally in `/tmp/<NODE_NAME>/hls/` so you can verify the
> pipeline end-to-end before enabling live uploads.

---

## Step 5 — Run Setup Script

`setup.sh` installs Docker, fixes the Docker Hub IPv6 issue (common on
Pi OS Trixie), and adds the user to the `docker` and `audio` groups:

```bash
cd ~/orcanode/node_2026
bash setup.sh
```

The script reboots the Pi when complete. Wait for reboot, then SSH
back in (over Tailscale, if you're off the LAN by this point).

> **Note:** `jackd`, `ffmpeg`, and Python run inside the Docker
> container — `setup.sh` does not install them on the host.

---

## Step 6 — Build and Start the Container

Build the image and start (first time only, or after code changes):

```bash
cd ~/orcanode/node_2026
docker compose up -d --build
```

After the first build, Docker manages the container automatically:

- `restart: always` — restarts on crash without any action needed
- Docker enabled at boot — container starts on every reboot
- crontab (installed by `setup.sh`) restarts at midnight each night so
  each calendar day gets its own S3 timestamp directory and a complete
  `live.m3u8` covering only that day

Watch the startup logs:

```bash
docker compose logs -f
```

Healthy startup looks like:

```
Time looks sane: <date>
Success! pisound found at index N. Using address: hw:N,0
JACK is ready.
```

(then silence — ffmpeg and the uploaders run quietly)

---

## Step 7 — Verify the Pipeline

Check that HLS segments are being generated locally:

```bash
docker compose exec streaming ls -lh /tmp/<NODE_NAME>/hls/
```

Each `.ts` segment should be 150-300 KB. Watch them appear in real
time:

```bash
docker compose exec streaming watch -n 1 'ls -lh /tmp/<NODE_NAME>/hls/*/'
```

In research mode, also check FLAC files are being written:

```bash
docker compose exec streaming ls -lh /tmp/<NODE_NAME>/flac/
```

Each `.flac` file covers `FLAC_DURATION` seconds of lossless audio.

If `NO_UPLOAD=false`, verify segments are reaching S3:

```bash
aws s3 ls s3://audio-orcasound-net/<NODE_NAME>/hls/ --human-readable
```

Segments are stored under a timestamp subdirectory, e.g.:

```
s3://audio-orcasound-net/<NODE_NAME>/hls/<timestamp>/live000.ts
```

The live manifest (`live.m3u8`) grows throughout the day, accumulating
every segment since the last midnight restart. Inspect it to confirm
`program_date_time` tags:

```bash
aws s3 cp s3://audio-orcasound-net/<NODE_NAME>/hls/<timestamp>/live.m3u8 -
```

Check the upload log for RMS values (healthy signal = RMS > 100):

```bash
docker compose logs -f
```

Finally, confirm the node is reachable remotely: from another device
on your tailnet, check the
[Tailscale admin console](https://login.tailscale.com/admin/machines)
for this node's entry and try `ssh pi@<node-hostname>`.

---

## Container Management

```bash
docker compose up -d          # start (after first build)
docker compose down           # stop
docker compose restart        # restart
docker compose logs -f        # follow live logs
docker compose up -d --build  # rebuild image and restart (after code changes)
```

Open a shell inside the running container:

```bash
docker compose exec streaming /bin/bash
```

Check JACK port connections from inside the container:

```bash
docker compose exec streaming jack_lsp -c
```

You should see `system:capture_1/2` connected to `ffjack:input_1/2`.

---

## Internet Outage Recovery

`upload_s3.py` leaves segments on disk when uploads fail. When
connectivity returns, `catchup_s3.py` finds stranded segments,
generates a VOD manifest (`catchup.m3u8`), and uploads everything at
low priority (2s between segments).

**Disk guard:** if stranded segments exceed 500 MB, the oldest are
deleted first to protect the SD card.

No configuration required — this runs automatically alongside
`upload_s3.py`.

---

## Troubleshooting

**Docker pull/push fails ("network is unreachable"):**
IPv6 issue on Pi OS Trixie. `setup.sh` fixes this automatically. If it
recurs, re-run `setup.sh` or manually add the Docker Hub IPv4 to
`/etc/hosts`:

```bash
curl -4 -v https://registry-1.docker.io/v2/ 2>&1 | grep "Connected to"
echo "<IP>    registry-1.docker.io" | sudo tee -a /etc/hosts
```

**JACK "Bus error" or "Cannot lock down memory":**
The container needs a larger `/dev/shm`. Verify `docker-compose.yml`
contains:

```yaml
shm_size: '256m'
```

Rebuild and restart if you change it.

**Audio device not found (pisound):**
Check the device is visible on the host:

```bash
aplay -l
```

Verify `AUDIO_HW_ID` in `.env` matches the card name shown by
`aplay -l`.

**Segments are silent (RMS near 0):**
JACK ports are not connected. Reconnect manually and restart:

```bash
docker compose exec streaming jack_connect system:capture_1 ffjack:input_1
docker compose exec streaming jack_connect system:capture_2 ffjack:input_2
docker compose restart
```

**`.env` not loading:**
Verify no Windows line endings:

```bash
file ~/orcanode/node_2026/.env
```

If it shows "CRLF", convert it:

```bash
sed -i 's/\r//' ~/orcanode/node_2026/.env
```

**Node doesn't appear in the Tailscale admin console:**
Confirm `tailscaled` is actually running and the device authenticated
successfully:

```bash
sudo systemctl status tailscaled
sudo tailscale up
```

If `tailscale up` reports it's already logged in but the node still
isn't listed, check you're looking at the correct tailnet (organization)
in the admin console — easy to mix up if you're a member of more than
one.

**SSH over Tailscale hangs or refuses the connection:**
Confirm the Pi's Tailscale status is `Connected`, not `Idle` or
`NeedsLogin`:

```bash
tailscale status
```

Also check the admin console for an ACL restricting SSH between
devices/tags — a permissive default tailnet allows it, but locked-down
tailnets need an explicit ACL rule.

---

For help, open an issue at: https://github.com/orcasound/orcanode
