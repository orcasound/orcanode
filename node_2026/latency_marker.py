#!/usr/bin/env python3
"""Latency test marker for stream_sync_latency.sh (CHECK_LATENCY=true).

Registers a JACK client, connects its outputs to ffjack's inputs once, and
at the top of every wall-clock minute writes a short full-scale tone into
the feed. JACK sums it with the real capture signal already connected to
ffjack, so the tone ends up in the HLS (and FLAC) output.

The tone's start is scheduled on JACK's frame clock rather than by
sleeping, so it lands within a few milliseconds of :00 regardless of
Python scheduling jitter. Each minute logs:

    LATENCY MARKER injected at <ISO time> (epoch <seconds>, UTC_TIME=...)

The time zone follows TZ, which stream_sync_latency.sh sets from UTC_TIME
so the log lines up with the FLAC filenames and HLS timestamps.
"""

import os
import sys
import time
from datetime import datetime

import jack
import numpy as np

DURATION_MS = float(os.environ.get("LATENCY_PULSE_DURATION_MS", "50"))
FREQ_HZ = float(os.environ.get("LATENCY_PULSE_FREQ_HZ", "1000"))
UTC_TIME = os.environ.get("UTC_TIME", "false")
TARGET = "ffjack"
RAMP_MS = 1.0          # short fade in/out so the tone doesn't click
WRAP = 2 ** 32         # JACK frame counter is 32-bit (wraps every ~25 h at 48 kHz)

client = jack.Client("latency_marker", no_start_server=True)
rate = client.samplerate

n = int(round(rate * DURATION_MS / 1000))
tone = np.sin(2 * np.pi * FREQ_HZ * np.arange(n) / rate).astype(np.float32)
ramp = min(int(rate * RAMP_MS / 1000), n // 2)
if ramp:
    fade = np.linspace(0.0, 1.0, ramp, dtype=np.float32)
    tone[:ramp] *= fade
    tone[-ramp:] *= fade[::-1]

targets = client.get_ports(TARGET + ":", is_input=True, is_audio=True)
if not targets:
    sys.exit(f"latency_marker: no {TARGET} input ports found")
outs = [client.outports.register(f"out_{i + 1}") for i in range(len(targets))]

# Absolute JACK frame at which the next tone starts, or None when idle.
# Written by the main thread, cleared by the process callback once the
# whole tone has been output.
pending = {"start": None}


@client.set_process_callback
def process(frames):
    bufs = [p.get_array() for p in outs]
    for b in bufs:
        b.fill(0.0)
    start = pending["start"]
    if start is None:
        return
    # Where the tone starts relative to this cycle, wrap-safe.
    offset = (start - client.last_frame_time + WRAP // 2) % WRAP - WRAP // 2
    lo, hi = max(offset, 0), min(offset + n, frames)
    if lo < hi:
        for b in bufs:
            b[lo:hi] = tone[lo - offset:hi - offset]
    if offset + n <= frames:
        pending["start"] = None


@client.set_shutdown_callback
def shutdown(status, reason):
    print(f"latency_marker: JACK shut down ({reason}), exiting", flush=True)
    os._exit(1)


with client:
    for out, target in zip(outs, targets):
        client.connect(out, target)
    print(f"latency_marker: connected {len(outs)} port(s) to {TARGET}, "
          f"{DURATION_MS:g} ms {FREQ_HZ:g} Hz tone at the top of every minute",
          flush=True)

    while True:
        boundary = (int(time.time()) // 60 + 1) * 60
        # Wake ~1 s early, then convert the remaining wall-clock time into
        # a JACK frame so the tone starts on the exact frame for :00.
        time.sleep(max(0.0, boundary - time.time() - 1.0))
        now_wall, now_frame = time.time(), client.frame_time
        pending["start"] = (now_frame + int(round((boundary - now_wall) * rate))) % WRAP

        time.sleep(max(0.0, boundary - time.time()) + DURATION_MS / 1000 + 0.2)
        if pending["start"] is not None:
            pending["start"] = None
            print("WARNING: latency marker was not written (JACK stalled?), "
                  "skipping this marker.", flush=True)
            continue
        when = datetime.fromtimestamp(boundary).astimezone().isoformat(timespec="seconds")
        print(f"LATENCY MARKER injected at {when} (epoch {boundary}, UTC_TIME={UTC_TIME})",
              flush=True)
