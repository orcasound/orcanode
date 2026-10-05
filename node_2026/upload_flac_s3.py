#!/usr/bin/env python3
# Based on https://github.com/gergnz/s3autoloader/blob/master/s3autoloader.py
# FLAC counterpart to upload_s3.py: watches /tmp/$NODE_NAME/flac for finished
# FLAC segments written by ffmpeg (NODE_TYPE=research) and uploads them to the
# archive bucket under the key $NODE_NAME/flac/<filename>.

import inotify.adapters
import logging
import logging.handlers
import boto3
import os
import sys

from logdna_handler import attach_logdna_handler

NODE = os.environ["NODE_NAME"]
BASEPATH = os.path.join("/tmp", NODE)
PATH = os.path.join(BASEPATH, "flac")

LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)
log.setLevel(LOGLEVEL)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)
attach_logdna_handler(log, NODE, app="upload_flac_s3")

BUCKET = ""
if "BUCKET_TYPE" in os.environ:
    if(os.environ["BUCKET_TYPE"] == "prod"):
        print("using production bucket")
        BUCKET = 'archive-orcasound-net'
    elif (os.environ["BUCKET_TYPE"] == "custom"):
        print("using custom bucket")
        BUCKET = os.environ["BUCKET_ARCHIVE"]
    else:
        BUCKET = "dev-archive-orcasound-net"

    log.debug("flac bucket set to "+BUCKET)


def s3_copy_file(path, filename):
    uploadfile = os.path.join(path, filename)

    # Check file size first
    try:
        filesize = os.path.getsize(uploadfile)
    except FileNotFoundError:
        log.warning(f'SKIPPING {filename}: file no longer exists')
        return
    if filesize == 0:
        log.warning(f'SKIPPING empty file: {filename}')
        return

    log.debug(f'file {filename} size: {filesize} bytes')
    log.debug('uploading file '+filename+' from '+path+' to bucket '+BUCKET)
    try:
        resource = boto3.resource('s3')
        uploadpath = os.path.relpath(path, "/tmp")
        uploadkey = os.path.join(uploadpath, filename)
        log.debug('upload key: ' + uploadkey)
        try:
            resource.meta.client.upload_file(uploadfile, BUCKET, uploadkey,
                                             ExtraArgs={'ContentType': 'audio/flac'})
        except Exception as e:
            log.critical('error uploading to S3: ' + str(e))
            return

        try:
            os.remove(uploadfile)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning('error removing local file: ' + str(e))
    except:
        e = sys.exc_info()[0]
        log.critical('error uploading to S3: '+str(e))


def _main():
    i = inotify.adapters.InotifyTree(PATH)
    try:
        for event in i.event_gen(yield_nones=False):
            (header, type_names, path, filename) = event
            if not filename.endswith('.flac'):
                continue
            # ffmpeg's segment muxer writes each FLAC file in place, so
            # IN_CLOSE_WRITE fires once the segment (and its STREAMINFO
            # header, rewritten at close) is complete.
            if type_names[0] in ('IN_CLOSE_WRITE', 'IN_MOVED_TO'):
                log.debug('Recieved a new file ' + filename)
                s3_copy_file(path, filename)
    finally:
        log.debug('all done')


if __name__ == '__main__':
    _main()
