from __future__ import annotations

from socket import socket as Socket


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
