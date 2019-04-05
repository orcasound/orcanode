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

import inotify.adapters
import logging
import logging.handlers
import os
import sys
from redis import Redis
from rq import Queue
from s3_copy_file import s3_copy_file

NODE = os.environ["NODE_NAME"]
BASEPATH = "/audio"
PATH = os.path.join(BASEPATH, NODE)
# Paths to watch is /tmp/NODE_NAME an /tmp/flac/NODE_NAME
# "/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts"
# "/tmp/flac/$NODE_NAME"
# s3.Bucket(name='dev-archive-orcasound-net')  // flac
# s3.Bucket(name='dev-streaming-orcasound-net') // hls 

LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)

log.setLevel(LOGLEVEL)

handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)

log.addHandler(handler)

        
s3_copy_file(BASEPATH, PATH, 'latest.txt')
conn = Redis(host='redis', port=6379)
q = Queue("high", connection=conn, default_timeout=600)
i = inotify.adapters.InotifyTree(BASEPATH)
try:
    for event in i.event_gen(yield_nones=False):
        (header, type_names, path, filename) = event
        if type_names[0] == 'IN_CLOSE_WRITE':
            if 'tmp' not in filename:
                log.debug('Recieved a new file ' + filename)
                q.enqueue_call(
                        func=s3_copy_file, args=(BASEPATH, path, filename))
        if type_names[0] == 'IN_MOVED_TO':
            log.debug('Recieved a new file ' + filename)
            q.enqueue_call(
                    func=s3_copy_file, args=(BASEPATH, path, filename))
finally:
    log.debug('all done')

