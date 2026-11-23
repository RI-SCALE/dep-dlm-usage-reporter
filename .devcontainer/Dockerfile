FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image ships a yarn apt source with no signing key, which breaks
# `apt-get update` for every feature layered on top (e.g. docker-in-docker).
# This project doesn't need yarn, so just drop the source.
RUN rm -f /etc/apt/sources.list.d/yarn.list

# uv, pinned to the minor version the build backend allows (uv_build <0.12).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

RUN curl -fsSL https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz \
    | tar xz -C /usr/local/bin kubeconform