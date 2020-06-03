# Orcasound's orcanode

This software captures local audio data and streams it to AWS S3 buckets -- both as lossy (AAC-encoded) data in HLS segments for live-listening and as a lossless (FLAC-encoded) for archiving and/or acoustic analysis. There are branches for both arm32v7 and amd64 architectures, though the majority of initial development has been on the ARM-based Raspberry Pi. The current branches use ffmpeg+s3fs called by a bash script; an improved upload script is under development using ffmpeg+boto within a Python script, possibly with redis handling queueing.

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

Choose the branch that is appropriate for your architecture. Clone that branch and create an .env file that contains the following:

```
AWSACCESSKEYID=YourAWSaccessKey
AWSSECRETACCESSKEY=YourAWSsecretAccessKey

NODE_NAME=YourNodeName
NODE_TYPE=hls-only
AUDIO_HW_ID=1,0
CHANNELS=2
FLAC_DURATION=30
SEGMENT_DURATION=10 
 
SYSLOG_URL=syslog+tls://syslog-a.logdna.com:YourLogDNAPort
SYSLOG_STRUCTURED_DATA='logdna@YourLogDNAnumber key="YourLogDNAKey" tag="docker"
```

* NODE_NAME should indicate your device and it's location, ideally in the form `device_location` (e.g. we call our Raspberry Pi staging device in Seattle `rpi_seattle`. 
* NODE_TYPE determines what audio data formats will be generated and transferred to their respective AWS buckets. 
* AUDIO_HW_ID is the card, device providing the audio data. 
* CHANNELS indicates the number of audio channels to expect (1 or 2). 
* FLAC_DURATION is the amount of seconds you want in each archived lossless file. 
* SEGMENT_DURATION is the amount of seconds you want in each streamed lossy segment.

## Running local tests

In the repository directory (where you also put your .env file) run `docker-compose up -d`. Watch what happens using `htop`. If you want to verify files are being written to /tmp or /mnt directories, get the name of your streaming service using `docker-compose ps` (in this case `orcanode_streaming_1`) and then do `docker exec -it orcanode_streaming_1 /bin/bash` to get a bash shell within the running container.

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
