# Orcasound's orcastream

This software contains audio tools and scripts for capturing, reformatting, transcoding and uploading audio for Orcasound.  There is a base set of tools and a couple of specific projects, orcanode and orcamseed.  Orcanode is streaming using Intel (amd64) or Raspberry Pi (arm32v7) platforms using a soundcard.  While any soundcard should work, the most common one in use is the pisound board on either a Raspberry Pi 3B+ or 4.  The other project orcamseed is for converting mseed format data to be streamed on Orcanode.  This is mainly used for the [OOI](https://oceanobservatories.org/ "OOI") network.  See the README in each of those directories for more info.

## Background & motivation

This code was developed for source nodes on the [Orcasound](http://orcasound.net) hydrophone network (WA, USA) -- thus the repository names! Our primary motivation is to make it easy for lots of folks to listen for whales using their favorite device/OS/browser. 

We also aspire to use open-source software as much as possible. A long-term goal is to stream lossless FLAC-encoded data within DASH segments to a player that works optimally on as many listening devices as possible.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

If you want to set up your hardware to host a hydrophone within the Orcasound network, take a look at [how to join Orcasound](http://www.orcasound.net/join/) and [our prototype built from a Raspberry Pi3b with the Pisound Hat](http://www.orcasound.net/2018/04/27/orcasounds-new-live-audio-solution-from-hydrophone-to-headphone-with-a-raspberry-pi-computer-and-hls-dash-streaming-software/).

Audio data is acquired within a Docker container by ALSA/FFmpeg, written to /tmp directories, transferred to /mnt directories by rsync, and transferred to AWS S3 buckets by s3fs. Errors/etc are logged to LogDNA via a separate Docker container.

### Prerequisites

An ARM or X86 device with a sound card (or other audio input devices) connected to the Internet (via wireless network or ethernet cable) that has [Docker-compose](https://docs.docker.com/compose/install/) installed and an AWS account with some S3 buckets set up.

### Installing

Create a base docker image for your architecture by running the script in /base/rpi or /base/amd64 as appropriate.  You will need to create a .env file as appropriate for your projects.  Here is an example of an .env file (tested/working as of June, 2021) without the keys that are common to all Orcasound projects:

```
AWS_METADATA_SERVICE_TIMEOUT=5
AWS_METADATA_SERVICE_NUM_ATTEMPTS=0
REGION=us-west-2
BUCKET_TYPE=dev
NODE_TYPE=hls-only
NODE_NAME=rpi_YOURNODENAME_test
NODE_LOOPBACK=true
SAMPLE_RATE=48000
AUDIO_HW_ID=pisound
CHANNELS=1
FLAC_DURATION=30
SEGMENT_DURATION=10
LC_ALL=C.UTF-8
```

except that the following fields are excised and will be need added if you are integrating with the audio and logging data streaming systems of Orcasound. (You can request keys via the #hydrophone-nodes channel in the Orcasound Slack. As of June, 2021, we are continuing to use AWS S3 for storage and LogDNA for live-logging and troubleshooting.)

```
AWSACCESSKEYID=YourAWSaccessKey
AWSSECRETACCESSKEY=YourAWSsecretAccessKey
 
SYSLOG_URL=syslog+tls://syslog-a.logdna.com:YourLogDNAPort
SYSLOG_STRUCTURED_DATA='logdna@YourLogDNAnumber key="YourLogDNAKey" tag="docker"
```

Here are explanations of some of the .env fields:

* NODE_NAME should indicate your device and it's location, ideally in the form `device_location` (e.g. we call our Raspberry Pi staging device in Seattle `rpi_seattle`. 
* NODE_TYPE determines what audio data formats will be generated and transferred to their respective AWS buckets. 
* AUDIO_HW_ID is the card, device providing the audio data. Note: you can find your sound device by using the command "arecord -l".  It's preferred to use the logical name i.e. pisound, USB, etc, instead of the "0,0" or "1,0" format which can change on reboots. 
* CHANNELS indicates the number of audio channels to expect (1 or 2). 
* FLAC_DURATION is the amount of seconds you want in each archived lossless file. 
* SEGMENT_DURATION is the amount of seconds you want in each streamed lossy segment.



## Running local tests

In the repository directory (where you also put your .env file) first copy the compose file you want to docker-compose.yml.  For example if you are raspberry pi and you want to use the prebuilt image then copy docker-compose.rpi-pull.yml to docker-compose.  Then run `docker-compose up -d`. Watch what happens using `htop`. If you want to verify files are being written to /tmp or /mnt directories, get the name of your streaming service using `docker-compose ps` (in this case `orcanode_streaming_1`) and then do `docker exec -it orcanode_streaming_1 /bin/bash` to get a bash shell within the running container.

### Running an end-to-end test

Once you've verified files are making it to your S3 bucket (with public read access), you can test the stream using a browser-based reference player.  For example, with [Bitmovin HLS/MPEG/DASH player] you can use the drop-down menu to select HLS and then paste the URL for your current S3-based m3u8 manifest file into it to listen to the stream.

Your URL should look something like this:
```
https://s3-us-west-2.amazonaws.com/dev-streaming-orcasound-net/rpi_seattle/hls/1526661120/live.m3u8
```
For end-to-end tests of Orcasound nodes, this schematic describes how sources map to the .dev, .beta, and .live subdomains of orcasound.net --

![Schematic of Orcasound source-subdomain mapping](http://orcasound.net/img/orcasound-app/Orcasound-software-evolution-model.png "Orcasound software evolution model")

-- and you can monitor your development stream via the web-app using this URL structure:

```dev.orcasound.net/dynamic/node_name``` so for node_name = rpi_orcasound_lab the test URL would be [dev.orcasound.net/dynamic/rpi_orcasound_lab](http://dev.orcasound.net/dynamic/rpi_orcasound_lab).


## Deployment

If you would like to add a node to the Orcasound hydrophone network, contact Scott for guidance on how to participate.

## Built With

* [FFmpeg](https://www.ffmpeg.org/) - Uses ALSA to acquire audio data, then generates lossy streams and/or lossless archive files
* [rsync](https://rsync.samba.org/) - Transfers files locally from /tmp to /mnt directories
* [s3fs](https://github.com/s3fs-fuse/s3fs-fuse) - Used to transfer audio data from local device to S3 bucket(s)

## Contributing

Please read [CONTRIBUTING.md](https://github.com/orcasound/orcanode/blob/master/CONTRIBUTING) for details on our code of conduct, and the process for submitting pull requests to us.

## Authors

* **Paul Cretu** - *Lead developer* - [Paul on Github](https://github.com/paulcretu)
* **Scott Veirs** - *Project manager* - [Scott on Github](https://github.com/scottveirs)
* **Steve Hicks** - *Raspberry Pi expert* - [Steve on Github](https://github.com/mcshicks)
* **Val Veirs** - *Hydrophone expert* - [Val on Github](https://github.com/veirs)

See also the list of [contributors](https://github.com/your/project/contributors) who participated in this project.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE.md](LICENSE.md) file for details

## Acknowledgments

* Thanks to the backers of the 2017 Kickstarter that funded the development of this open-source code.
* Thanks to the makers of the Raspberry Pi and the Pisound HAT.
* Thanks to the many friends and backers who helped improve maintain nodes and improve the [Orcasound app](https://github.com/orcasound/orcasite).
