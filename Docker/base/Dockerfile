# initialize from the image

ARG BASE_IMAGE=debian:9
FROM ${BASE_IMAGE} AS tbuilder

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Prague

RUN set -ex && \
    apt-get update && \
    apt-get --no-install-recommends --yes install \
        ca-certificates \
        cmake \
        g++ \
        git \
        make \
        pkg-config

## Packager cleanup, best practices
RUN set -ex && rm -rf /var/lib/apt/lists/*
