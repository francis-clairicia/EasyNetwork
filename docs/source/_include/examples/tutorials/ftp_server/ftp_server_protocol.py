from __future__ import annotations

from easynetwork.converter import RequestResponseConverterBuilder
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import StringLineSerializer

from ftp_converters import FTPReplyConverter, FTPRequestConverter
from ftp_reply import FTPReply
from ftp_request import FTPRequest


class FTPServerProtocol(StreamProtocol[FTPReply, FTPRequest]):
    def __init__(self) -> None:
        request_converter = FTPRequestConverter()
        response_converter = FTPReplyConverter()

        super().__init__(
            serializer=StringLineSerializer(newline="CRLF", encoding="ascii"),
            converter=RequestResponseConverterBuilder.build_for_server(
                request_converter,
                response_converter,
            ),
        )
