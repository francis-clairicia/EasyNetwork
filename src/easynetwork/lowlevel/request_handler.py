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
"""Low-level server's helpers module for request handlers.

.. versionadded:: NEXT_VERSION
"""

from __future__ import annotations

__all__ = ["RecvAncillaryDataParams", "RecvParams"]

import dataclasses
from collections.abc import Callable
from typing import Any, NamedTuple


class RecvAncillaryDataParams(NamedTuple):
    """
    Parameters for ancillary data reception by server.

    .. versionadded:: NEXT_VERSION
    """

    bufsize: int
    """Read buffer size for ancillary data."""

    data_received: Callable[[Any], object]
    """Action to perform on ancillary data reception."""


@dataclasses.dataclass(kw_only=True, frozen=True, slots=True)
class RecvParams:
    """
    Parameters yielded by request handlers for servers.

    .. versionadded:: NEXT_VERSION
    """

    timeout: float | None = None
    """Timeout (in seconds) for blocking operations. Optional."""

    recv_with_ancillary: RecvAncillaryDataParams | None = None
    """Ask server to handle ancillary data sent along with the packet. May not be supported by all transports."""
