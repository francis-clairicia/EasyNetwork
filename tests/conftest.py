# -*- coding: Utf-8 -*-

from __future__ import annotations

import random

from easynetwork.client.tcp import TCPNetworkClient
from easynetwork.client.udp import UDPNetworkClient, UDPNetworkEndpoint

random.seed(42)  # Fully deterministic random output

# Default __del__ implementation try to close client
setattr(TCPNetworkClient, "__del__", lambda self: None)
setattr(UDPNetworkClient, "__del__", lambda self: None)
setattr(UDPNetworkEndpoint, "__del__", lambda self: None)
