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
"""EasyNetwork's packet serializer module"""

from __future__ import annotations

__all__ = [
    "AbstractCompressorSerializer",
    "AbstractIncrementalPacketSerializer",
    "AbstractPacketSerializer",
    "AbstractStructSerializer",
    "AutoSeparatedPacketSerializer",
    "BZ2CompressorSerializer",
    "Base64EncodedSerializer",
    "CBORDecoderConfig",
    "CBOREncoderConfig",
    "CBORSerializer",
    "EncryptorSerializer",
    "FileBasedPacketSerializer",
    "FixedSizePacketSerializer",
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
    "ZlibCompressorSerializer",
]


############ Package initialization ############
from .abc import *
from .base_stream import *
from .cbor import *
from .json import *
from .line import *
from .msgpack import *
from .pickle import *
from .struct import *
from .wrapper import *
