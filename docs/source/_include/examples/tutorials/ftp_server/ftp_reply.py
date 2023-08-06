from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FTPReply:
    """Dataclass defining an FTP reply."""

    code: int
    """The reply code."""

    message: str
    """A line of text following the reply code."""

    @staticmethod
    def ok() -> FTPReply:
        return FTPReply(200, "Command okay.")

    @staticmethod
    def service_ready_for_new_user() -> FTPReply:
        return FTPReply(220, "Service ready for new user.")

    @staticmethod
    def connection_close(*, unexpected: bool = False) -> FTPReply:
        if unexpected:
            return FTPReply(421, "Service not available, closing control connection.")
        return FTPReply(221, "Service closing control connection.")

    @staticmethod
    def syntax_error() -> FTPReply:
        return FTPReply(500, "Syntax error, command unrecognized.")

    @staticmethod
    def not_implemented_error() -> FTPReply:
        return FTPReply(502, "Command not implemented.")
