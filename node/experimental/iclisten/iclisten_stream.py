#!/usr/bin/env python3
"""Stream live PCM audio from an Ocean Sonics icListen hydrophone to stdout.

Connects to the hydrophone's real-time waveform telemetry socket (TCP), decodes
the framed sample data, and writes raw interleaved PCM to stdout so it can be
piped straight into ffmpeg, e.g.:

    iclisten_stream.py $ICLISTEN_HOST | \\
        ffmpeg -f s24le -ar <rate> -ac <channels> -i pipe:0 ...

The output byte format matches whatever the device is configured to send
(default 24-bit little-endian); the detected sample rate / format / channel
count are logged to stderr so the surrounding pipeline can be set to match
(configure rate & format in the icListen web interface).

STATUS: EXPERIMENTAL — not yet tested against real hardware. See README.md.
"""

import argparse
import logging
import signal
import socket
import struct
import sys
import time

# --- Protocol constants ---------

WAVEFORM_PORT = 51678          # TCP time-series (waveform) stream
SYNC = 0x2A                    # '*' — second byte of every message
MAX_MESSAGE = 6706             # sanity cap on payload length

# Message types (first byte of each message)
MSG_NOTIFY = 0x30             # control / error notification
MSG_DATA = 0x31              # carries PCM sample data
MSG_HEADER = 0x32            # "event header", ~1/sec, carries setup info
MSG_START = 0x33            # client -> device: start streaming
MSG_STOP = 0x34             # client -> device: stop streaming

# Chunk types (payloads are a sequence of these)
CHUNK_DATA = 0x42
CHUNK_WAVE_SETUP = 0x45

# Start-stream message: type '3', sync '*', payload length 4,
# payload = duration(uint16 BE = 0 -> forever) + requested-data(uint16 BE = 0).
START_STREAM = bytes([MSG_START, SYNC, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00])
STOP_STREAM = bytes([MSG_STOP, SYNC, 0x00, 0x00])

# Notification codes (payload of MSG_NOTIFY)
NOTIFY_MEANING = {
    1: "cannot start (no free stream connection)",
    2: "duration timeout",
    3: "stopped by stop/stop-all",
    4: "invalid start message",
    5: "cannot stream: device is busy logging",
}

log = logging.getLogger("iclisten")


# --- Pure parsing helpers (unit-tested in test_parse.py) ---------------------

def data_format_to_ffmpeg(fmt):
    """Map an icListen Data-Format byte to an ffmpeg `-f` sample format.

    Low 7 bits = bytes per sample; high bit (0x80) set = little-endian.
    """
    bytes_per_sample = fmt & 0x7F
    little_endian = bool(fmt & 0x80)
    endian = "le" if little_endian else "be"
    bits = {2: 16, 3: 24, 4: 32}.get(bytes_per_sample)
    if bits is None:
        raise ValueError("unsupported data format byte: %d" % fmt)
    return "s%d%s" % (bits, endian)


def iter_chunks(payload):
    """Yield (chunk_type, chunk_bytes) for each chunk in a message payload.

    Chunk header is [type:1][version:1][size:2 BE]; `size` counts the bytes
    after the 4-byte header. Stops cleanly if the payload is truncated.
    """
    i = 0
    n = len(payload)
    while i + 4 <= n:
        ctype = payload[i]
        size = (payload[i + 2] << 8) | payload[i + 3]
        end = i + 4 + size
        if end > n:
            break  # truncated / malformed chunk — stop rather than misread
        yield ctype, payload[i:end]
        i = end


def parse_wave_setup(chunk):
    """Return (sample_rate, data_format) from a Wave Setup (0x45) chunk."""
    # offsets from chunk start: 4..8 sample rate (uint32 BE), 10 data format
    sample_rate = struct.unpack(">I", chunk[4:8])[0]
    data_format = chunk[10]
    return sample_rate, data_format


def parse_data_chunk(chunk):
    """Return (num_channels, data_format, pcm_bytes) from a Data (0x42) chunk.

    Layout from chunk start: 8 #channels, 9 data format, 10..12 #samples
    (uint16 BE, per channel), 12.. interleaved samples, then 0-3 pad bytes.
    We compute the exact data length from the counts so the trailing 32-bit
    alignment padding is never emitted.
    """
    num_channels = chunk[8]
    data_format = chunk[9]
    num_samples = struct.unpack(">H", chunk[10:12])[0]
    bytes_per_sample = data_format & 0x7F
    n = num_samples * num_channels * bytes_per_sample
    pcm = chunk[12:12 + n]
    return num_channels, data_format, pcm


# --- Socket framing ----------------------------------------------------------

def recvall(sock, n):
    """Read exactly n bytes from sock, or raise ConnectionError on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed by peer")
        buf.extend(chunk)
    return bytes(buf)


def read_message(sock):
    """Read one framed message. Returns (msg_type, payload_bytes)."""
    header = recvall(sock, 4)
    if header[1] != SYNC:
        raise ValueError("bad sync byte 0x%02x (stream desync)" % header[1])
    length = (header[2] << 8) | header[3]
    if length > MAX_MESSAGE:
        raise ValueError("payload length %d exceeds max %d" % (length, MAX_MESSAGE))
    payload = recvall(sock, length) if length else b""
    return header[0], payload


# --- Main streaming loop -----------------------------------------------------

def stream_once(host, port, out):
    """Connect, stream, and write PCM to `out` until the connection ends."""
    log.info("connecting to %s:%d", host, port)
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(30)
        sock.sendall(START_STREAM)
        log.info("start-stream sent; streaming")
        announced = False
        while True:
            msg_type, payload = read_message(sock)
            if msg_type == MSG_DATA:
                for ctype, chunk in iter_chunks(payload):
                    if ctype == CHUNK_DATA:
                        _, _, pcm = parse_data_chunk(chunk)
                        if pcm:
                            out.write(pcm)
                out.flush()
            elif msg_type == MSG_HEADER:
                if not announced:
                    for ctype, chunk in iter_chunks(payload):
                        if ctype == CHUNK_WAVE_SETUP:
                            rate, fmt = parse_wave_setup(chunk)
                            log.info(
                                "device: %d Hz, format 0x%02x (ffmpeg -f %s)",
                                rate, fmt, data_format_to_ffmpeg(fmt))
                            announced = True
            elif msg_type == MSG_NOTIFY:
                code = struct.unpack(">I", payload[:4])[0] if len(payload) >= 4 else 0
                meaning = NOTIFY_MEANING.get(code, "unknown")
                log.warning("notify code %d: %s", code, meaning)
                if code in (1, 3, 5):
                    return  # device dropped the stream — let caller reconnect
            # any other message type: already fully read; ignore.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="icListen IP address or hostname")
    parser.add_argument("--port", type=int, default=WAVEFORM_PORT)
    parser.add_argument("--reconnect-delay", type=float, default=5.0,
                        help="seconds to wait before reconnecting (0 = exit on drop)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s iclisten: %(message)s")

    # Exit quietly if the downstream consumer (ffmpeg) closes the pipe.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    out = sys.stdout.buffer
    while True:
        try:
            stream_once(args.host, args.port, out)
        except (OSError, ValueError) as exc:
            log.warning("stream error: %s", exc)
        if args.reconnect_delay <= 0:
            return 1
        time.sleep(args.reconnect_delay)


if __name__ == "__main__":
    sys.exit(main())
