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
"""Common type variables for EasyNetwork's classes"""

from __future__ import annotations

__all__ = [
    "_BufferT",
    "_DTOPacketT",
    "_PacketT",
    "_ReceivedPacketT",
    "_RequestT",
    "_ResponseT",
    "_SentPacketT",
]

import typing

if typing.TYPE_CHECKING:
    from _typeshed import WriteableBuffer

_DTOPacketT = typing.TypeVar("_DTOPacketT")

_SentPacketT = typing.TypeVar("_SentPacketT")
_ReceivedPacketT = typing.TypeVar("_ReceivedPacketT")
_PacketT = typing.TypeVar("_PacketT")

_RequestT = typing.TypeVar("_RequestT")
_ResponseT = typing.TypeVar("_ResponseT")

_BufferT = typing.TypeVar("_BufferT", bound="WriteableBuffer")
