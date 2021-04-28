#/bin/bash
cd ..
cat amd64/Dockerfile DockerCommon >./Dockerfile
docker-compose build --force-rm
