#!/usr/bin/env python3
# Based on https://github.com/gergnz/s3autoloader/blob/master/s3autoloader.py

from boto3.s3.transfer import S3Transfer
import inotify.adapters
import logging
import logging.handlers
import boto3
import numpy as np
import subprocess
import os
import shutil
import sys
import time

from logdna_handler import attach_logdna_handler

NODE = os.environ["NODE_NAME"]
BASEPATH = os.path.join("/tmp", NODE)
PATH = os.path.join(BASEPATH, "hls")
# Full-day archive manifests are kept here, outside the inotify-watched
# hls tree, and uploaded next to live.m3u8 as archive.m3u8.
ARCHIVE_PATH = os.path.join(BASEPATH, "archive")
LIVE_MANIFEST = "live.m3u8"
ARCHIVE_MANIFEST = "archive.m3u8"
# Playlists and latest.txt change in place, so browsers must revalidate
# them; without a Cache-Control header they cache them heuristically and
# a listener can keep requesting an old session. .ts segments never change.
NO_CACHE = {'CacheControl': 'no-cache'}

SEGMENT_DURATION = int(os.environ.get("SEGMENT_DURATION", "10").strip())
# On a slow link this single-threaded loop can fall behind ffmpeg. A .ts
# older than this when its event is handled is left on disk for
# catchup_s3.py, so the uploader skips ahead to the live edge.
LIVE_LAG_LIMIT = SEGMENT_DURATION * 3
# archive.m3u8 grows with every segment for the whole session, so it is
# uploaded at most this often rather than once per segment.
ARCHIVE_UPLOAD_INTERVAL = 300

# REGION = os.environ["REGION"]
LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)
log.setLevel(LOGLEVEL)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)
attach_logdna_handler(log, NODE, app="upload_s3")

BUCKET = ""
if "BUCKET_TYPE" in os.environ:
    if(os.environ["BUCKET_TYPE"] == "prod"):
        print("using production bucket")
        BUCKET = 'audio-orcasound-net'
    elif (os.environ["BUCKET_TYPE"] == "custom"):
        print("using custom bucket")
        BUCKET = os.environ["BUCKET_STREAMING"]
    else:
        BUCKET = "dev-streaming-orcasound-net"

    log.debug("hls bucket set to "+BUCKET)


def compute_rms(filepath):
    """Decode audio from a .ts file using ffmpeg and compute RMS level."""
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-i', filepath,
                '-ac', '1',          # mix to mono for single RMS value
                '-ar', '48000',      # consistent sample rate
                '-f', 's16le',       # raw signed 16-bit little-endian PCM
                '-'                  # output to stdout
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # suppress ffmpeg's own output
            timeout=10
        )
        if len(result.stdout) == 0:
            log.warning(f'ffmpeg produced no audio output for {filepath}')
            return None
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(samples ** 2))
        return rms
    except subprocess.TimeoutExpired:
        log.warning(f'ffmpeg timed out decoding {filepath}')
        return None
    except Exception as e:
        log.warning(f'RMS computation failed for {filepath}: {e}')
        return None


