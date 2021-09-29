#/bin/bash
cd ..
cp arm64/jack.c ./jack.c
cat arm64/Dockerfile DockerCommon >./Dockerfile
docker-compose build --force-rm
