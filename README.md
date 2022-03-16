# Orcasound's orcastream

This software contains audio tools and scripts for capturing, reformatting, transcoding and uploading audio for Orcasound.  The directory structure reflects that we have developed a **base** set of tools and a couple of specific projects, orcanode and orcamseed (in the node and mseed directories).  Orcasound hydrophone nodes stream by running the **node** code on Intel (amd64) or [Raspberry Pi](https://www.raspberrypi.org/) (arm32v7) platforms using a soundcard.  While any soundcard should work, the most common one in use is the [Pisound](https://blokas.io/pisound/) board on either a Raspberry Pi 3B+ or 4.  The other project (in the **mseed** directory) is for converting mseed format data to be streamed via Orcanode through the Orcasound human & machine detection pipeline.  This is mainly used for streaming audio data from the [OOI](https://oceanobservatories.org/ "OOI") (NSF-funded Ocean Observatory Initiative) hydrophones off the coast of Oregon.  See the README in each of those directories for more info.

## Background & motivation

This code was developed for source nodes on the [Orcasound](http://orcasound.net) hydrophone network (WA, USA) -- thus the repository names begin with "orca"! Our primary motivation is to make it easy for lots of folks to listen for whales using their favorite device/OS/browser. 

We also aspire to use open source software as much as possible. We rely heavily on [FFmpeg](https://www.ffmpeg.org/). One of our long-term goals is to stream lossless FLAC-encoded data within DASH segments to a player that works optimally on as many listening devices as possible.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See the deployment section (below) for notes on how to deploy the project on a live system like [live.orcasound.net](https://live.orcasound.net).

If you want to set up your hardware to host a hydrophone within the Orcasound network, take a look at [how to join Orcasound](http://www.orcasound.net/join/) and [our prototype built from a Raspberry Pi3b with the Pisound Hat](http://www.orcasound.net/2018/04/27/orcasounds-new-live-audio-solution-from-hydrophone-to-headphone-with-a-raspberry-pi-computer-and-hls-dash-streaming-software/).

The general scheme is to acquire audio data from a sound card within a Docker container via ALSA or Jack and FFmpeg, and then stream the audio data with minimal latency to cloud-based storage (as of Oct 2021, we use AWS S3 buckets). Errors/etc are logged to LogDNA via a separate Docker container.

### Prerequisites

An ARM or X86 device with a sound card (or other audio input devices) connected to the Internet (via wireless network or ethernet cable) that has [Docker-compose](https://docs.docker.com/compose/install/) installed and an AWS account with some S3 buckets set up.

### Installing

Create a base docker image for your architecture by running the script in /base/rpi or /base/amd64 as appropriate.  You will need to create a .env file as appropriate for your projects.  Here is an example of an .env file (tested/working as of June, 2021)...

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

... except that the following fields are excised and will need to be added if you are integrating with the audio and logging systems of Orcasound: 

```
AWSACCESSKEYID=YourAWSaccessKey
AWSSECRETACCESSKEY=YourAWSsecretAccessKey
 
SYSLOG_URL=syslog+tls://syslog-a.logdna.com:YourLogDNAPort
SYSLOG_STRUCTURED_DATA='logdna@YourLogDNAnumber key="YourLogDNAKey" tag="docker"
```

(You can request keys via the #hydrophone-nodes channel in the Orcasound Slack. As of October, 2021, we are continuing to use AWS S3 for storage and LogDNA for live-logging and troubleshooting.)

Here are explanations of some of the .env fields:

* NODE_NAME should indicate your device and it's location, ideally in the form `device_location` (e.g. we call our Raspberry Pi staging device in Seattle `rpi_seattle`. 
* NODE_TYPE determines what audio data formats will be generated and transferred to their respective AWS buckets. 
* AUDIO_HW_ID is the card, device providing the audio data. Note: you can find your sound device by using the command "arecord -l".  It's preferred to use the logical name i.e. pisound, USB, etc, instead of the "0,0" or "1,0" format which can change on reboots. 
* CHANNELS indicates the number of audio channels to expect (1 or 2). 
* FLAC_DURATION is the amount of seconds you want in each archived lossless file. 
* SEGMENT_DURATION is the amount of seconds you want in each streamed lossy segment.


## Running local tests

At the root of the repository directory (where you also put your .env file) first copy the compose file you want to `docker-compose.yml`.  For example, if you have a Raspberry Pi and you want to use the prebuilt image, then copy `docker-compose.rpi-pull.yml` to `docker-compose.yml`.  Then run `docker-compose up -d`. Watch what happens using `htop`. If you want to verify files are being written to /tmp or /mnt directories, get the name of your streaming service using `docker-compose ps` (in this case `orcanode_streaming_1`) and then do `docker exec -it orcanode_streaming_1 /bin/bash` to get a bash shell within the running container.

### Running an end-to-end test

Once you've verified files are making it to your S3 bucket (with public read access), you can test the stream using a browser-based reference player.  For example, with [Bitmovin HLS/MPEG/DASH player](https://bitmovin.com/demos/stream-test?format=hls&manifest=) you can use select HLS and then paste the URL for your current S3-based manifest (`.m3u8` file) to listen to the stream (and observe buffer levels and bitrate in real-time).

Your URL should look something like this:
```
https://s3-us-west-2.amazonaws.com/dev-streaming-orcasound-net/rpi_seattle/hls/1526661120/live.m3u8
```
For end-to-end tests of Orcasound nodes, this schematic describes how sources map to the `dev`, `beta`, and `live` subdomains of orcasound.net --

![Schematic of Orcasound source-subdomain mapping](http://orcasound.net/img/orcasound-app/Orcasound-software-evolution-model.png "Orcasound software evolution model")

-- and you can monitor your development stream via the web-app using this URL structure:

```dev.orcasound.net/dynamic/node_name``` 

For example, with node_name = rpi_orcasound_lab the test URL would be [dev.orcasound.net/dynamic/rpi_orcasound_lab](http://dev.orcasound.net/dynamic/rpi_orcasound_lab).


## Deployment

If you would like to add a node to the Orcasound hydrophone network, contact admin@orcasound.net for guidance on how to participate.

## Built With

* [FFmpeg](https://www.ffmpeg.org/) - Uses ALSA to acquire audio data, then generates lossy streams and/or lossless archive files
* [rsync](https://rsync.samba.org/) - Transfers files locally from /tmp to /mnt directories
* [s3fs](https://github.com/s3fs-fuse/s3fs-fuse) - Used to transfer audio data from local device to S3 bucket(s)

## Contributing

Please read [CONTRIBUTING.md](https://github.com/orcasound/orcanode/blob/master/CONTRIBUTING) for details on our code of conduct, and the process for submitting pull requests.

## Authors

* **Steve Hicks** - *Raspberry Pi expert* - [Steve on Github](https://github.com/mcshicks)
* **Paul Cretu** - *Lead developer* - [Paul on Github](https://github.com/paulcretu)
* **Scott Veirs** - *Project manager* - [Scott on Github](https://github.com/scottveirs)
* **Val Veirs** - *Hydrophone expert* - [Val on Github](https://github.com/veirs)

See also the list of [orcanode contributors](https://github.com/orcasound/orcanode/graphs/contributors) who have helped this project and the [Orcasound Hacker Hall of Fame] who have advanced both Orcasound open source code and the hydrophone network in the habitat of the endangered Southern Resident killer whales.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE.md](LICENSE.md) file for details

## Acknowledgments

* Thanks to the backers of the 2017 Kickstarter that funded the development of this open source code.
* Thanks to the makers of the Raspberry Pi and the Pisound HAT.
* Thanks to the many friends and backers who helped improve maintain nodes and improve the [Orcasound app](https://github.com/orcasound/orcasite).
