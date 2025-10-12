from __future__ import annotations

import sys
from socket import socket as Socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from socket import _RetAddress


def readline(sock: Socket) -> bytes:
    buf: list[bytes] = []
    while True:
        chunk = sock.recv(1024)
        if not chunk:
            break
        buf.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(buf)


if sys.platform != "win32":
    from easynetwork.lowlevel.socket import SocketAncillary

    try:
        from socket import CMSG_SPACE
    except ImportError:
        from socket import CMSG_LEN as CMSG_SPACE

    def readmsg(sock: Socket) -> tuple[bytes, SocketAncillary, _RetAddress]:
        chunk, cmsgs, flags, address = sock.recvmsg(1024, CMSG_SPACE(8192))
        assert flags == 0, "messages truncated"
        ancillary = SocketAncillary()
        ancillary.update_from_raw(cmsgs)
        return chunk, ancillary, address
