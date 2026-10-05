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

   Both modes embed absolute timestamps with a UTC offset (`EXT-X-PROGRAM-DATE-TIME`)
   in the manifest so players and researchers can locate segments by
   time.
5. Launches `upload_s3.py` to stream segments to S3 as they are written
6. **research** only: launches `upload_flac_s3.py` to upload each FLAC
   chunk to the archive bucket as it is finished
7. Launches `catchup_s3.py` (`nice -n 10`) to recover segments (and,
   on research nodes, FLAC chunks) missed during any internet outage

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
| `BUCKET_STREAMING` | HLS bucket name. Required only when `BUCKET_TYPE=custom`. |
| `BUCKET_ARCHIVE` | FLAC archive bucket name. Required only when `BUCKET_TYPE=custom` on `research` nodes. |
| `AWS_ACCESS_KEY_ID` | Your AWS access key |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key |
| `AWS_METADATA_SERVICE_TIMEOUT` | `5` |
| `AWS_METADATA_SERVICE_NUM_ATTEMPTS` | `0` |
| `REGION` | `us-west-2` |
| `LOGDNA_INGESTION_KEY` | Optional. Set to forward `upload_s3.py`/`upload_flac_s3.py`/`catchup_s3.py` logs to Mezmo (formerly LogDNA) — warnings/errors from the uploader, and catch-up activity after an outage. Leave unset to skip centralized logging entirely; nothing else depends on it. |
| `LC_ALL` | `C.UTF-8` |
| `NO_UPLOAD` | `false` — set `true` to test the pipeline without S3 |
| `UTC_TIME` | `false` — FLAC filenames and HLS `EXT-X-PROGRAM-DATE-TIME` use the Pi's local time. Set `true` to use UTC instead. Either way the HLS timestamps carry a UTC offset, so they mark the same instant; only the FLAC filenames change meaning. |
| `CHECK_LATENCY` | `false` — set `true` to inject a full-scale test tone at the top of every minute, for measuring capture-to-S3/player latency. Only has an effect when running `stream_sync_latency.sh` (see note below); ignored by the normal `stream_sync.sh`. |
| `LATENCY_PULSE_DURATION_MS` | Optional. Length of the latency test tone in milliseconds. Default `50`. |
| `LATENCY_PULSE_FREQ_HZ` | Optional. Frequency of the latency test tone in Hz. Default `1000`. |

> **Note:** Set `NO_UPLOAD=true` during initial testing. Segments will
> accumulate locally in `/tmp/<NODE_NAME>/hls/` so you can verify the
> pipeline end-to-end before enabling live uploads.

