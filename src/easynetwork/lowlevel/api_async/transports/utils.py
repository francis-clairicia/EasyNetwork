# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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

from .abc import AsyncBaseTransport


async def aclose_forcefully(transport: AsyncBaseTransport) -> None:
    """
    Close an async resource or async generator immediately, without blocking to do any graceful cleanup.

    Parameters:
        transport: the transport to close.
    """
    with transport.backend().move_on_after(0):
        await transport.aclose()
