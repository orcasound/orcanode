import ooipy
import os
import datetime
import shutil
import logging
import logging.handlers
import sys

LOGLEVEL = logging.DEBUG
PREFIX = os.environ["TIME_PREFIX"]
DELAY = os.environ["DELAY_SEGMENT"]
NODE = os.environ["NODE_NAME"]
ENV = os.environ["ENV"]
TEST_DATETIME_START = os.environ["TEST_DATETIME_START"]
TEST_DATETIME_END = os.environ["TEST_DATETIME_END"]
OOI_NODE = os.environ["OOI_NODE"]
#Comment

BASEPATH = os.path.join('/tmp', NODE)
PATH = os.path.join(BASEPATH, 'hls')
log = logging.getLogger(__name__)

log.setLevel(LOGLEVEL)

handler = logging.StreamHandler(sys.stdout)

formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
handler.setFormatter(formatter)

log.addHandler(handler)

def fetchData(start_time, segment_length, end_time, node):
    os.makedirs(BASEPATH, exist_ok=True)
    os.makedirs(PATH, exist_ok=True)
    while start_time < end_time:
        segment_end = min(start_time + segment_length, end_time)

        #paths and filenames
        datestr = start_time.strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
        sub_directory = start_time.strftime("%Y-%m-%d")
        file_path = os.path.join(PATH, sub_directory)
        wav_name = "{date}.wav".format(date=datestr)
        ts_name = "{prefix}{date}.ts".format(prefix=PREFIX, date=datestr) 

        #create directory and edit latest.txt
        if not os.path.exists(file_path):
            os.mkdir(file_path)
            manifest_file = os.path.join('/root', 'live.m3u8')           
            if os.path.exists(manifest_file):
                os.remove(manifest_file)
            if not os.path.exists(os.path.join(BASEPATH, 'latest.txt')):
                with open('latest.txt', 'x') as f:
                    f.write(sub_directory)
                    shutil.move('latest.txt', BASEPATH )
            else:
                with open(f'/{BASEPATH}/latest.txt', 'w') as f:
                    f.write(sub_directory)


        #fetch if file doesn't already exist
        if(os.path.exists(os.path.join(file_path, ts_name))):
            print("EXISTS")
            start_time = segment_end
            continue
        hydrophone_data = ooipy.request.hydrophone_request.get_acoustic_data(
            start_time, segment_end, node, verbose=True, data_gap_mode=2
        )
        if hydrophone_data is None:
            print(f"Could not get data from {start_time} to {segment_end}")
            start_time = segment_end
            continue
        print(f"data: {hydrophone_data}")
        hydrophone_data.wav_write(wav_name)   
        
        writeManifest(wav_name, ts_name) 

        #move files to tmp for upload
        shutil.move(os.path.join('/root', ts_name), os.path.join(file_path, ts_name))
        shutil.copy('/root/live.m3u8', os.path.join(file_path, 'live.m3u8'))
        os.remove(wav_name)
        start_time = segment_end


def writeManifest(wav_name, ts_name):
    root_path = os.path.join('/root', 'live.m3u8')
    if not os.path.exists(root_path):
        os.system("ffmpeg -i {wavfile} -f segment -segment_list 'live.m3u8' -strftime 1 -segment_time 300 -segment_format mpegts -ac 1 -acodec aac {tsfile}".format(wavfile=wav_name, tsfile=ts_name))
    else:
        os.system('ffmpeg -i {wavfile} -f mpegts -ar 64000 -acodec aac -ac 1 {tsfile}'.format(wavfile=wav_name, tsfile=ts_name))
        #remove EXT-X-ENDLIST and write new segment
        with open("live.m3u8", "r+") as f:
            lines = f.readlines()
            f.seek(0)
            f.truncate()
            f.writelines(lines[:-1])
            f.write("#EXTINF:300.000000, \n")
            f.write(f'{ts_name} \n')
            f.write(f'#EXT-X-ENDLIST \n')

        #os.system("ffmpeg -i {wavfile} -hls_playlist_type event -strftime 1 -hls_segment_type mpegts -ac 1 -acodec aac -hls_segment_filename {tsfile} -hls_time 1800 -hls_flags omit_endlist+append_list live.m3u8".format(wavfile=wav_name, tsfile=ts_name))      



def _main():

    segment_length = datetime.timedelta(minutes = 5)
    fixed_delay = datetime.timedelta(hours=8)

    if ENV == "live":
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(hours=8)

        #near live fetch
        fetchData(start_time, segment_length, end_time, 'PC01A')

        #delayed fetch
        fetchData(end_time-datetime.timedelta(hours=24), segment_length, end_time, 'PC01A')

        start_time, end_time = end_time, datetime.datetime.utcnow()
    
    elif ENV == "test":
        if(TEST_DATETIME_END != None):
            end_time = dateutil.parser.parse(TEST_DATETIME_END)
        else:
            end_time = end_time = datetime.datetime.utcnow()

        if(TEST_DATETIME_START != None):
            start_time = dateutil.parser.parse(TEST_DATETIME_START)
        else:
            start_time = end_time - datetime.timedelta(hours=8)
        
        #manual testing
        if(OOI_NODE != None):
            fetchData(start_time, segment_length, end_time, OOI_NODE)
        else:
            print("Please provide OOI Node Env Variable")
            

    else:
        print("Please provide a valid fetch environment: live or test.")




_main()
