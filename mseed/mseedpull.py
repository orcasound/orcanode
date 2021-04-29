# OOI Conversion script for continious streaming audio
# The OOI website doesn't live post so this script continually
# looks for old files (based on delay) and then converts them
# to WAV files, which could then be posted to Orcasound website
# via FFMPEG and other scripts
#
# The code below is based on some code from Val Veirs,
# Elijah Blaisdell, Scott Veirs and Valentina Staneva from Democracy Lab
# Hackathon, Jan 9, 2021.
#
#
#
"""
!wget 'https://rawdata.oceanobservatories.org/files/RS01SBPS/PC01A/08-HYDBBA103/2021/01/09/OO-HYVM2--YDH-2021-01-09T00:15:00.000015.mseed'
"""

from obspy import read
import requests
from html.parser import HTMLParser
import time
from datetime import datetime, timedelta
import os
import shutil
import dateutil.parser
import logging
import logging.handlers
import sys

DELAY = int(os.environ["STREAM_DELAY"])
# DELAY = 6.5
SEGMENT = int(os.environ["DELAY_SEGMENT"]) # maybe change to "buffer"
# SEGMENT = 1
# TODO Should put this in env variable
#BASE_URL = os.environ["BASE_URL"]
BASE_URL = 'https://rawdata.oceanobservatories.org/files/RS01SBPS/PC01A/08-HYDBBA103/'

# Format of date in filename is ISO 8601 extended format
# To parse the start time of the file 
# import dateutil.parser
# >>> dateutil.parser.isoparse('2021-01-09T00:15:00.000015')
# datetime.datetime(2021, 1, 9, 0, 15, 0, 15)
TIME_PREFIX = os.environ['TIME_PREFIX']
TIME_POSTFIX = os.environ['TIME_POSTFIX']
LOGLEVEL = logging.DEBUG

log = logging.getLogger(__name__)

log.setLevel(LOGLEVEL)

handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)

log.addHandler(handler)

filesdone = []  # files that have already been converted


def getFileTime(filestring, prefix=TIME_PREFIX, postfix=TIME_POSTFIX):
        y = filestring.replace(prefix, '')
        z = y.replace(postfix, '')
        return(dateutil.parser.isoparse(z))


def getFileUrls():
    class MyHTMLParser(HTMLParser):
        def _init_(self, url):
            self.url = url

        def handle_data(self, data):
            if 'HYVM2' in data:
                datetimestr = getFileTime(data)
                filelist.append({'datetime': datetimestr, 'url': url, 'filepath': data})
    dates = []
    filelist = []
    now = datetime.utcnow()
    # TODO This only deals with a delay of 24 hours.  To generalize we need to 
    # divide delta by 24 to figure how the maximum number of days.
    datestr = (now - timedelta(hours=DELAY)).strftime('%Y/%m/%d')
    datenowstr = (now).strftime('%Y/%m/%d')
    dates.append(datestr)
    if (datestr != datenowstr):
        dates.append(datenowstr)
    for datestr in dates:
        url = BASE_URL + '{}'.format(datestr)
        r = requests.get(url)
        if r == 'Response [404]':
                # Day folder does not exist yet or website down
            print("website not responding or file not posted")
        parser = MyHTMLParser()
        parser.feed(str(r.content))
    return filelist


