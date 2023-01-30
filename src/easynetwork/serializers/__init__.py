# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
    "DeserializeError",
    "EncryptorSerializer",
    "FileBasedIncrementalPacketSerializer",
    "FixedSizePacketSerializer",
    "IncrementalDeserializeError",
    "JSONDecoderConfig",
    "JSONEncoderConfig",
    "JSONSerializer",
    "NamedTupleStructSerializer",
    "PickleSerializer",
    "PicklerConfig",
    "UnpicklerConfig",
    "ZlibCompressorSerializer",
]


############ Package initialization ############
from .abc import *
from .base_stream import *
from .cbor import *
from .exceptions import *
from .json import *
from .pickle import *
from .struct import *
from .wrapper import *
