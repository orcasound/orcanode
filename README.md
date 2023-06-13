# Orcasound's orcanode code for live-streaming audio data

The `orcanode` software repository contains audio tools and scripts for capturing, reformatting, transcoding and uploading audio data at each node of a network. Orcanode live-streaming should work on Intel (amd64) or Raspberry Pi (arm32v7) platforms using any soundcard.  The most common hardware used by Orcasound is the [Pisound HAT](https://blokas.io/pisound/) on either a Raspberry Pi 3B+ or 4. 

There is a `base` set of tools and a couple of specific projects in the `node` and `mseed` directories. The mseed directory has code for converting mseed format data to the live-streaming audio format used in the node code. This conversion code is mainly used for audio data collected by the [Ocean Observatories Initiative or OOI](https://oceanobservatories.org/ "OOI") network.  See the README in each of those directories for more info.

You can also gain some bioacoustic context for the project in the [orcanode wiki](https://github.com/orcasound/orcanode/wiki).

## Background & motivation

This code was developed for live-streaming from source nodes in the [Orcasound](http://orcasound.net) hydrophone network (WA, USA). Thus, the repository names begin with "orca"! Our primary motivation is to make it easy for community scientists to listen for whales via the [Orcasound web app](https://live.orcasound.net) using their favorite device/OS/browser.

We also aspire to use open source software as much as possible. We rely heavily on [FFmpeg](https://www.ffmpeg.org/). One of our long-term goals is to stream lossless FLAC-encoded data within DASH segments to a player that works optimally on as many listening devices as possible.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See the deployment section (below) for notes on how to deploy the project on a live system like [live.orcasound.net](https://live.orcasound.net).

If you want to set up your hardware to host a hydrophone within the Orcasound network, take a look at [how to join Orcasound](http://www.orcasound.net/join/) and [our prototype built from a Raspberry Pi3b with the Pisound Hat](http://www.orcasound.net/2018/04/27/orcasounds-new-live-audio-solution-from-hydrophone-to-headphone-with-a-raspberry-pi-computer-and-hls-dash-streaming-software/).

The general scheme is to acquire audio data from a sound card within a Docker container via ALSA or Jack and FFmpeg, and then stream the audio data with minimal latency to cloud-based storage (as of Oct 2021, we use AWS S3 buckets). Errors/etc are logged to LogDNA via a separate Docker container.

### Prerequisites

An ARM or X86 device with a sound card (or other audio input devices) connected to the Internet (via wireless network or ethernet cable) that has [Docker-compose](https://docs.docker.com/compose/install/) installed and an AWS account with some S3 buckets set up.

### Installing

Create a base docker image for your architecture by running the script in /base/rpi or /base/amd64 as appropriate.  You will need to create a .env file as appropriate for your projects.  Common to to all projects are the need for AWS keys

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
* AUDIO_HW_ID is the card, device providing the audio data. Note: you can find your sound device by using the command "arecord -l".  For Raspberry Pi hardware with pisound just use AUDIO_HW_ID=pisound
* CHANNELS indicates the number of audio channels to expect (1 or 2). 
* FLAC_DURATION is the amount of seconds you want in each archived lossless file. 
* SEGMENT_DURATION is the amount of seconds you want in each streamed lossy segment.


## Supported combinations


| NODE ARCHITECTURE | node | mseed |
|-------------------|------|-------|
| arm32v7           |  Y   |  N    |
| amd64             |  Y   |  Y    |



| NODE ARCHITECTURE | hls-only | research | dev-virt |
|-------------------|----------|----------|----------|
| arm32v7           | Y        | Y        | N        |
| amd64             | Y        | N        | Y        |



| NODE Hardware     | hls-only | research |
|-------------------|----------|----------|
| RPI4              | Y        | Y        |
| RPI3 B-           | Y        | N        |



## Running local tests

In the repository directory (where you also put your .env file) first copy the compose file you want to docker-compose.yml.  For example if you are raspberry pi and you want to use the prebuilt image then copy docker-compose.rpi-pull.yml to docker-compose.  Then run `docker-compose up -d`. Watch what happens using `htop`. If you want to verify files are being written to /tmp or /mnt directories, get the name of your streaming service using `docker-compose ps` (in this case `orcanode_streaming_1`) and then do `docker exec -it orcanode_streaming_1 /bin/bash` to get a bash shell within the running container.

## Running an end-to-end test

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

If you would like to add a node to the Orcasound hydrophone network, read through our [Administrative Handbook](https://github.com/orcasound/.github/wiki#3-administrative-handbook) and then contact admin@orcasound.net if you have any questions. 

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

See also the list of [orcanode contributors](https://github.com/orcasound/orcanode/graphs/contributors) who have helped this project and the [Orcasound Hacker Hall of Fame](https://www.orcasound.net/hacker-hall-of-fame/) who have advanced both Orcasound open source code and the hydrophone network in the habitat of the endangered Southern Resident killer whales.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE.md](LICENSE.md) file for details

## Acknowledgments

* Thanks to the backers of the 2017 Kickstarter that funded the development of this open source code.
* Thanks to the makers of the Raspberry Pi, the Pisound HAT (Blokas in Lithuania), and the manufacturers who supply us with long-lasting, cost-effective hydrophones.
* Thanks to the many friends and backers who helped improve maintain nodes and improve the [Orcasound app](https://github.com/orcasound/orcasite).
