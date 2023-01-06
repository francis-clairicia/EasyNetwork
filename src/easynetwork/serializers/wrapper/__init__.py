# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""EasyNetwork's packet serializer module"""

from __future__ import annotations

__all__ = [
    "BZ2CompressorSerializer",
    "Base64EncodedSerializer",
    "ZlibCompressorSerializer",
]

from .base64 import *
from .compressor import *
