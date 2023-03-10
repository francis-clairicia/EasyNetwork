# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client module"""

from __future__ import annotations

__all__ = [
    "AbstractNetworkClient",
    "EmptyDatagramError",
    "TCPNetworkClient",
    "UDPNetworkClient",
    "UDPNetworkEndpoint",
]

from .abc import *
from .tcp import *
from .udp import *
