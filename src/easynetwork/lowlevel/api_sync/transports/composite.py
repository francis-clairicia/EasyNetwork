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
"""Low-level synchronous transport composite module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = [
    "StapledDatagramTransport",
    "StapledStreamTransport",
]

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, final

from ... import _utils
from ..._final import runtime_final_class
from . import abc as _transports

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer


_T_SendStreamTransport = TypeVar("_T_SendStreamTransport", bound=_transports.StreamWriteTransport)
_T_ReceiveStreamTransport = TypeVar("_T_ReceiveStreamTransport", bound=_transports.StreamReadTransport)

_T_SendDatagramTransport = TypeVar("_T_SendDatagramTransport", bound=_transports.DatagramWriteTransport)
_T_ReceiveDatagramTransport = TypeVar("_T_ReceiveDatagramTransport", bound=_transports.DatagramReadTransport)


@final
@runtime_final_class
@dataclass(frozen=True, slots=True)
class StapledStreamTransport(_transports.StreamTransport, Generic[_T_SendStreamTransport, _T_ReceiveStreamTransport]):
    """
    A continous stream data transport that merges two transports.

    Extra attributes will be provided from both transports, with the receive stream providing the values in case of a conflict.

    .. versionadded:: 1.1
    """

    send_transport: _T_SendStreamTransport
    """The write part of the transport."""

    receive_transport: _T_ReceiveStreamTransport
    """The read part of the transport."""

    def close(self) -> None:
        """
        Closes both transports.
        """
        _close_stapled_transports(self.send_transport, self.receive_transport)

    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called on both transports.

        Returns:
            :data:`True` if the transports are closed.
        """
        return self.send_transport.is_closed() and self.receive_transport.is_closed()

    def recv(self, bufsize: int, timeout: float) -> bytes:
        """
        Calls :meth:`self.receive_transport.recv() <.StreamReadTransport.recv>`.
        """
        return self.receive_transport.recv(bufsize, timeout)

    def recv_into(self, buffer: WriteableBuffer, timeout: float) -> int:
        """
        Calls :meth:`self.receive_transport.recv_into() <.StreamReadTransport.recv_into>`.
        """
        return self.receive_transport.recv_into(buffer, timeout)

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> int:
        """
        Calls :meth:`self.send_transport.send() <.StreamWriteTransport.send>`.
        """
        return self.send_transport.send(data, timeout)

    def send_all(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Calls :meth:`self.send_transport.send_all() <.StreamWriteTransport.send_all>`.
        """
        return self.send_transport.send_all(data, timeout)

    def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview], timeout: float) -> None:
        """
        Calls :meth:`self.send_transport.send_all_from_iterable() <.StreamWriteTransport.send_all_from_iterable>`.
        """
        return self.send_transport.send_all_from_iterable(iterable_of_data, timeout)

    def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.

        If :meth:`self.send_transport.send_eof() <.StreamTransport.send_eof>` then this calls it. Otherwise, this calls
        :meth:`self.send_transport.close() <.BaseTransport.close>`.

        Note:
            This method handles the case where :meth:`self.send_transport.send_eof() <.StreamTransport.send_eof>`
            raises :exc:`NotImplementedError` or :exc:`.UnsupportedOperation`;
            :meth:`self.send_transport.close() <.BaseTransport.close>` will be called as a fallback.
        """
        try:
            if not isinstance(self.send_transport, _transports.StreamTransport):
                raise NotImplementedError("not a full-duplex transport")
            # send_eof() can raise UnsupportedOperation, subclass of NotImplementedError
            self.send_transport.send_eof()
        except NotImplementedError:
            self.send_transport.close()

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.send_transport.extra_attributes,
            **self.receive_transport.extra_attributes,
        }


@final
@runtime_final_class
@dataclass(frozen=True, slots=True)
class StapledDatagramTransport(_transports.DatagramTransport, Generic[_T_SendDatagramTransport, _T_ReceiveDatagramTransport]):
    """
    A transport of unreliable packets of data that merges two transports.

    Extra attributes will be provided from both transports, with the receive stream providing the values in case of a conflict.

    .. versionadded:: 1.1
    """

    send_transport: _T_SendDatagramTransport
    """The write part of the transport."""

    receive_transport: _T_ReceiveDatagramTransport
    """The read part of the transport."""

    def close(self) -> None:
        """
        Closes both transports.
        """
        _close_stapled_transports(self.send_transport, self.receive_transport)

    def is_closed(self) -> bool:
        """
        Checks if :meth:`close` has been called on both transports.

        Returns:
            :data:`True` if the transports are closed.
        """
        return self.send_transport.is_closed() and self.receive_transport.is_closed()

    def recv(self, timeout: float) -> bytes:
        """
        Calls :meth:`self.receive_transport.recv() <.DatagramReadTransport.recv>`.
        """
        return self.receive_transport.recv(timeout)

    def send(self, data: bytes | bytearray | memoryview, timeout: float) -> None:
        """
        Calls :meth:`self.send_transport.send() <.DatagramWriteTransport.send>`.
        """
        return self.send_transport.send(data, timeout)

    @property
    @_utils.inherit_doc(_transports.BaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.send_transport.extra_attributes,
            **self.receive_transport.extra_attributes,
        }


def _close_stapled_transports(
    send_transport: _transports.BaseTransport,
    receive_transport: _transports.BaseTransport,
) -> None:
    try:
        send_transport.close()
    finally:
        receive_transport.close()