> **Note:** `CHECK_LATENCY` is read by `stream_sync_latency.sh`, a
> diagnostic copy of `stream_sync.sh` that also starts
> `latency_marker.py`, a small JACK client that mixes the tone into the
> feed at the top of each minute. To use it, override the container command, e.g. add to
> `docker-compose.yml` (or an override file):
> ```yaml
> command: ./stream_sync_latency.sh
> ```
> It launches the same uploaders as `stream_sync.sh` — `upload_s3.py`
> and `catchup_s3.py`, plus `upload_flac_s3.py` on `research` nodes — so
> the marker tone reaches S3 by the normal paths.
> Then check the container logs for `LATENCY MARKER injected at ...`
> lines, and compare that wall-clock timestamp against when the tone
> actually shows up in the archived S3 files (HLS segments, and on
> research nodes the FLAC chunks under `<NODE_NAME>/flac/` in the
> archive bucket) and in the live player. The marker log line uses the
> same time zone as the FLAC filenames (UTC if `UTC_TIME=true`,
> otherwise the Pi's local time), with its UTC offset and the Unix epoch.

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
Time synchronized: <date>
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

Each `.flac` file covers `FLAC_DURATION` seconds of lossless audio. The
filename (`YYYY-MM-DD_HH-MM-SS_<NODE_NAME>-<SAMPLE_RATE>-<CHANNELS>.flac`)
gives the chunk's start time in the Pi's local time, or in UTC if
`UTC_TIME=true` (see Step 4).

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

## Updating a Deployed Node

To get new code from the `node_2026` branch onto a Pi that's already
running, pull it with git and **rebuild the image**. The Dockerfile
copies the scripts into the image at build time, so `git pull` alone
leaves the container running the old code.

**1. SSH in over Tailscale:**

```bash
ssh pi@<node-hostname>      # or ssh pi@100.x.x.x
```

**2. Check for local edits, then pull:**

```bash
cd ~/orcanode
git status            # should be clean, on branch node_2026
git pull
git log --oneline -1  # confirm you're on the expected commit
```

`.env` is in `.gitignore`, so the pull never overwrites it. If
`git status` shows files edited on the Pi, `git stash` them (or commit
them) before pulling.

**3. Add any new `.env` settings.** A pull doesn't add new variables to
an existing `.env` — compare it against `.env.template` and add what's
missing (see Step 4 for what each does):

```bash
cd ~/orcanode/node_2026
diff <(grep -o '^#\?[A-Z_]*=' .env.template | tr -d '#' | sort -u) \
     <(grep -o '^[A-Z_]*=' .env | sort -u)
nano .env
```

Lines starting with `<` are in the template but not in your `.env`.
Most have safe defaults when missing (e.g. `UTC_TIME` behaves as
`false`), but with `BUCKET_TYPE=custom` you need `BUCKET_STREAMING`,
plus `BUCKET_ARCHIVE` on research nodes.

**4. Rebuild and restart:**

```bash
docker compose up -d --build
```

Only the steps that copy the code rerun, so this is quick after the
first build.

**5. Verify** with `docker compose logs -f` and the checks in Step 7.
For example, the startup log should include a `UTC_TIME=...` line, and
on research nodes FLAC chunks in `/tmp/<NODE_NAME>/flac/` should
disappear as they upload (with `NO_UPLOAD=false`).

**If the Pi's copy isn't a git clone** (files were copied over by hand),
make a fresh clone next to it and bring `.env` across:

```bash
git clone -b node_2026 https://github.com/orcasound/orcanode.git ~/orcanode_new
cp ~/orcanode/node_2026/.env ~/orcanode_new/node_2026/
cd ~/orcanode/node_2026 && docker compose down
cd ~/orcanode_new/node_2026 && docker compose up -d --build
```

Then check the midnight-restart crontab entry (`crontab -l`) still
points at the folder you're now running from.

---

## Internet Outage Recovery

`upload_s3.py` leaves segments on disk when uploads fail. When
connectivity returns, `catchup_s3.py` finds stranded segments,
generates a VOD manifest (`catchup.m3u8`), and uploads everything at
low priority (2s between segments).

On research nodes, `upload_flac_s3.py` likewise leaves FLAC files on
disk when uploads fail, and `catchup_s3.py` uploads them to the archive
bucket after the HLS catch-up (no manifest needed).

**Disk guard:** if stranded segments exceed 500 MB, the oldest are
deleted first to protect the SD card. Stranded FLAC files have their
own separate 500 MB limit.

No configuration required — this runs automatically alongside
`upload_s3.py`.

---

## Centralized Logging (Mezmo / LogDNA)

If `LOGDNA_INGESTION_KEY` is set in `.env` (see Step 4), `upload_s3.py`,
`upload_flac_s3.py` and `catchup_s3.py` forward selected log lines to
[Mezmo](https://app.mezmo.com/) (formerly LogDNA) over HTTPS, so you
can check on a node's health without SSHing in. This is optional —
leave the key unset and nothing changes.

**What gets sent:**

| Source | Minimum level forwarded | Typical content |
|---|---|---|
| `upload_s3.py` | `WARNING` | Low-RMS warnings (possible silence/bad capture), S3 upload failures |
| `upload_flac_s3.py` | `WARNING` | FLAC upload failures, skipped empty/missing files (research nodes only) |
| `catchup_s3.py` | `INFO` | Stranded segments and FLAC files found after an outage, disk-guard deletions, catch-up progress |

Routine per-segment activity (every successful upload, RMS values on a
healthy signal) stays local-only by design, to avoid flooding a
rate-limited API — check those with `docker compose logs -f` instead.
Boot-time output (`stream_sync.sh`, JACK, ffmpeg) isn't sent to Mezmo
either, since it never passes through Python logging; that's local-only
too, same command.

**To view the logs:**

1. Log into [app.mezmo.com](https://app.mezmo.com/) with the account
   tied to your ingestion key.
2. Each node reports under its `NODE_NAME` as the **Host** — use the
   Host filter (left sidebar, or `host:` in the search bar) to narrow
   to one node. This is why keeping `NODE_NAME` unique per node
   (Step 4) matters here too.
3. Use the **App** filter (or `app:` in the search bar) to separate
   `upload_s3`, `upload_flac_s3` and `catchup_s3` events.
4. Use the **Level** filter to jump straight to `WARN`/`ERROR` — that's
   the fastest way to spot a node that's gone silent or lost its audio
   signal without reading through everything.

If a node's logs aren't showing up in Mezmo at all, check the
container's own log first — the handler logs a local warning
(`LogDNA delivery failed: ...`) whenever it can't reach Mezmo, so
`docker compose logs -f` will tell you if the key is wrong or the node
has no route out:

```bash
docker compose logs -f | grep -i logdna
```

---

## Troubleshooting

**Container keeps restarting with "Waiting for time sync..." then
"ERROR: Time sync timed out":** the Pi's clock isn't NTP-synchronized
yet. `stream_sync.sh` refuses to record until it is, because the
timestamps go into the stream and filenames. On the Pi (not in the
container), check:

```bash
timedatectl            # want "System clock synchronized: yes"
systemctl status systemd-timesyncd chrony --no-pager
```

Usually it's no internet, or blocked NTP (UDP 123) on the site network.
Once the Pi syncs, the next container restart gets past this step.

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
