# Experimental: icListen live TCP ingest

**Status: EXPERIMENTAL — not yet tested against real hardware.** The parsing
logic is covered by offline unit tests, but the full path (device → client →
ffmpeg → HLS) has not been exercised end to end because no icListen has been
reachable from the node yet. Treat this as a prototype.

## What it is

`iclisten_stream.py` connects to an Ocean Sonics icListen hydrophone's
real-time waveform telemetry socket, decodes the sample data, and writes raw
interleaved PCM to stdout — ready to pipe into ffmpeg and on into the node's
existing HLS pipeline. This lets the node re-stream a hydrophone **live**

## Protocol summary

- **TCP** to the hydrophone on port **51678** (waveform stream).
- Client sends an 8-byte **Start-Stream** message, then reads framed messages.
- Each message: `[type][sync=0x2A][length: uint16 BE][payload]`.
- **Data** messages (`0x31`) carry a Data chunk (`0x42`) whose bytes from
  offset 12 are the interleaved PCM. A one-byte **Data Format** field gives the
  bit depth and endianness (device default: 24-bit little-endian → `s24le`).
- **Event Header** messages (`0x32`, ~once/second) carry a Wave Setup chunk
  (`0x45`) with the configured **sample rate** and format.
- **Notify** messages (`0x30`) report control/error conditions (e.g. "device
  busy logging", "no free connection").

Set the **sample rate and data format in the icListen web interface** before
streaming; the client logs the detected rate/format to stderr so you can match
the ffmpeg flags. The command/control channel (port 50000) is **not** used.

## Usage (intended)

```sh
python3 iclisten_stream.py "$ICLISTEN_HOST" \
  | ffmpeg -re -f "${ICLISTEN_FMT:-s24le}" -ar "$ICLISTEN_RATE" -ac "$CHANNELS" -i pipe:0 \
      ... (the node's usual HLS + local_hls outputs) ...
```

In the node this is wired as `NODE_TYPE=iclisten` in `stream.sh`, with
`ICLISTEN_HOST`, `ICLISTEN_RATE`, `ICLISTEN_FMT`, and `CHANNELS` set in `.env`.

## Important caveats

- **One stream connection per hydrophone.** The device allows a single live
  waveform client at a time. Onboard logging (and file retrieval) is
  independent and does **not** occupy this socket, so archival can continue —
  but a second live client (e.g. the vendor software actively streaming) will
  block us with Notify code 1/5.
- **Reachability.** The hydrophone must be reachable over IP from the node
  (routable address on a reachable subnet)

## Testing

```sh
python3 test_parse.py        # offline: synthetic frames, no hardware/network
```
