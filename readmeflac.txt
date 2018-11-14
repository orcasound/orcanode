* Build notes ffmpeg with Jack
sudo apt remove ffmpeg
 git clone git://source.ffmpeg.org/ffmpeg.git ffmpeg;
 cd ffmpeg/
 sudo apt-get update
 sudo apt-get install libomxil-bellagio-dev
 sudo apt-get install libjack-dev
 ./configure --arch=armel --target-os=linux --enable-gpl --enable-omx --enable-omx-rpi --enable-nonfree --enable-mmal --enable-libjack
make -j4
sudo make install 
* Installing Jack
 wget -O - http://rpi.autostatic.com/autostatic.gpg.key| sudo apt-key add -
 sudo wget -O /etc/apt/sources.list.d/autostatic-audio-raspbian.list http://rpi.autostatic.com/autostatic-audio-raspbian.list
 sudo apt-get update
 sudo apt-get --no-install-recommends install jackd1 jack-capture
* Patching Jack 
To get 192 to work at all I had to patch jack.c in ffmpeg
/ffmpeg/libavdevice/jack.c
    *** changed from 100000 + 2 to 100000 + 3 as indicated below 
    /* Wait for a packet coming back from process_callback(), if one isn't available yet */
    timeout.tv_sec = av_gettime() / 1000000 + 3;
    if (sem_timedwait(&self->packet_count, &timeout)) {
        if (errno == ETIMEDOUT) {
            av_log(context, AV_LOG_ERROR,
                   "Input error: timed out when waiting for JACK process callback output\n");
        } else {

* Notes on testing
Setup jack 

  41  echo @audio - memlock 256000 >> /etc/security/limits.conf
  42  echo @audio - rtprio 75 >> /etc/security/limits.co
  43  JACK_NO_AUDIO_RESERVATION=1 jackd -t 2000 -P 75 -d alsa -d hw:pisound -r 192000 -p 1024 -n 10 -s

the rest below should be done by stream.sh

Capture flac using jack

jack_capture -p system:capture* -f flac

wav file using ffmpeg 

sudo ffmpeg -f jack -i ffmpeg -y out.wav

sudo ffmpeg -f jack -i ffjack \
       -f segment -segment_time "00:00:30.00" -strftime 1 "/tmp/rpi_steve_test/%Y-%m-%d_%H-%M-%S_rpi_test-2.flac" \
       -f segment -segment_list "/tmp/rpi_test/live.m3u8" -segment_list_flags +live -segment_time 10 -segment_format \
       mpegts -ar 48000 -ac 2 -acodec aac "/tmp/rpi_test/live%03d.ts" &

sudo jack_connect system:capture_1 ffjack:input_1
sudo jack_connect system:capture_2 ffjack:input_2
