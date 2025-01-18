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
"""Common type variables for EasyNetwork's classes."""

from __future__ import annotations

__all__ = [
    "_T_Buffer",
    "_T_ReceivedDTOPacket",
    "_T_ReceivedPacket",
    "_T_Request",
    "_T_Response",
    "_T_SentDTOPacket",
    "_T_SentPacket",
]

import typing

if typing.TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_T_SentDTOPacket = typing.TypeVar("_T_SentDTOPacket")
_T_ReceivedDTOPacket = typing.TypeVar("_T_ReceivedDTOPacket")

_T_SentPacket = typing.TypeVar("_T_SentPacket")
_T_ReceivedPacket = typing.TypeVar("_T_ReceivedPacket")

_T_Request = typing.TypeVar("_T_Request")
_T_Response = typing.TypeVar("_T_Response")

_T_Buffer = typing.TypeVar("_T_Buffer", bound="WriteableBuffer")
