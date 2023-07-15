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
"""Exceptions definition module.

Here are all the exception classes defined and used by the library.
"""

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

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .tools.socket import SocketAddress


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client"""


class ServerClosedError(RuntimeError):
    """Error raised when trying to do an operation on a closed server"""


class ServerAlreadyRunning(RuntimeError):
    """The server is already running"""


class DeserializeError(Exception):
    """Error raised by a :term:`serializer` if the data format is invalid"""

    def __init__(self, message: str, error_info: Any = None) -> None:
        """
        :param message: Error message
        :param error_info: Additional error data
        """

        super().__init__(message)

        self.error_info: Any = error_info
        """Additional error data"""


class IncrementalDeserializeError(DeserializeError):
    """Error raised by an :term:`incremental serializer` if the data format is invalid"""

    def __init__(self, message: str, remaining_data: bytes, error_info: Any = None) -> None:
        """
        :param message: Error message
        :param remaining_data: Unused trailing data
        :param error_info: Additional error data
        """

        super().__init__(message, error_info=error_info)

        self.remaining_data: bytes = remaining_data
        """Unused trailing data"""


class PacketConversionError(Exception):
    """The deserialized :term:`packet` is invalid"""

    def __init__(self, message: str, error_info: Any = None) -> None:
        """
        :param message: Error message
        :param error_info: Additional error data
        """

        super().__init__(message)

        self.error_info: Any = error_info
        """Additional error data"""


class BaseProtocolParseError(Exception):
    """Parsing error raised by a :term:`protocol object`"""

    def __init__(self, error_type: Literal["deserialization", "conversion"], message: str, error_info: Any = None) -> None:
        """
        :param error_type: Error type identifier
        :param message: Error message
        :param error_info: Additional error data
        """

        super().__init__(f"Error while parsing data: {message}")

        self.error_type: Literal["deserialization", "conversion"] = error_type
        """Error type identifier"""

        self.error_info: Any = error_info
        """Additional error data"""

        self.message: str = message
        """Error message"""


class DatagramProtocolParseError(BaseProtocolParseError):
    """Parsing error raised by :class:`easynetwork.protocol.DatagramProtocol`"""

    sender_address: SocketAddress
    """Address of the sender."""


class StreamProtocolParseError(BaseProtocolParseError):
    """Parsing error raised by :class:`easynetwork.protocol.StreamProtocol`"""

    def __init__(
        self,
        remaining_data: bytes,
        error_type: Literal["deserialization", "conversion"],
        message: str,
        error_info: Any = None,
    ) -> None:
        """
        :param remaining_data: Unused trailing data
        :param error_type: Error type identifier
        :param message: Error message
        :param error_info: Additional error data
        """

        super().__init__(
            error_type=error_type,
            message=message,
            error_info=error_info,
        )

        self.remaining_data: bytes = remaining_data
        """Unused trailing data"""