def s3_copy_file(path, filename):
    uploadfile = os.path.join(path, filename)

    # Check file size first
    try:
        filesize = os.path.getsize(uploadfile)
    except FileNotFoundError:
        log.warning(f'SKIPPING {filename}: file already rotated by ffmpeg')
        return
    if filesize == 0:
        log.warning(f'SKIPPING empty file: {filename}')
        return

    # Compute and log RMS for .ts segment files
    if filename.endswith('.ts'):
        rms = compute_rms(uploadfile)
        if rms is not None:
            log.debug(f'file {filename} size: {filesize} bytes  RMS: {rms:.1f}')
            if rms < 1.0:
                log.warning(f'Very low RMS ({rms:.2f}) in {filename} - possible silence or bad capture')
        else:
            log.debug(f'file {filename} size: {filesize} bytes  RMS: could not compute')
    else:
        log.debug(f'file {filename} size: {filesize} bytes')

    log.debug('uploading file '+filename+' from '+path+' to bucket '+BUCKET)
    log.debug(f'AWS_ACCESS_KEY_ID present: {"AWS_ACCESS_KEY_ID" in os.environ}')
    log.debug(f'AWS_SECRET_ACCESS_KEY present: {"AWS_SECRET_ACCESS_KEY" in os.environ}')
    try:
        resource = boto3.resource('s3')
        uploadpath = os.path.relpath(path, "/tmp")
        uploadkey = os.path.join(uploadpath, filename)
        log.debug('upload key: ' + uploadkey)
        try:
            extra_args = None
            if filename.endswith('.m3u8') or filename == 'latest.txt':
                extra_args = NO_CACHE
            resource.meta.client.upload_file(uploadfile, BUCKET, uploadkey,
                                             ExtraArgs=extra_args)
        except Exception as e:
            log.critical('error uploading to S3: ' + str(e))
            return

        try:
            os.remove(os.path.join(path, filename))
        except FileNotFoundError:
            pass  # ffmpeg may have already replaced or rotated the file
        except Exception as e:
            log.warning('error removing local file: ' + str(e))
    except:
        e = sys.exc_info()[0]
        log.critical('error uploading to S3: '+str(e))


def parse_manifest(text):
    """Split an HLS playlist into (header tags, segments).

    Each segment is (uri, [tag lines before it]). EXT-X-ENDLIST is dropped.
    """
    header = []
    segments = []
    pending = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line == '#EXT-X-ENDLIST':
            continue
        if line.startswith(('#EXTINF', '#EXT-X-PROGRAM-DATE-TIME',
                            '#EXT-X-DISCONTINUITY')):
            pending.append(line)
        elif line.startswith('#'):
            if not segments and not pending:
                header.append(line)
        else:
            segments.append((line, pending))
            pending = []
    return header, segments


def header_value(header, tag, default):
    for line in header:
        if line.startswith(tag + ':'):
            return line.split(':', 1)[1]
    return default


