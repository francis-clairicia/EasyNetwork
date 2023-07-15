# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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
    "ServerAlreadyRunning",
    "ServerClosedError",
    "StreamProtocolParseError",
]

from typing import TYPE_CHECKING, Any, Literal, TypeAlias

if TYPE_CHECKING:
    from .tools.socket import SocketAddress


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client"""


class ServerClosedError(RuntimeError):
    """Error raised when trying to do an operation on a closed server"""


class ServerAlreadyRunning(RuntimeError):
    """Error raised if serve_forever() is called twice"""


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
    sender_address: SocketAddress


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
