#/bin/bash
cd ..
cp rpi/jack.c ./jack.c
cat rpi/Dockerfile DockerCommon >./Dockerfile
docker-compose build --force-rm
