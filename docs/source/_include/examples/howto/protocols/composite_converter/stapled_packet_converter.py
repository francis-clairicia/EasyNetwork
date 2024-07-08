# mypy: disable-error-code=empty-body

from __future__ import annotations

from typing import Any

from easynetwork.converter import AbstractPacketConverter, StapledPacketConverter
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class Request: ...


class Response: ...


# A converter which handles only Request objects
class RequestConverter(AbstractPacketConverter[Request, dict[str, Any]]):
    def convert_to_dto_packet(self, request: Request, /) -> dict[str, Any]: ...

    def create_from_dto_packet(self, request_dict: dict[str, Any], /) -> Request: ...


# A converter which handles only Response objects
class ResponseConverter(AbstractPacketConverter[Response, dict[str, Any]]):
    def convert_to_dto_packet(self, response: Response, /) -> dict[str, Any]: ...

    def create_from_dto_packet(self, response_dict: dict[str, Any], /) -> Response: ...


serializer = JSONSerializer()
request_converter = RequestConverter()
response_converter = ResponseConverter()

# On the client side, tell the protocol:
# - to serialize with request_converter
# - to deserialize with response_converter
client_protocol: StreamProtocol[Request, Response] = StreamProtocol(
    serializer=serializer,
    converter=StapledPacketConverter(
        sent_packet_converter=request_converter,
        received_packet_converter=response_converter,
    ),
)

# On the server side, tell the protocol:
# - to deserialize with request_converter
# - to serialize with response_converter
server_protocol: StreamProtocol[Response, Request] = StreamProtocol(
    serializer=serializer,
    converter=StapledPacketConverter(
        sent_packet_converter=response_converter,
        received_packet_converter=request_converter,
    ),
)
