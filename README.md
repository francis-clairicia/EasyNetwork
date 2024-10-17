# EasyNetwork

The easiest way to use sockets in Python!

[![PyPI](https://img.shields.io/pypi/v/easynetwork)](https://pypi.org/project/easynetwork/)
[![PyPI - License](https://img.shields.io/pypi/l/easynetwork)](https://github.com/francis-clairicia/EasyNetwork/blob/main/LICENSE)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/easynetwork)

[![Test](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/test.yml/badge.svg)](https://github.com/francis-clairicia/EasyNetwork/actions/workflows/test.yml)
[![Documentation Status](https://readthedocs.org/projects/easynetwork/badge/?version=latest)](https://easynetwork.readthedocs.io/en/latest/?badge=latest)
[![Codecov](https://img.shields.io/codecov/c/github/francis-clairicia/EasyNetwork)](https://codecov.io/gh/francis-clairicia/EasyNetwork)
[![CodeFactor Grade](https://img.shields.io/codefactor/grade/github/francis-clairicia/EasyNetwork)](https://www.codefactor.io/repository/github/francis-clairicia/easynetwork)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/francis-clairicia/EasyNetwork/main.svg)](https://results.pre-commit.ci/latest/github/francis-clairicia/EasyNetwork/main)

[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

[![Hatch project](https://img.shields.io/badge/%F0%9F%A5%9A-Hatch-4051b5.svg)](https://github.com/pypa/hatch)
[![pdm-managed](https://img.shields.io/badge/pdm-managed-blueviolet)](https://pdm.fming.dev)

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
EasyNetwork completely encapsulates the socket handling, providing you with a higher level interface
that allows an application/software to completely handle the logic part with Python objects,
without worrying about how to process, send or receive data over the network.

The communication protocol can be whatever you want, be it JSON, Pickle, ASCII, structure, base64 encoded,
compressed, or any other format that is not part of the standard library.
You choose the data format and the library takes care of the rest.

This project is especially useful for simple **message** exchange between clients and servers.

Works with TCP, UDP, and Unix sockets.

Interested ? Here is the documentation : https://easynetwork.readthedocs.io/

## Usage
### TCP Echo server with JSON data
```py
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer
from easynetwork.servers import AsyncTCPNetworkServer
from easynetwork.servers.handlers import AsyncStreamClient, AsyncStreamRequestHandler

# These TypeAliases are there to help you understand
# where requests and responses are used in the code
RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class JSONProtocol(StreamProtocol[ResponseType, RequestType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


class EchoRequestHandler(AsyncStreamRequestHandler[RequestType, ResponseType]):
    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    async def handle(
        self,
        client: AsyncStreamClient[ResponseType],
    ) -> AsyncGenerator[None, RequestType]:
        # A JSON request has been sent by this client
        data: Any = yield

        self.logger.info(f"{client!r} sent {data!r}")

        # As a good echo handler, the request is sent back to the client
        await client.send_packet(data)

        # Leaving the generator will NOT close the connection,
        # a new generator will be created afterwards.
        # You may manually close the connection if you want to:
        # await client.aclose()


async def main() -> None:
    host = None  # Bind on all interfaces
    port = 9000
    protocol = JSONProtocol()
    handler = EchoRequestHandler()

    logging.basicConfig(
        level=logging.INFO,
        format="[ %(levelname)s ] [ %(name)s ] %(message)s",
    )

    async with AsyncTCPNetworkServer(host, port, protocol, handler) as server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except* KeyboardInterrupt:
        pass
```

### TCP Echo client with JSON data
```py
from typing import Any, TypeAlias

from easynetwork.clients import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

RequestType: TypeAlias = Any
ResponseType: TypeAlias = Any


class JSONProtocol(StreamProtocol[RequestType, ResponseType]):
    def __init__(self) -> None:
        super().__init__(JSONSerializer())


def main() -> None:
    with TCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        client.send_packet({"data": {"my_body": ["as json"]}})
        response = client.recv_packet()  # response should be the sent dictionary
        print(response)  # prints {'data': {'my_body': ['as json']}}


if __name__ == "__main__":
    main()
```

#### Asynchronous version ( with `async def` )

```py
import asyncio

from easynetwork.clients import AsyncTCPNetworkClient

...

async def main() -> None:
    async with AsyncTCPNetworkClient(("localhost", 9000), JSONProtocol()) as client:
        await client.send_packet({"data": {"my_body": ["as json"]}})
        response = await client.recv_packet()
        print(response)  # prints {'data': {'my_body': ['as json']}}


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

## License
This project is licensed under the terms of the [Apache Software License 2.0](https://github.com/francis-clairicia/EasyNetwork/blob/main/LICENSE).

### AnyIO's typed attributes

AnyIO's typed attributes is incorporated in `easynetwork.lowlevel.typed_attr` from [anyio 4.2](https://github.com/agronholm/anyio/tree/4.2.0), which is distributed under the [MIT license](https://github.com/agronholm/anyio/blob/4.2.0/LICENSE).