class ArchiveManifest:
    """Full-day manifest for one timestamp directory, built by merging every
    rolling live.m3u8 ffmpeg writes. Persisted locally so an uploader restart
    does not lose the segments that already left the live window."""

    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.local_path = os.path.join(ARCHIVE_PATH, timestamp, ARCHIVE_MANIFEST)
        self.version = '3'
        self.target_duration = 0
        self.media_sequence = None
        self.segments = []
        self.seen = set()
        self.last_upload = 0.0
        if os.path.exists(self.local_path):
            with open(self.local_path) as f:
                header, segments = parse_manifest(f.read())
            self.version = header_value(header, '#EXT-X-VERSION', self.version)
            self.target_duration = int(header_value(header, '#EXT-X-TARGETDURATION', '0'))
            self.media_sequence = int(header_value(header, '#EXT-X-MEDIA-SEQUENCE', '0'))
            self.segments = segments
            self.seen = {uri for uri, _ in segments}

    def merge(self, live_text):
        """Append segments from live_text not seen yet; return count added."""
        header, segments = parse_manifest(live_text)
        self.version = header_value(header, '#EXT-X-VERSION', self.version)
        self.target_duration = max(
            self.target_duration,
            int(header_value(header, '#EXT-X-TARGETDURATION', '0')))
        live_seq = int(header_value(header, '#EXT-X-MEDIA-SEQUENCE', '0'))
        added = 0
        for i, (uri, tags) in enumerate(segments):
            if uri in self.seen:
                continue
            if self.media_sequence is None:
                self.media_sequence = live_seq + i
            self.segments.append((uri, tags))
            self.seen.add(uri)
            added += 1
        return added

    def write(self):
        os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
        lines = ['#EXTM3U',
                 f'#EXT-X-VERSION:{self.version}',
                 f'#EXT-X-TARGETDURATION:{self.target_duration}',
                 f'#EXT-X-MEDIA-SEQUENCE:{self.media_sequence or 0}']
        for uri, tags in self.segments:
            lines.extend(tags)
            lines.append(uri)
        tmp = self.local_path + '.tmp'
        with open(tmp, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(tmp, self.local_path)

    def upload(self):
        """Upload the local archive manifest; keep the local copy. Return True on success."""
        key = os.path.join(NODE, 'hls', self.timestamp, ARCHIVE_MANIFEST)
        try:
            boto3.resource('s3').meta.client.upload_file(
                self.local_path, BUCKET, key,
                ExtraArgs={'ContentType': 'application/x-mpegurl', **NO_CACHE})
            log.debug(f'uploaded {key} ({len(self.segments)} segments)')
            return True
        except Exception as e:
            log.critical(f'error uploading {key} to S3: {e}')
            return False


def flush_old_archives():
    """Upload and remove archive manifests left from earlier sessions.

    A session's last archive upload can fail if the network was down when
    the container restarted, so retry it here before discarding the copy.
    """
    try:
        with open(os.path.join(BASEPATH, 'latest.txt')) as f:
            current = f.read().strip()
    except FileNotFoundError:
        current = None
    if not os.path.isdir(ARCHIVE_PATH):
        return
    for timestamp in sorted(os.listdir(ARCHIVE_PATH)):
        if timestamp == current:
            continue
        archive = ArchiveManifest(timestamp)
        if not os.path.exists(archive.local_path) or archive.upload():
            shutil.rmtree(os.path.join(ARCHIVE_PATH, timestamp), ignore_errors=True)


archives = {}


def update_archive(path):
    """Merge the just-written live.m3u8 in path into that session's archive."""
    try:
        with open(os.path.join(path, LIVE_MANIFEST)) as f:
            live_text = f.read()
    except FileNotFoundError:
        return
    timestamp = os.path.basename(path)
    archive = archives.get(timestamp)
    if archive is None:
        archive = archives[timestamp] = ArchiveManifest(timestamp)
    if archive.merge(live_text):
        archive.write()
        # The local copy is always current; S3 lags by at most
        # ARCHIVE_UPLOAD_INTERVAL, and flush_old_archives() sends the
        # final version after a restart.
        now = time.monotonic()
        if now - archive.last_upload >= ARCHIVE_UPLOAD_INTERVAL:
            if archive.upload():
                archive.last_upload = now


def is_stale_segment(path, filename):
    """True if a .ts event is handled too long after ffmpeg closed the file."""
    if not filename.endswith('.ts'):
        return False
    try:
        age = time.time() - os.path.getmtime(os.path.join(path, filename))
    except FileNotFoundError:
        return False  # s3_copy_file logs and skips it
    if age > LIVE_LAG_LIMIT:
        log.warning(f'Uploader {age:.0f}s behind, leaving {filename} for catchup')
        return True
    return False


def _main():
    flush_old_archives()
    # latest.txt is uploaded after the first manifest, not at startup.
    # This ensures the player can find segments when it reads the timestamp.
    latest_txt_uploaded = False
    i = inotify.adapters.InotifyTree(PATH)
    try:
        for event in i.event_gen(yield_nones=False):
            (header, type_names, path, filename) = event
            if type_names[0] == 'IN_CLOSE_WRITE':
                if 'tmp' not in filename:
                    log.debug('Recieved a new file ' + filename)
                    if not is_stale_segment(path, filename):
                        s3_copy_file(path, filename)
            if type_names[0] == 'IN_MOVED_TO':
                    log.debug('Recieved a new file ' + filename)
                    # Read live.m3u8 before s3_copy_file removes it.
                    if filename == LIVE_MANIFEST:
                        update_archive(path)
                    s3_copy_file(path, filename)
            if not latest_txt_uploaded and filename.endswith('.ts'):
                log.debug('First segment uploaded — now publishing latest.txt')
                s3_copy_file(BASEPATH, 'latest.txt')
                latest_txt_uploaded = True
    finally:
        log.debug('all done')


if __name__ == '__main__':
    _main()
