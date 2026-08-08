# CLONE_README.md — Turning an SD-Card Clone into a New Node

## Background

The usual way to provision a new hydrophone node is to flash a fresh SD
card and walk through `README.txt` end to end (`setup.sh`, `.env`, Docker
build). That takes ~30-45 minutes per Pi because of package installs and
the Docker image build.

A faster path: image a **known-good, already-built SD card** (Docker
installed, image already built, `orcanode` repo cloned) and clone that
image onto new SD cards for additional Pis. This skips the slow parts —
but a raw SD-card clone is a *bit-for-bit copy*, which means the new Pi
boots up claiming to be an exact duplicate of the original: same
hostname, same machine-id, same SSH host keys, same S3 `NODE_NAME`, and
— critically — the same **Tailscale identity**.

If you skip the de-duplication steps below, two symptoms show up:

- The new Pi's audio segments overwrite the original node's data on S3
  (they'd upload to the same `NODE_NAME` prefix).
- Tailscale treats the clone as the *same machine* re-appearing at a new
  IP. Instead of a new device on your tailnet, you get one flapping
  entry — whichever Pi checked in most recently "wins" and the other
  drops offline.

This doc covers de-duplicating a clone and bringing it up as a distinct,
independent node.

---

## What's already on the clone

Assuming the source SD card was a working `node_2026` install:

- Raspberry Pi OS, Docker, and the `docker/audio` group memberships from
  `setup.sh`
- `~/orcanode/node_2026/` checked out, with the Docker image
  already built (`docker compose up -d --build` has been run at least
  once)
- A working `.env` with the **original** node's `NODE_NAME` and AWS
  credentials
- Tailscale installed and authenticated as the **original** node
- The container is likely still running from before the card was imaged
  — it will start immediately using the old `.env` on first boot

---

## Step 1 — Flash the clone and boot it standalone

Flash the cloned image to the new SD card (Raspberry Pi Imager, `dd`,
balenaEtcher — whatever you used to make the clone in the first place).

Before inserting it into the new Pi:

- **Do not** boot the new Pi on the same network as the original while
  both still share the same Tailscale identity — the identity collision
  happens the moment `tailscaled` on the new Pi calls home. It's not
  destructive, but it will bounce the original node offline until you
  fix it, so do the fixes below before letting the new Pi sit online for
  long.
- If you used Raspberry Pi Imager to write the clone, use its "Edit
  Settings" (gear icon) to preset a new **hostname** and re-enable SSH
  before first boot — this saves a step, but does not fix Tailscale or
  the SSH host keys, which are handled below.

Boot the new Pi and get a shell on it — either directly (keyboard/HDMI),
or via the LAN IP shown in your router's DHCP client list (do this over
plain SSH/local network, not Tailscale, since Tailscale isn't safe to
rely on yet):

```bash
ssh pi@<new-pi-lan-ip>
```

---

## Step 2 — Fix machine identity before anything else

These make the new Pi behave as its own device instead of a duplicate of
the source. Do this before touching Tailscale.

**Regenerate the machine-id** (used by systemd, DHCP client identifiers,
and some other services to distinguish hosts):

```bash
sudo rm -f /etc/machine-id
sudo systemd-machine-id-setup
```

**Regenerate SSH host keys** (a cloned Pi ships with the *same* host
keys as the source — SSH clients that already trust the original will
throw host-key-mismatch warnings, or worse, silently trust the wrong
box):

```bash
sudo rm -f /etc/ssh/ssh_host_*
sudo dpkg-reconfigure openssh-server
sudo systemctl restart ssh
```

