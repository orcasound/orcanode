#!/usr/bin/env python3
# Based on https://github.com/gergnz/s3autoloader/blob/master/s3autoloader.py
# Needs to replace this code 
# while true; do
#   inotifywait -r -e close_write,create /tmp/$NODE_NAME /tmp/flac/$NODE_NAME
#   echo "Running rsync on $NODE_NAME..."
#   nice -n -5 rsync -rtv /tmp/flac/$NODE_NAME /mnt/dev-archive-orcasound-net
#   nice -n -5 rsync -rtv /tmp/$NODE_NAME /mnt/dev-streaming-orcasound-net
# done
# #
#
#  Version 1 - just to hls
#  Version 2 - + flac
#
#
#

from boto3.s3.transfer import S3Transfer
import inotify.adapters
import logging
import logging.handlers
import boto3
import os
import sys

NODE = os.environ["NODE_NAME"]
BASEPATH = os.path.join("/tmp", NODE)
PATH = os.path.join(BASEPATH, "flac")
# Paths to watch is /tmp/NODE_NAME an /tmp/flac/NODE_NAME
# "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts"
# "/tmp/flac/$NODE_NAME"
# s3.Bucket(name='dev-archive-orcasound-net')  // flac
# s3.Bucket(name='dev-streaming-orcasound-net') // hls 


REGION = os.environ["REGION"]
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
        BUCKET = 'archive-orcasound-net'
    elif (os.environ["BUCKET_TYPE"] == "custom"):
        print("using custom bucket")
        BUCKET = os.environ["BUCKET_ARCHIVE"]
    else:
        print("using dev bucket")
        BUCKET = "dev-archive-orcasound-net"
        
    log.debug("archive bucket set to ", BUCKET)


def s3_copy_file(path, filename):
    log.debug('uploading file '+filename+' from '+path+' to bucket '+BUCKET)
    try:
        resource = boto3.resource('s3', REGION)   # Doesn't seem like we have to specify region
        # transfer = S3Transfer(client)
        uploadfile = os.path.join(path, filename)
        log.debug('upload file: ' + uploadfile)
        uploadpath = os.path.relpath(path, "/tmp")
        uploadkey = os.path.join(uploadpath, filename, )
        log.debug('upload key: ' + uploadkey)
        resource.meta.client.upload_file(uploadfile, BUCKET, uploadkey,
                                         ExtraArgs={'ACL': 'public-read'})  # TODO have to build filename into correct key.
        os.remove(path+'/'+filename)  # maybe not necessary since we write to /tmp and reboot every so often
    except:
        e = sys.exc_info()[0]
        log.critical('error uploading to S3: '+str(e))

def _main():
    #s3_copy_file(PATH, 'latest.txt')
    i = inotify.adapters.InotifyTree(PATH)
    # TODO we should ideally block block_duration_s on the watch about the rate at which we write files, maybe slightly less
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
    finally:
        log.debug('all done')

        
if __name__ == '__main__':
    _main()

