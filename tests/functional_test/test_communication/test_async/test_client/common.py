from __future__ import annotations

from ..socket import AsyncStreamSocket


async def sock_readline(sock: AsyncStreamSocket) -> bytes:
    buf: list[bytes] = []
    while True:
        chunk = await sock.recv(1024)
        if not chunk:
            break
        buf.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(buf)
