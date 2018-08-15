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

from threading import Thread
from boto3.s3.transfer import S3Transfer
import inotify.adapters
import logging
import logging.handlers
import boto3
import os
import sys

NODE = os.environ["NODE_NAME"]
# Paths to watch is /tmp/NODE_NAME an /tmp/flac/NODE_NAME
PATH = 

# "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts"
# "/tmp/flac/$NODE_NAME"
# s3.Bucket(name='dev-archive-orcasound-net')  // flac
# s3.Bucket(name='dev-streaming-orcasound-net') // hls 

BUCKET = 'dev-streaming-orcasound-net'
REGION = 'us-west-2'
LOGLEVEL = logging.DEBUG

# def _main():
#     #i = inotify.adapters.Inotify()

#     #i.add_watch('/tmp')
#     i = inotify.adapters.InotifyTree('/tmp/rpi_steve_test')

#     #with open('/tmp/test_file', 'w'):
#     #    pass

#     for event in i.event_gen(yield_nones=False):
#         (_, type_names, path, filename) = event

#         print("PATH=[{}] FILENAME=[{}] EVENT_TYPES={}".format(
#               path, filename, type_names))

log = logging.getLogger(__name__)

log.setLevel(LOGLEVEL)

handler = logging.handlers.SysLogHandler(address = '/dev/log')

formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)

log.addHandler(handler)

def s3_copy_file(filename):
    log.debug('uploading file '+filename+' from '+PATH+' to bucket '+BUCKET)
    try:
        client = boto3.client('s3', REGION)   # Doesn't seem like we have to specify region
        transfer = S3Transfer(client)
        transfer.upload_file(PATH+'/'+filename, BUCKET, filename)  # TODO have to build filename into correct key.
    #    os.remove(PATH+'/'+filename)  maybe not necessary since we write to /tmp and reboot every so often
    except:
        e = sys.exc_info()[0]
        log.critical('error uploading to S3: '+str(e))

def do_something():
    i = inotify.adapters.Inotify()
    i.add_watch(str.encode(PATH))  #TODO we want recursive watch i = inotify.adapters.InotifyTree('/tmp/rpi_steve_test')???
    # TODO we should ideally block block_duration_s on the watch about the rate at which we write files, maybe slightly less
    try:
        for event in i.event_gen():   # for event in i.event_gen(yield_nones=False):
            if event is not None:
                (header, type_names, watch_path, filename) = event
                if type_names[0] == 'IN_CLOSE_WRITE':
                    log.debug('Recieved a new file '+bytes.decode(filename))
                    #
                    # todo get rid of threads
                    # todo pass both filename (for orignal path + file name to read
                    # plus the s3 key combination create from "watch_path" with /tmp removed from front
                    #
                    
                    z = Thread(target=s3_copy_file, args=(bytes.decode(filename),))
                    z.start()
    finally:
        i.remove_watch(str.encode(PATH))

        
if __name__ == '__main__':
    _main()
#    pid=PID
#    daemon = Daemonize(app="s3autoloader", pid=pid, action=do_something)
#    daemon.start()

