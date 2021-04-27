#/bin/bash
cd ..
cat rpi/Dockerfile DockerCommon >./DockerFile
docker-compose build --force-rm
