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
import sys

NODE = os.environ["NODE_NAME"]
BASEPATH = os.path.join("/tmp", NODE)
PATH = os.path.join(BASEPATH, "hls")

# REGION = os.environ["REGION"]
LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)
log.setLevel(LOGLEVEL)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

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
            resource.meta.client.upload_file(uploadfile, BUCKET, uploadkey)
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


def _main():
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
                    s3_copy_file(path, filename)
            if type_names[0] == 'IN_MOVED_TO':
                    log.debug('Recieved a new file ' + filename)
                    s3_copy_file(path, filename)
            if not latest_txt_uploaded and filename.endswith('.ts'):
                log.debug('First segment uploaded — now publishing latest.txt')
                s3_copy_file(BASEPATH, 'latest.txt')
                latest_txt_uploaded = True
    finally:
        log.debug('all done')


if __name__ == '__main__':
    _main()
