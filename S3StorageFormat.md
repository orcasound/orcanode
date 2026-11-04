# AWS S3 Storage Format

OrcaNode code publishes audio to AWS S3 buckets.  It is essential that publishers and
subscribers use a common contract for the storage formats, to prevent breaking clients.  
This document covers the layout of files that can be read by clients such as the
[orca-hls-utils](https://github.com/orcasound/orca-hls-utils) library.  

## Buckets

The primary audio bucket is called `audio-orcasound-net` and can be browsed
using the [Quilt audio-orcasound-net page](https://app.quilt.bio/b/audio-orcasound-net/tree/)
which supports anonymous access.

Dev nodes can use the `dev-streaming-orcasound-net` bucket which can be browsed using the
[Quilt dev-streaming-orcasound-net page](https://app.quilt.bio/b/dev-streaming-orcasound-net/tree/)
which supports anonymous access.

At least one dev node instead uses the `streaming-orcasound-net` bucket which can be browsed
using the [Quilt streaming-orcasound-net page](https://app.quilt.bio/b/streaming-orcasound-net/tree/)
which does NOT support anonymous access.

Each bucket contains a folder per hydrophone node. The folder name is the node's `NODE_NAME` value (normally `rpi_{node_name}`,
e.g., `rpi_andrews_bay`), with contents as specified in the [Node Folders section](#node-folders).

## Node folders

Each node folder contains the following:

1. a `latest.txt` text file containing the Unix timestamp (i.e., the number of seconds since 00:00:00 UTC
   on 1 January 1970) of the most recent time at which the orcanode code restarted.  Note: Unix timestamps
   can be converted to UTC or local time at https://www.epochconverter.com/

2. an `hls` folder, with contents as specified in the [HLS folders section](#hls-folders).

3. (optionally) a `flac` folder, with contents as specified in the [FLAC folders section](#flac-folders).

## HLS folders

Each `hls` folder contains a set of folders, each named using a Unix timestamp of a time
at which the orcanode code restarted, which we will refer to as a "restart time", which contents as
specified in the [Restart Time Folders section](#restart-time-folders).

## Restart time folders

Each restart time folder contains the following:

1. a `live.m3u8` text file containing a list of all audio files in the folder.  The format of the
   M3U8 file is specified in [RFC 8216](https://www.rfc-editor.org/info/rfc8216/).
   The M3U8 file will contain the basic tags (`EXTM3U`, `EXT-X-VERSION`) specified in
   [RFC 8216 section 4.3.1](https://www.rfc-editor.org/info/rfc8216/#section-4.3.1), but may also
   contain other basic tags.  The M3U8 file can also contain various media segment tags
   specified in [RFC 8216 section 4.3.2](https://www.rfc-editor.org/info/rfc8216/#section-4.3.2),
   where `EXTINF` is required, and `EXT-X-PROGRAM-DATE-TIME` is recommended but not required,
   and others may also appear.  The `EXT-X-VERSION` value must be 3 or higher.
   The URI of the M3U8 file is "https://{bucket}.s3.amazonaws.com/rpi_{node_name}/hls/{unixtimestamp}/live.m3u8".

2. a set of MPEG-2 Transport Stream (MPEG-TS) files named using the convention
   `live{number}.ts`, where {number} is an integer starting at 000 for the first file, and
   sequentially incrementing for each subsequent file. The integer is not limited to three digits,
   so live1000.ts follows live999.ts and live10000.ts follows live9999.ts for example.
   [RFC 8216 section 3.2](https://www.rfc-editor.org/info/rfc8216/#section-3.2) describes the
   constraints and requirements for MPEG-TS segments used in HLS.  Such TS files in this folder
   are typically around 10 seconds long, but may be shorter or longer.  The associated `EXTINF`
   tag in the M3U8 file gives the audio file's duration with millisecond granularity.
   The URI of an audio file is "https://{bucket}.s3.amazonaws.com/rpi_{node_name}/hls/{unixtimestamp}/live{index}.ts".

Note: it is important that the M3U8 file contain all audio files in the folder, since various
clients rely on this to provide uninterrupted playback of stored audio (e.g., within a bout).
A current issue is that if a bout spans restarts, this requirement will not be met and playback
of the entire bout may fail.

## FLAC folders

Each `flac` folder, if present, contains a set of Free Lossless Audio Codec (FLAC) files named
using the convention "YYYY-MM-DD_HH-MM-SS_rpi_{node_name}-{samplerate}-{channels}.flac" (e.g.,
"2024-11-13_22-31-08_rpi_port_townsend-48000-1.flac").  The format of each file is as specified
in [RFC 9639](https://www.rfc-editor.org/info/rfc9639/).
