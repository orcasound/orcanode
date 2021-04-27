#/bin/bash
cd ..
cat amd64/Dockerfile DockerCommon >./DockerFile
docker-compose build --force-rm
