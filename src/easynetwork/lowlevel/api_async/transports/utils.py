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
"""Low-level asynchronous transports tools module."""

from __future__ import annotations

__all__ = ["aclose_forcefully"]

from abc import abstractmethod
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol

from ... import _utils
from .abc import AsyncBaseTransport

if TYPE_CHECKING:
    from ..backend.abc import AsyncBackend


class _TransportLike(Protocol):

    @abstractmethod
    @_utils.inherit_doc(AsyncBaseTransport)
    def aclose(self) -> Awaitable[None]: ...

    @abstractmethod
    @_utils.inherit_doc(AsyncBaseTransport)
    def backend(self) -> AsyncBackend: ...


async def aclose_forcefully(transport: _TransportLike) -> None:
    """
    Close an async transport immediately, without blocking to do any graceful cleanup.

    .. versionchanged:: 1.1
        `transport` can now be any closeable object with a ``backend()`` method.

    Parameters:
        transport: the transport to close.
    """
    with transport.backend().move_on_after(0):
        await transport.aclose()
