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
"""Low-level asynchronous transport composite module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = [
    "AsyncStapledDatagramTransport",
    "AsyncStapledStreamTransport",
]

import contextlib
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, Generic, TypeVar, final

from ... import _utils
from ..._final import runtime_final_class
from . import abc as _transports
from .utils import aclose_forcefully

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

    from ..backend.abc import AsyncBackend


_T_SendStreamTransport = TypeVar("_T_SendStreamTransport", bound=_transports.AsyncStreamWriteTransport)
_T_ReceiveStreamTransport = TypeVar("_T_ReceiveStreamTransport", bound=_transports.AsyncStreamReadTransport)

_T_SendDatagramTransport = TypeVar("_T_SendDatagramTransport", bound=_transports.AsyncDatagramWriteTransport)
_T_ReceiveDatagramTransport = TypeVar("_T_ReceiveDatagramTransport", bound=_transports.AsyncDatagramReadTransport)


@final
@runtime_final_class
@dataclass(frozen=True, slots=True)
class AsyncStapledStreamTransport(_transports.AsyncStreamTransport, Generic[_T_SendStreamTransport, _T_ReceiveStreamTransport]):
    """
    An asynchronous continous stream data transport that merges two transports.

    Extra attributes will be provided from both transports, with the receive stream providing the values in case of a conflict.

    .. versionadded:: 1.1
    """

    send_transport: _T_SendStreamTransport
    """The write part of the transport."""

    receive_transport: _T_ReceiveStreamTransport
    """The read part of the transport."""

    _backend: AsyncBackend = dataclass_field(init=False)

    def __post_init__(self) -> None:
        backend = _check_stapled_transports_consistency(self.send_transport, self.receive_transport)
        object.__setattr__(self, "_backend", backend)

    async def aclose(self) -> None:
        """
        Closes both transports.

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transports to close.

            If :meth:`aclose` is cancelled, the transports are closed using :func:`.aclose_forcefully`.
        """
        await _close_stapled_transports(self.send_transport, self.receive_transport)

    def is_closing(self) -> bool:
        """
        Checks if both the transports are closed or in the process of being closed.

        Returns:
            :data:`True` if the transports are closing.
        """
        return self.send_transport.is_closing() and self.receive_transport.is_closing()

    async def recv(self, bufsize: int) -> bytes:
        """
        Calls :meth:`self.receive_transport.recv() <.AsyncStreamReadTransport.recv>`.
        """
        return await self.receive_transport.recv(bufsize)

    async def recv_into(self, buffer: WriteableBuffer) -> int:
        """
        Calls :meth:`self.receive_transport.recv_into() <.AsyncStreamReadTransport.recv_into>`.
        """
        return await self.receive_transport.recv_into(buffer)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        """
        Calls :meth:`self.send_transport.send_all() <.AsyncStreamWriteTransport.send_all>`.
        """
        return await self.send_transport.send_all(data)

    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        """
        Calls :meth:`self.send_transport.send_all_from_iterable() <.AsyncStreamWriteTransport.send_all_from_iterable>`.
        """
        return await self.send_transport.send_all_from_iterable(iterable_of_data)

    async def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.

        If :meth:`self.send_transport.send_eof() <.AsyncStreamTransport.send_eof>` then this calls it. Otherwise, this calls
        :meth:`self.send_transport.aclose() <.AsyncBaseTransport.aclose>`.

        Note:
            This method handles the case where :meth:`self.send_transport.send_eof() <.AsyncStreamTransport.send_eof>`
            raises :exc:`NotImplementedError` or :exc:`.UnsupportedOperation`;
            :meth:`self.send_transport.aclose() <.AsyncBaseTransport.aclose>` will be called as a fallback.
        """
        try:
            if not isinstance(self.send_transport, _transports.AsyncStreamTransport):
                raise NotImplementedError("not a full-duplex transport")
            # send_eof() can raise UnsupportedOperation, subclass of NotImplementedError
            await self.send_transport.send_eof()
        except NotImplementedError:
            await self.send_transport.aclose()

    @_utils.inherit_doc(_transports.AsyncStreamTransport)
    def backend(self) -> AsyncBackend:
        return self._backend

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.send_transport.extra_attributes,
            **self.receive_transport.extra_attributes,
        }


@final
@runtime_final_class
@dataclass(frozen=True, slots=True)
class AsyncStapledDatagramTransport(
    _transports.AsyncDatagramTransport,
    Generic[_T_SendDatagramTransport, _T_ReceiveDatagramTransport],
):
    """
    An asynchronous transport of unreliable packets of data that merges two transports.

    Extra attributes will be provided from both transports, with the receive stream providing the values in case of a conflict.

    .. versionadded:: 1.1
    """

    send_transport: _T_SendDatagramTransport
    """The write part of the transport."""

    receive_transport: _T_ReceiveDatagramTransport
    """The read part of the transport."""

    _backend: AsyncBackend = dataclass_field(init=False)

    def __post_init__(self) -> None:
        backend = _check_stapled_transports_consistency(self.send_transport, self.receive_transport)
        object.__setattr__(self, "_backend", backend)

    async def aclose(self) -> None:
        """
        Closes both transports.

        Warning:
            :meth:`aclose` performs a graceful close, waiting for the transports to close.

            If :meth:`aclose` is cancelled, the transports are closed using :func:`.aclose_forcefully`.
        """
        await _close_stapled_transports(self.send_transport, self.receive_transport)

    def is_closing(self) -> bool:
        """
        Checks if both the transports are closed or in the process of being closed.

        Returns:
            :data:`True` if the transports are closing.
        """
        return self.send_transport.is_closing() and self.receive_transport.is_closing()

    async def recv(self) -> bytes:
        """
        Calls :meth:`self.receive_transport.recv() <.AsyncDatagramReadTransport.recv>`.
        """
        return await self.receive_transport.recv()

    async def send(self, data: bytes | bytearray | memoryview) -> None:
        """
        Calls :meth:`self.send_transport.send() <.AsyncDatagramWriteTransport.send>`.
        """
        return await self.send_transport.send(data)

    @_utils.inherit_doc(_transports.AsyncDatagramTransport)
    def backend(self) -> AsyncBackend:
        return self._backend

    @property
    @_utils.inherit_doc(_transports.AsyncBaseTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.send_transport.extra_attributes,
            **self.receive_transport.extra_attributes,
        }


def _check_stapled_transports_consistency(
    send_transport: _transports.AsyncBaseTransport,
    receive_transport: _transports.AsyncBaseTransport,
) -> AsyncBackend:
    if (backend := send_transport.backend()) is not receive_transport.backend():
        raise RuntimeError("transport backend inconsistency")
    return backend


async def _close_stapled_transports(
    send_transport: _transports.AsyncBaseTransport,
    receive_transport: _transports.AsyncBaseTransport,
) -> None:
    async with contextlib.AsyncExitStack() as exit_stack:
        await exit_stack.enter_async_context(_try_graceful_close(receive_transport))
        await exit_stack.enter_async_context(_try_graceful_close(send_transport))


@contextlib.asynccontextmanager
async def _try_graceful_close(transport: _transports.AsyncBaseTransport) -> AsyncIterator[None]:
    try:
        yield
    except BaseException:
        await aclose_forcefully(transport)
        raise
    else:
        await transport.aclose()
