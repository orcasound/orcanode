### Installing

After first creating a base image and a baseline .env file you will need to add certain specific env variable for mseed.  Then you can use `docker-compose build` to build your image and `docker-compose up` to run it.  Your .env file should look like this.

```
AWSACCESSKEYID=YourAWSaccessKey
AWSSECRETACCESSKEY=YourAWSsecretAccessKey
 
SYSLOG_URL=syslog+tls://syslog-a.logdna.com:YourLogDNAPort
SYSLOG_STRUCTURED_DATA='logdna@YourLogDNAnumber key="YourLogDNAKey" tag="docker"
```

You will need to add the following variables to your baseline .env file to be able to pull and parse the mseed files.

* STREAM_DELAY This is how many hours your stream will be delayed from the OOI websites, which are not updated in real time.
* DELAY_SEGMENT This is how many hours will be buffered locally after your delay.
* BASE_URL This is the root URL that your mseed files will be pulled from 
* TIME_PREFIX This is a unique file prefix for each OOI site which will be ignored when checking time filetimes
* TIME_POSTFIX This is the portion after the timestamp.  Nominally should be .mseed

