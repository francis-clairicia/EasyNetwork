# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network client exceptions module"""

from __future__ import annotations

__all__ = ["ClientClosedError"]


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client"""
