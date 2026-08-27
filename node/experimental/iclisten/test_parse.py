#!/usr/bin/env python3
"""Offline unit tests for iclisten_stream parsing.

No hardware or network required. Builds synthetic protocol frames and checks
that the parser extracts the correct sample rate, format, and PCM bytes.

Run:  python3 test_parse.py
"""

import struct
import sys

import iclisten_stream as ic


def build_chunk(ctype, body):
    """[type][version=0][size:2 BE][body]"""
    return bytes([ctype, 0]) + struct.pack(">H", len(body)) + body


def build_wave_setup(sample_rate, data_format, gain=0):
    # body offsets (from chunk start): 4 rate(u32), 8 gain(u16), 10 fmt, 11 rsvd
    body = struct.pack(">I", sample_rate) + struct.pack(">H", gain) + bytes([data_format, 0])
    return build_chunk(ic.CHUNK_WAVE_SETUP, body)


def build_data_chunk(num_channels, data_format, pcm, num_samples, pad=b""):
    # body offsets: 4 sample#(u32), 8 #chan, 9 fmt, 10 #samples(u16), 12 data..
    body = (struct.pack(">I", 0)
            + bytes([num_channels, data_format])
            + struct.pack(">H", num_samples)
            + pcm + pad)
    return build_chunk(ic.CHUNK_DATA, body)


def build_message(msg_type, payload):
    return bytes([msg_type, ic.SYNC]) + struct.pack(">H", len(payload)) + payload


class FakeSock:
    """Minimal socket stand-in that serves bytes from a buffer via recv()."""

    def __init__(self, data):
        self.data = bytes(data)
        self.pos = 0

    def recv(self, n):
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk


def check(name, cond):
    print(("PASS" if cond else "FAIL") + ": " + name)
    if not cond:
        raise AssertionError(name)


def main():
    # 1. Data-format -> ffmpeg mapping
    check("fmt 131 -> s24le", ic.data_format_to_ffmpeg(131) == "s24le")
    check("fmt 3 -> s24be", ic.data_format_to_ffmpeg(3) == "s24be")
    check("fmt 130 -> s16le", ic.data_format_to_ffmpeg(130) == "s16le")
    check("fmt 4 -> s32be", ic.data_format_to_ffmpeg(4) == "s32be")

    # 2. Wave Setup parsing
    ws = build_wave_setup(64000, 131)
    rate, fmt = ic.parse_wave_setup(ws)
    check("wave setup rate", rate == 64000)
    check("wave setup format", fmt == 131)

    # 3. Data chunk parsing (24-bit LE, mono, 2 samples) with trailing padding
    pcm = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])  # 2 samples x 3 bytes
    dc = build_data_chunk(1, 131, pcm, num_samples=2, pad=b"\x00\x00")
    nchan, dfmt, out = ic.parse_data_chunk(dc)
    check("data chunk channels", nchan == 1)
    check("data chunk format", dfmt == 131)
    check("data chunk pcm excludes padding", out == pcm)

    # 4. Multi-channel length maths (stereo, 16-bit, 3 samples -> 12 bytes)
    spcm = bytes(range(12))
    sdc = build_data_chunk(2, 130, spcm, num_samples=3)
    _, _, sout = ic.parse_data_chunk(sdc)
    check("stereo pcm length", sout == spcm)

    # 5. iter_chunks walks a multi-chunk payload
    payload = ws + dc
    types = [ctype for ctype, _ in ic.iter_chunks(payload)]
    check("iter_chunks finds both", types == [ic.CHUNK_WAVE_SETUP, ic.CHUNK_DATA])

    # 6. read_message framing over a fake socket
    msg = build_message(ic.MSG_DATA, dc)
    sock = FakeSock(msg + b"trailing-ignored")
    mtype, mpayload = ic.read_message(sock)
    check("read_message type", mtype == ic.MSG_DATA)
    check("read_message payload", mpayload == dc)

    # 7. read_message rejects bad sync
    bad = bytes([ic.MSG_DATA, 0x00, 0x00, 0x00])
    try:
        ic.read_message(FakeSock(bad))
        check("bad sync rejected", False)
    except ValueError:
        check("bad sync rejected", True)

    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
