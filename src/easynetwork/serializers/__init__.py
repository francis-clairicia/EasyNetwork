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
"""EasyNetwork's packet serializers module"""

from __future__ import annotations

__all__ = [
    "AbstractStructSerializer",
    "CBORDecoderConfig",
    "CBOREncoderConfig",
    "CBORSerializer",
    "JSONDecoderConfig",
    "JSONEncoderConfig",
    "JSONSerializer",
    "MessagePackSerializer",
    "MessagePackerConfig",
    "MessageUnpackerConfig",
    "NamedTupleStructSerializer",
    "PickleSerializer",
    "PicklerConfig",
    "StringLineSerializer",
    "UnpicklerConfig",
]


############ Package initialization ############
from .cbor import *
from .json import *
from .line import *
from .msgpack import *
from .pickle import *
from .struct import *
