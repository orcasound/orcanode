import ooipy
import os
import datetime
import shutil
import logging
import logging.handlers
import sys


LOGLEVEL = logging.DEBUG
NODE = os.environ["NODE_NAME"]
BASEPATH = os.path.join('/tmp', NODE)
PATH = os.path.join(BASEPATH, 'hls')

ffmpeg_cmd = "ffmpeg -i files.txt -flush_packets 0 -f segment -segment_list '/tmp/$NODE_NAME/hls/$timestamp/live.m3u8' -segment_list_flags -segment_time 10 -segment_format mpegts -ar 64000 -ac 1 -acodec aac '/tmp/$NODE_NAME/hls/$timestamp/live%03d.ts'"

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
        hydrophone_data = ooipy.request.hydrophone_request.get_acoustic_data(
            start_time, segment_end, node, verbose=True, data_gap_mode=2
        )
        if hydrophone_data is None:
            print(f"Could not get data from {start_time} to {segment_end}")
            start_time = segment_end
            continue
        print(f"data: {hydrophone_data}")
        datestr = start_time.strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
        sub_directory = start_time.strftime("%Y-%m-%d")
        file_path = os.path.join(PATH, sub_directory)
        wav_name = f"{datestr}.wav"
        hydrophone_data.wav_write(wav_name)   
        ts_name = f"{datestr}.ts"
        #os.system('ffmpeg -i {wavfile} -f mpegts -ar 64000 -acodec aac -ac 1 {tsfile}'.format(wavfile=wav_name, tsfile=ts_name))
        #os.system("ffmpeg -f concat -safe 0 -i files.txt -flush_packets 0 -f segment -segment_list '/tmp/$NODE/hls/$sub_directory/live.m3u8'")
        os.system("ffmpeg -i {wavfile} -f segment -segment_list './live.m3u8' -strftime 1 -segment_time 10 -segment_format mpegts -ac 1 -acodec aac {tsfile}".format(wavfile=wav_name, tsfile=ts_name))
        if not os.path.exists(file_path):
           os.makedirs(file_path)
        shutil.move(ts_name, file_path)
        if not os.path.exists(os.path.join(file_path, 'live.m3u8')):
            shutil.move('/root/live.m3u8', file_path)
        shutil.copy('/root/live.m3u8', file_path)
        os.remove(wav_name)
        start_time = segment_end

def _main():

    start_time = datetime.datetime(2021, 4, 27)
    end_time = datetime.datetime(2022, 4, 30)
    segment_length = datetime.timedelta(seconds = 10)

    fetchData(start_time, segment_length, end_time, 'PC01A')


_main()
