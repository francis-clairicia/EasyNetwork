# mypy: disable-error-code=empty-body

from __future__ import annotations

from typing import Any

from easynetwork.converter import AbstractPacketConverter, StapledPacketConverter
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer


class Request:
    ...


class Response:
    ...


class RequestConverter(AbstractPacketConverter[Request, dict[str, Any]]):
    def convert_to_dto_packet(self, request: Request, /) -> dict[str, Any]:
        ...

    def create_from_dto_packet(self, request_dict: dict[str, Any], /) -> Request:
        ...


class ResponseConverter(AbstractPacketConverter[Response, dict[str, Any]]):
    def convert_to_dto_packet(self, response: Response, /) -> dict[str, Any]:
        ...

    def create_from_dto_packet(self, response_dict: dict[str, Any], /) -> Response:
        ...


serializer = JSONSerializer()
request_converter = RequestConverter()
response_converter = ResponseConverter()

client_protocol: StreamProtocol[Request, Response] = StreamProtocol(
    serializer=serializer,
    converter=StapledPacketConverter(
        sent_packet_converter=request_converter,
        received_packet_converter=response_converter,
    ),
)
server_protocol: StreamProtocol[Response, Request] = StreamProtocol(
    serializer=serializer,
    converter=StapledPacketConverter(
        sent_packet_converter=response_converter,
        received_packet_converter=request_converter,
    ),
)
