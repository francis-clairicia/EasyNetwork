# EasyNetwork
[![Build](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/build.yml/badge.svg)](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/build.yml)
[![Lint](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/lint.yml/badge.svg)](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/lint.yml)
[![Test](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/test.yml/badge.svg)](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/francis-clairicia/EasyNetwork/branch/main/graph/badge.svg?token=3EGAHE4LZY)](https://codecov.io/gh/francis-clairicia/EasyNetwork)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/francis-clairicia/EasyNetwork/main.svg)](https://results.pre-commit.ci/latest/github/francis-clairicia/EasyNetwork/main)

[![PyPI](https://img.shields.io/pypi/v/easynetwork)](https://pypi.org/project/easynetwork/)
[![PyPI - License](https://img.shields.io/pypi/l/easynetwork)](https://github.com/francis-clairicia/EasyNetwork/blob/main/LICENSE)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/easynetwork)

[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)

The easiest way to use sockets in Python!

## Installation
### From PyPI repository
```sh
pip install --user easynetwork
```

### From source
```sh
git clone https://github.com/francis-clairicia/EasyNetwork.git
cd EasyNetwork
pip install --user .
```

## Overview
EasyNetwork fully encapsulates socket handling, offering you a high-level interface enabling an application/software to fully handle the logic part
with Python objects without worrying about how to process, send or receive data across the network.

The communication protocol can be whatever you want, be it json, pickle, ASCII, structure, base64 encoded, compressed, encrypted,
or any other format not part of the standard library.
You choose the data format, and the library takes care of the rest.

Works with TCP and UDP, for Internet sockets ([AF_INET](https://docs.python.org/3/library/socket.html#socket.AF_INET) and [AF_INET6](https://docs.python.org/3/library/socket.html#socket.AF_INET6) socket families)

N.B.: Unix sockets ([AF_UNIX](https://docs.python.org/3/library/socket.html#socket.AF_UNIX) family) are expressly not supported.

## Usage
### TCP Echo server with JSON data
```py
import logging
from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.api_async.server import AsyncBaseRequestHandler, AsyncClientInterface, StandaloneTCPNetworkServer
from easynetwork.exceptions import BaseProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


# These TypeAliases are there to help you understand where requests and responses are used in the code
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class JSONProtocol(StreamProtocol[ResponseType, RequestType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class EchoRequestHandler(AsyncBaseRequestHandler[RequestType, ResponseType]):
    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    async def handle(self, client: AsyncClientInterface[ResponseType]) -> AsyncGenerator[None, RequestType]:
        request: RequestType = yield  # A JSON request has been sent by this client

        self.logger.info(f"{client.address} sent {request!r}")

        # As a good echo handler, the request is sent back to the client
        response: ResponseType = request
        await client.send_packet(response)

        # Leaving the generator will NOT close the connection, a new generator will be created afterwards.
        # You may manually close the connection if you want to:
        # await client.aclose()

    async def bad_request(self, client: AsyncClientInterface[ResponseType], exc: BaseProtocolParseError) -> None:
        # Invalid JSON data sent
        await client.send_packet({"data": {"error": "Invalid JSON", "code": "parse_error"}})


def main() -> None:
    host = None  # Bind on all interfaces
    # host = "" works too
    port = 9000

    logging.basicConfig(level=logging.INFO, format="[ %(levelname)s ] [ %(name)s ] %(message)s")
    with StandaloneTCPNetworkServer(host, port, JSONProtocol(), EchoRequestHandler()) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
```

### TCP Echo client with JSON data
```py
from typing import Any

from easynetwork.api_sync.client import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class JSONProtocol(StreamProtocol[Any, Any]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


def main() -> None:
    with TCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        client.send_packet({"data": {"my_body": ["as json"]}})
        response = client.recv_packet()  # response will be a JSON
        print(response["data"])  # prints {'my_body': ['as json']}


if __name__ == "__main__":
    main()
```

<details markdown="1">
<summary>Asynchronous version ( with <code>async def</code> )</summary>

```py
import asyncio
from typing import Any

from easynetwork.api_async.client import AsyncTCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class JSONProtocol(StreamProtocol[Any, Any]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


async def main() -> None:
    async with AsyncTCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        await client.send_packet({"data": {"my_body": ["as json"]}})
        response = await client.recv_packet()  # response will be a JSON
        print(response["data"])  # prints {'my_body': ['as json']}


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

### Other examples
Check out the [available examples](./examples) for an overview.

### Documentation
Coming soon.

## License
This project is licensed under the terms of the [MIT License](https://github.com/francis-clairicia/EasyNetwork/blob/main/LICENSE).
