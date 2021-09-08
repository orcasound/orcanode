# Node Dockerfile for hydrophone streaming

# Use official debian image, but pull the armhf (v7+) image explicitly because
# Docker currently has a bug where armel is used instead when relying on
# multiarch manifest: https://github.com/moby/moby/issues/34875
# When this is fixed, this can be changed to just `FROM debian:stretch-slim`
# FROM python:3.6-slim-buster
FROM arm32v7/python:3.6-slim-buster
MAINTAINER Orcasound <orcanode-devs@orcasound.net>

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

