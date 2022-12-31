# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2022, Francis Clairicia-Rose-Claire-Josephine
#
#
# mypy: no-warn-unused-ignores
"""Network client module"""

from __future__ import annotations

__all__ = ["AbstractNetworkClient", "TCPInvalidPacket", "TCPNetworkClient", "UDPInvalidPacket", "UDPNetworkClient"]

from .abc import *
from .tcp import *
from .udp import *
