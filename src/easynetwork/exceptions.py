# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Exceptions definition module"""

from __future__ import annotations

__all__ = [
    "BaseProtocolParseError",
    "ClientClosedError",
    "DatagramProtocolParseError",
    "DeserializeError",
    "IncrementalDeserializeError",
    "PacketConversionError",
    "StreamProtocolParseError",
]

from typing import Any, Literal, TypeAlias


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client"""


class DeserializeError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info


class IncrementalDeserializeError(DeserializeError):
    def __init__(self, message: str, remaining_data: bytes, error_info: Any = None) -> None:
        super().__init__(message, error_info=error_info)
        self.remaining_data: bytes = remaining_data


class PacketConversionError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info


class BaseProtocolParseError(Exception):
    ParseErrorType: TypeAlias = Literal["deserialization", "conversion"]

    def __init__(self, error_type: ParseErrorType, message: str, error_info: Any = None) -> None:
        super().__init__(f"Error while parsing data: {message}")
        self.error_type: BaseProtocolParseError.ParseErrorType = error_type
        self.error_info: Any = error_info
        self.message: str = message


class DatagramProtocolParseError(BaseProtocolParseError):
    pass


class StreamProtocolParseError(BaseProtocolParseError):
    def __init__(
        self,
        remaining_data: bytes,
        error_type: StreamProtocolParseError.ParseErrorType,
        message: str,
        error_info: Any = None,
    ) -> None:
        super().__init__(
            error_type=error_type,
            message=message,
            error_info=error_info,
        )
        self.remaining_data: bytes = remaining_data
