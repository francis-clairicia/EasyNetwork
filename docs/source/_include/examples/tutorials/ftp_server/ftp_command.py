from __future__ import annotations

from enum import StrEnum, auto


class FTPCommand(StrEnum):
    """This is an enumeration of all the commands defined in RFC 959.

    If the client sends a command that is not one of these,
    the server will reply a 500 error code.

    If the server has not implemented one of these commands,
    it will reply a 502 error code.
    """

    @staticmethod
    def _generate_next_value_(
        name: str,
        start: int,
        count: int,
        last_values: list[str],
    ) -> str:
        assert name.isupper()
        return name

    ABOR = auto()
    ACCT = auto()
    ALLO = auto()
    APPE = auto()
    CDUP = auto()
    CWD = auto()
    DELE = auto()
    HELP = auto()
    LIST = auto()
    MKD = auto()
    MODE = auto()
    NOOP = auto()
    PASS = auto()
    PASV = auto()
    PORT = auto()
    PWD = auto()
    QUIT = auto()
    REIN = auto()
    REST = auto()
    RETR = auto()
    RMD = auto()
    RNFR = auto()
    RNTO = auto()
    SITE = auto()
    SMNT = auto()
    STAT = auto()
    STOR = auto()
    STOU = auto()
    STRU = auto()
    SYST = auto()
    TYPE = auto()
    USER = auto()
