ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION

# This means 'do not warn about it' :)
ENV PIP_ROOT_USER_ACTION=ignore

ENV PIP_NO_CACHE_DIR=true

RUN pip install -U pip

RUN mkdir -p /usr/src
COPY servers /usr/src/servers
RUN pip install -r /usr/src/servers/requirements.txt

ARG EASYNETWORK_SDIST

COPY $EASYNETWORK_SDIST /easynetwork.tar.gz
RUN pip install "/easynetwork.tar.gz"
