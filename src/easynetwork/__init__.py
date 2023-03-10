# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""The easiest way to use sockets in Python

EasyNetwork is a high-level interface for networking in Python
"""

from __future__ import annotations

__all__ = [
    "AbstractNetworkClient",
    "AbstractNetworkServer",
    "AbstractRequestExecutor",
    "AbstractTCPNetworkServer",
    "AbstractUDPNetworkServer",
    "ConnectedClient",
    "EmptyDatagramError",
    "ForkingRequestExecutor",
    "TCPNetworkClient",
    "ThreadingRequestExecutor",
    "UDPNetworkClient",
    "UDPNetworkEndpoint",
]

__author__ = "FrankySnow9"
__contact__ = "clairicia.rcj.francis@gmail.com"
__copyright__ = "Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine"
__credits__ = ["FrankySnow9"]
__deprecated__ = False
__email__ = "clairicia.rcj.francis@gmail.com"
__license__ = "MIT"
__maintainer__ = "FrankySnow9"
__status__ = "Development"
__version__ = "1.0.0.dev0"


############ Package initialization ############
from .client import *
from .server import *
