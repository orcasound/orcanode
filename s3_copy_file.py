#!/usr/bin/env python3
from boto3.s3.transfer import S3Transfer
import boto3
import os
import sys
import logging
import logging.handlers

LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)

log.setLevel(LOGLEVEL)

handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)

log.addHandler(handler)

def internet(host="8.8.8.8", port=53, timeout=3):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    import socket
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception as ex:
        print (ex.message)
        return False


def timecheck():
    import subprocess
    if(internet()):
        foo = str(subprocess.check_output("timedatectl"))
        return("Network time on: yes" in foo)
    else:
        return False


def s3_copy_file(basepath, path, filename):
    BUCKET = 'dev-streaming-orcasound-net'
    REGION = 'us-west-2'
    log.debug('uploading file '+filename+' from '+path+' to bucket '+BUCKET)
    try:
        resource = boto3.resource('s3', REGION)   # Doesn't seem like we have to specify region
        
        # transfer = S3Transfer(client)
        uploadfile = os.path.join(path, filename)
        log.debug('upload file: ' + uploadfile)
        uploadpath = os.path.relpath(path, basepath)
        uploadkey = os.path.join(uploadpath, filename, )
        log.debug('upload key: ' + uploadkey)
        resource.meta.client.upload_file(uploadfile, BUCKET, uploadkey,
                                         ExtraArgs={'ACL': 'public-read'})  # TODO have to build filename into correct key.
        if("m3u8" not in filename):
            os.remove(path+'/'+filename)  # maybe not necessary since we write to /tmp and reboot every so often
    except:
        e = sys.exc_info()[0]
        log.critical('error uploading to S3: '+str(e))
        raise
