ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION

RUN pip install --no-cache-dir -U pip

RUN mkdir -p /usr/src
COPY servers /usr/src/servers
RUN pip install --no-cache-dir -r /usr/src/servers/requirements.txt

ARG EASYNETWORK_SDIST

COPY $EASYNETWORK_SDIST /easynetwork.tar.gz
RUN pip install --no-cache-dir "/easynetwork.tar.gz"
