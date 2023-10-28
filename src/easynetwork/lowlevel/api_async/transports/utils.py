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
"""Low-level asynchronous transports module"""

from __future__ import annotations

__all__ = ["aclose_forcefully"]

from typing import TYPE_CHECKING

from .abc import AsyncBaseTransport

if TYPE_CHECKING:
    from ..backend.abc import AsyncBackend


async def aclose_forcefully(backend: AsyncBackend, transport: AsyncBaseTransport) -> None:
    """
    Close an async resource or async generator immediately, without blocking to do any graceful cleanup.

    Parameters:
        backend: the backend to use.
        transport: the transport to close.
    """
    with backend.move_on_after(0):
        await transport.aclose()