**Set a unique hostname** (pick something that matches the new
`NODE_NAME` you'll set in Step 3, e.g. `rpi-orcasound-bush-point`):

```bash
sudo raspi-config nonint do_hostname rpi-orcasound-bush-point
sudo reboot
```

SSH back in after the reboot (still over LAN, not Tailscale) using the
new hostname or the same LAN IP.

---

## Step 3 — Edit `.env` for the new node

Stop the container first so it isn't uploading under the old identity
while you edit:

```bash
cd ~/orcanode/node_2026
docker compose down
nano .env
```

| Variable | Action | Why |
|---|---|---|
| `NODE_NAME` | **Change — must be unique** | This is the S3 path prefix (`s3://<bucket>/<NODE_NAME>/hls/...`). Two nodes sharing a name will overwrite each other's segments. |
| `AUDIO_HW_ID` | Verify | Should still be `pisound` if this Pi also has a Pisound HAT; confirm with `aplay -l` since HAT enumeration order can vary between boards. |
| `NODE_TYPE` | Verify | `hls-only` or `research` — set per what this node should do, independent of the source node's setting. |
| `NODE_LOOPBACK` | Verify | Local-monitoring preference for this physical install, not necessarily the same as the source. |
| `BUCKET_TYPE` | Usually unchanged | Keep `prod` unless this new node is a test/dev deployment. |
| `NO_UPLOAD` | Set `true` temporarily | Recommended for first boot — verify segments generate locally before enabling live S3 upload with a brand-new `NODE_NAME`. Flip to `false` once verified (see Step 6). |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Usually unchanged | Same bucket, same credentials — unless this node should log in under a separate IAM identity. |
| `LOGDNA_INGESTION_KEY` | Usually unchanged | Shared Mezmo/LogDNA ingestion key, if set; logs from all nodes land in the same place, distinguished by the `hostname` each node sends (its `NODE_NAME`). |
| Everything else (`SAMPLE_RATE`, `CHANNELS`, `SEGMENT_DURATION`, `FLAC_DURATION`, `REGION`, `LC_ALL`) | Usually unchanged | Hardware/format constants, not node-specific. |

Do **not** rebuild the Docker image for a `.env` change — `.env` is
injected at container start via `env_file:` in `docker-compose.yml`, so
`docker compose up -d` alone picks up the new values.

---

## Step 4 — Reset and re-initialize Tailscale

This is the step that actually resolves the identity collision. Cloning
the SD card copied `/var/lib/tailscale/tailscaled.state`, which holds
the node's private key — that key *is* the machine's identity as far as
Tailscale is concerned. Wipe it and re-authenticate to mint a new
identity:

```bash
sudo systemctl stop tailscaled
sudo rm -f /var/lib/tailscale/tailscaled.state
sudo systemctl start tailscaled
sudo tailscale up --hostname=rpi-orcasound-bush-point
```

- This prints an authentication URL — open it in a browser and approve
  the new machine under your tailnet.
- `--hostname` sets the name Tailscale shows in the admin console;
  match it to what you set in `raspi-config` in Step 2 so the LAN
  hostname and Tailscale name agree.
- If you'd rather rename after the fact instead of via the flag, you can
  approve first and then rename it from
  `https://login.tailscale.com/admin/machines`.

Confirm it registered as a **new, separate** device:

```bash
tailscale status
```

You should see the new Pi listed by its new hostname with its own
`100.x.x.x` address, and — check the admin console — the **original**
node should still be online and unaffected (this confirms the identity
split actually worked; if the original dropped offline when the new one
came up, the state file wasn't fully cleared — repeat the `rm` /
`tailscale up` steps).

Get the new Pi's Tailscale IP for later reference:

```bash
tailscale ip -4
```

---

## Step 5 — Bring the streaming container up

```bash
cd ~/orcanode/node_2026
docker compose up -d
```

(No `--build` needed — the image was already built on the source Pi and
cloned along with the rest of the SD card. Only rebuild if you've also
changed code, not just `.env`.)

Watch the logs for a healthy startup:

```bash
docker compose logs -f
```

Expect:

```
Time looks sane: <date>
Success! pisound found at index N. Using address: hw:N,0
JACK is ready.
```

---

## Step 6 — Verify the new node end-to-end

**Tailscale admin console** (`https://login.tailscale.com/admin/machines`):
the new node appears as its own entry, distinct from the source, with
its own IP and last-seen time ticking forward.

**SSH over Tailscale** (from any device on the tailnet, not just LAN):

```bash
ssh pi@rpi-orcasound-bush-point
# or
ssh pi@$(tailscale ip -4)
```

**Local HLS segments** (confirms JACK/ffmpeg pipeline is healthy on this
hardware):

```bash
docker compose exec streaming ls -lh /tmp/<NODE_NAME>/hls/
```

**S3 upload**, once you're satisfied and have flipped `NO_UPLOAD=false`
in `.env` and restarted (`docker compose up -d` picks up the change):

```bash
aws s3 ls s3://audio-orcasound-net/<NODE_NAME>/hls/ --human-readable
```

Confirm the objects land under the **new** `NODE_NAME` prefix, not the
original node's.

---

## Troubleshooting

**Original node dropped offline right as the new one came up.**
Classic Tailscale identity collision — the state file wasn't cleared
before `tailscale up`. Re-run Step 4's `rm`/restart sequence on the
*new* Pi.

**Both Pis show the same hostname in the Tailscale admin console.**
`--hostname` wasn't picked up, or you renamed only one of LAN hostname
/ Tailscale hostname. Rename directly in the admin console as a
one-off fix, then align `raspi-config` to match.

**New node's segments aren't showing up in S3 under the expected
prefix.** `.env` still has the old `NODE_NAME` — check `docker compose
exec streaming env | grep NODE_NAME` to see what the *running*
container actually has (stale containers keep old env until recreated
with `docker compose up -d`).

**SSH warns about a host key mismatch when connecting to the new
Tailscale hostname.** Either Step 2's host-key regeneration was skipped,
or your local `~/.ssh/known_hosts` cached the source Pi's key under a
name now reused by the clone. Remove the stale entry:
`ssh-keygen -R rpi-orcasound-bush-point`.