def fetchAndConvert(files):
    convertedfiles = []
    toconvert = 0
    now = datetime.utcnow()
    maxdelay = timedelta(hours=DELAY)
    #    mindelay = maxdelay - timedelta(hours=SEGMENT)
    mindelay = maxdelay - timedelta(minutes=10)
    for file in files:
        filepath = file['filepath']
        filetime = file['datetime']
        filedelay = now - filetime
        if filepath not in filesdone:
            if (filedelay < maxdelay and filedelay > mindelay):
                toconvert += 1
    log.debug(f'files to convert: {toconvert}')
    for file in files:
        filetime = file['datetime']
        url = file['url']
        filepath = file['filepath']
        filedelay = now - filetime
        if filepath not in filesdone:
            full_url = f'{url}/{filepath}'
            if (filedelay < maxdelay and filedelay > mindelay):
                # reading from url
                hydro = read(full_url)  # load file into obspy object
                log.debug('read url')
                file['duration'] = hydro[0].meta['endtime'] - hydro[0].meta['starttime']
                # increasing amplitude
                hydro[0].data = hydro[0].data * 1e4
                sampling_rate = hydro[0].meta['sampling_rate']
                # writing to wav file
                wavfilename = (filepath[:-12]+'wav').replace(':', '-')  # TODO Could be tmp filename
                tsname = (filepath[:-12]+'ts').replace(':', '-')
                hydro.write(wavfilename, framerate=sampling_rate, format='WAV')
                log.debug('converted wav')
                # TODO fix this -ar to actually use sampling_rate
                if os.path.exists(tsname):
                        os.remove(tsname)
                os.system('ffmpeg -i {filename} -f mpegts -ar 64000 -acodec aac -ac 1 {tsfilename}'.format(filename=wavfilename, tsfilename=tsname))
                log.debug('made mpegts')
                if os.path.exists(wavfilename):
                        os.remove(wavfilename)
                file['samplerate'] = sampling_rate
                file['tsfilename'] = tsname
                filesdone.append(filepath)
                convertedfiles.append(file)
                toconvert -= 1
                log.debug(f'files to convert: {toconvert}')
    return(convertedfiles)

def queueFiles(files):
    delay = timedelta(hours=DELAY)
    now = datetime.utcnow()
    played = 0
    deleted = 0
    for idx, entry in enumerate(files):
        duration = timedelta(seconds=entry['duration'])
        age = now - entry['datetime']
        tsfilename = entry['tsfilename']
        filepath = entry['filepath']
        if (delay + duration < age):  # in the past
            log.debug('deleting old entry: ' + tsfilename)
            if os.path.exists(tsfilename):
                    os.remove(tsfilename)
            filesdone.remove(filepath)
            del files[idx]
            deleted += 1
        if ((delay + duration >= age) and (age > delay)):
                # should be playing next
            log.debug('playing : ' + tsfilename)
            if os.path.exists(tsfilename):
                    shutil.move(tsfilename, '/root/data/dummy.ts')
            played += 1
            filesdone.remove(filepath)
            del files[idx]
            deleted += 1
    return(played, deleted, files)


def main_loop():
    starttime = time.time()
    convertedfiles = []
    files = []
    while True:
        # TODO this converts correctly but after queue files it
        # get overwritten by fetchandconver
        # you need to change it fetchandconvert appends the exisitng list
        # and all timedate stamps are only converted once at most.    
        log.debug("checking")
        files = getFileUrls()
        log.debug(f'number of URLS: {len(files)}')
        convertedfiles.extend(fetchAndConvert(files))
        log.debug(f'number of converted files: {len(files)}')
        played, deleted, convertedfiles = queueFiles(convertedfiles)
        log.debug(f'played: {played}, deleted: {deleted}')
        time.sleep(150.0 - ((time.time() - starttime) % 150.0))


main_loop()

# todo - try encoding first to aac .ts and then stream looping
# ffmpeg -i dummy.wav -f mpegts -acodec aac dummy.ts

# splitting into 10 second .ts files 

# os.system('ffmpeg -i {filename} -f segment -segment_list "live.m3u8" -segment_time 10 -segment_format mpegts -ar 48000 -ac 2 -acodec aac "live/live%03d.ts"'.format(filename=wavfilename))
# To encode hls forever
#
# ffmpeg -re -stream_loop -1 -i list.txt -f segment -segment_list \
#        "./tmp/live.m3u8" -segment_list_flags +live -segment_time 10 \
#         -segment_format mpegts -ar 64000 -ac 2 -threads 3 -acodec aac \
#        "./tmp/live%03d.ts"

# list.txt contents below
#
# ffconcat version 1.0
# file 'dummy.wav'
# file 'list.txt'
#
#












