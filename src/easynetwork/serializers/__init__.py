# -*- coding: utf-8 -*-
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
