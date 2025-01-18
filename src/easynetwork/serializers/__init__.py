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
"""EasyNetwork's packet serializers module."""

from __future__ import annotations

__all__ = [
    "CBORSerializer",
    "JSONSerializer",
    "MessagePackSerializer",
    "NamedTupleStructSerializer",
    "PickleSerializer",
    "StringLineSerializer",
    "StructSerializer",
]


############ Package initialization ############
from .cbor import CBORSerializer
from .json import JSONSerializer
from .line import StringLineSerializer
from .msgpack import MessagePackSerializer
from .pickle import PickleSerializer
from .struct import NamedTupleStructSerializer, StructSerializer
