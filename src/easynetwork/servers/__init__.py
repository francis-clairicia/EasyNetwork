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
"""Network server module"""

from __future__ import annotations

__all__ = [
    "AbstractAsyncNetworkServer",
    "AbstractNetworkServer",
    "AsyncBaseClientInterface",
    "AsyncDatagramClient",
    "AsyncDatagramRequestHandler",
    "AsyncStreamClient",
    "AsyncStreamRequestHandler",
    "AsyncTCPNetworkServer",
    "AsyncUDPNetworkServer",
    "INETClientAttribute",
    "NetworkServerThread",
    "StandaloneTCPNetworkServer",
    "StandaloneUDPNetworkServer",
    "SupportsEventSet",
]

from .abc import *
from .async_tcp import *
from .async_udp import *
from .handlers import *
from .standalone_tcp import *
from .standalone_udp import *
from .threads_helper import *
