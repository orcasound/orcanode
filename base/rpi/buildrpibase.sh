#/bin/bash
cd ..
cat rpi/Dockerfile DockerCommon >./Dockerfile
docker-compose build --force-rm
