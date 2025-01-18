# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
    "BusyResourceError",
    "ClientClosedError",
    "DatagramProtocolParseError",
    "DeserializeError",
    "IncrementalDeserializeError",
    "LimitOverrunError",
    "PacketConversionError",
    "ServerAlreadyRunning",
    "ServerClosedError",
    "StreamProtocolParseError",
    "TypedAttributeLookupError",
    "UnsupportedOperation",
]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class BusyResourceError(RuntimeError):
    """Error raised when a task attempts to use a resource that some other task is
    already using, and this would lead to bugs and nonsense.

    Mostly used in asynchronous functions.
    """


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client."""


class ServerClosedError(RuntimeError):
    """Error raised when trying to do an operation on a closed server."""


class ServerAlreadyRunning(RuntimeError):
    """The server is already running."""


class DeserializeError(Exception):
    """Error raised by a :term:`serializer` if the data format is invalid."""

    def __init__(self, message: str, error_info: Any = None) -> None:
        """
        Parameters:
            message: Error message.
            error_info: Additional error data.
        """

        super().__init__(message)

        self.error_info: Any = error_info
        """Additional error data."""


class IncrementalDeserializeError(DeserializeError):
    """Error raised by an :term:`incremental serializer` if the data format is invalid."""

    def __init__(self, message: str, remaining_data: ReadableBuffer, error_info: Any = None) -> None:
        """
        Parameters:
            message: Error message.
            remaining_data: Unused trailing data.
            error_info: Additional error data.
        """

        super().__init__(message, error_info=error_info)

        self.remaining_data: ReadableBuffer = remaining_data
        """Unused trailing data."""


class LimitOverrunError(IncrementalDeserializeError):
    """Reached the buffer size limit while looking for a separator."""

    def __init__(self, message: str, buffer: ReadableBuffer, consumed: int, separator: bytes = b"") -> None:
        """
        Parameters:
            message: Error message.
            buffer: Currently too big buffer.
            consumed: Total number of to be consumed bytes.
            separator: Searched separator.
        """

        remaining_data = memoryview(buffer)[consumed:]
        seplen = len(separator)
        if seplen:
            if remaining_data[:seplen] == separator:
                remaining_data = remaining_data[seplen:]
            else:
                while remaining_data.nbytes and remaining_data[:seplen] != separator[: remaining_data.nbytes]:
                    remaining_data = remaining_data[1:]

        super().__init__(message, bytes(remaining_data), error_info=None)

        self.consumed: int = consumed
        """Total number of to be consumed bytes."""


class PacketConversionError(Exception):
    """The deserialized :term:`packet` is invalid."""

    def __init__(self, message: str, error_info: Any = None) -> None:
        """
        Parameters:
            message: Error message.
            error_info: Additional error data.
        """

        super().__init__(message)

        self.error_info: Any = error_info
        """Additional error data."""


class BaseProtocolParseError(Exception):
    """Parsing error raised by a :term:`protocol object`."""

    def __init__(self, error: DeserializeError | PacketConversionError) -> None:
        """
        Parameters:
            error: Error instance.
        """

        super().__init__(f"Error while parsing data: {error}")

        self.error: DeserializeError | PacketConversionError = error
        """Error instance."""


class DatagramProtocolParseError(BaseProtocolParseError):
    """Parsing error raised by :class:`easynetwork.protocol.DatagramProtocol`."""


class StreamProtocolParseError(BaseProtocolParseError):
    """Parsing error raised by :class:`easynetwork.protocol.StreamProtocol`."""

    def __init__(self, remaining_data: ReadableBuffer, error: IncrementalDeserializeError | PacketConversionError) -> None:
        """
        Parameters:
            remaining_data: Unused trailing data.
            error: Error instance.
        """

        super().__init__(error)

        self.error: IncrementalDeserializeError | PacketConversionError
        """Error instance."""

        self.remaining_data: ReadableBuffer = remaining_data
        """Unused trailing data."""


class TypedAttributeLookupError(LookupError):
    """
    Raised by :meth:`~.TypedAttributeProvider.extra` when the given typed attribute
    is not found and no default value has been given.
    """


class UnsupportedOperation(NotImplementedError):
    """
    The requested action is currently unavailable.
    """
