from __future__ import annotations

import asyncio
from socket import socket as Socket


async def sock_readline(loop: asyncio.AbstractEventLoop, sock: Socket) -> bytes:
    buf: list[bytes] = []
    while True:
        chunk = await loop.sock_recv(sock, 1024)
        if not chunk:
            break
        buf.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(buf)
