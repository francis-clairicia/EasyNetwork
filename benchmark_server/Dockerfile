ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION

# This means 'do not warn about it' :)
ENV PIP_ROOT_USER_ACTION=ignore

ENV PIP_NO_CACHE_DIR=true
ENV PIP_DISABLE_PIP_VERSION_CHECK=true

RUN pip install -U pip

# Install dependencies prior to copy scripts
RUN mkdir -p /usr/src/servers
COPY servers/requirements.txt /usr/src/servers/requirements.txt
RUN pip install -r /usr/src/servers/requirements.txt

COPY servers /usr/src/servers

ARG EASYNETWORK_SDIST

COPY $EASYNETWORK_SDIST /easynetwork.tar.gz
RUN pip install "/easynetwork.tar.gz"
