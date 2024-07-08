# mypy: disable-error-code=empty-body

from __future__ import annotations

from typing import Any

from easynetwork.converter import AbstractPacketConverterComposite
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class Request: ...


class Response: ...


# The client side knows how to serialize a request and deserialize a response
class ClientConverter(AbstractPacketConverterComposite[Request, Response, dict[str, Any], dict[str, Any]]):
    def convert_to_dto_packet(self, request: Request, /) -> dict[str, Any]: ...

    def create_from_dto_packet(self, response_dict: dict[str, Any], /) -> Response: ...


# The server side knows how to deserialize a request and serialize a response
class ServerConverter(AbstractPacketConverterComposite[Response, Request, dict[str, Any], dict[str, Any]]):
    def convert_to_dto_packet(self, response: Response, /) -> dict[str, Any]: ...

    def create_from_dto_packet(self, request_dict: dict[str, Any], /) -> Request: ...


serializer = JSONSerializer()

client_protocol: StreamProtocol[Request, Response] = StreamProtocol(
    serializer=serializer,
    converter=ClientConverter(),
)
server_protocol: StreamProtocol[Response, Request] = StreamProtocol(
    serializer=serializer,
    converter=ServerConverter(),
)
