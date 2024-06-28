from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ftp_command import FTPCommand


@dataclass(frozen=True, match_args=True)
class FTPRequest:
    """Dataclass defining an FTP request."""

    command: FTPCommand
    """Command name."""

    args: tuple[Any, ...]
    """Command arguments sequence. May be empty."""
