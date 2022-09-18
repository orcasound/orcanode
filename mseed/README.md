### Installing

After first creating a base image and a baseline .env file you will need to add certain specific env variable for mseed.  Then you can use docker-compose build to build your image and docker-compose up to run it.  Your .env file should look like this.

```
AWSACCESSKEYID=YourAWSaccessKey
AWSSECRETACCESSKEY=YourAWSsecretAccessKey
 
SYSLOG_URL=syslog+tls://syslog-a.logdna.com:YourLogDNAPort
SYSLOG_STRUCTURED_DATA='logdna@YourLogDNAnumber key="YourLogDNAKey" tag="docker"
```

You will need to add the following variables to your baseline .env file to be able to pull and parse the mseed files.

* STREAM_DELAY This is how many hours your stream will be delayed from the OOI websites, which are not updated in real time.
* DELAY_SEGMENT This is how many hours will be buffered locally after your delay.
* ENV This is set to "live" to live stream a node otherwise set to "test" for fixed start and stop time
* TEST_DATETIME_START for fixed start time example 2019-01-12T03:00:00Z
* TEST_DATETIME_END for fixed end time example2019-01-12T23:59:59Z
* OOI_NODE which OOI Node to stream from example 'PC01A'

