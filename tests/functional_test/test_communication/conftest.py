# -*- coding: utf-8 -*-

from __future__ import annotations

import ssl
from contextlib import ExitStack
from functools import partial
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM, has_ipv6 as HAS_IPV6, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.protocol import DatagramProtocol, StreamProtocol

import pytest
import trustme

from .serializer import StringSerializer

_FAMILY_TO_LOCALHOST: dict[int, str] = {
    AF_INET: "127.0.0.1",
    AF_INET6: "::1",
}

_SUPPORTED_FAMILIES = tuple(_FAMILY_TO_LOCALHOST)


@pytest.fixture(params=_SUPPORTED_FAMILIES, ids=lambda f: str(getattr(f, "name", f)))
def socket_family(request: Any) -> int:
    return request.param


@pytest.fixture
def localhost_ip(socket_family: int) -> str:
    return _FAMILY_TO_LOCALHOST[socket_family]


@pytest.fixture
def socket_factory(socket_family: int) -> Iterator[Callable[[int], Socket]]:
    if not HAS_IPV6:
        pytest.skip("socket.has_ipv6 is False")

    socket_stack = ExitStack()

    def socket_factory(type: int) -> Socket:
        return socket_stack.enter_context(Socket(socket_family, type))

    with socket_stack:
        yield socket_factory


@pytest.fixture
def tcp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_STREAM)


@pytest.fixture
def udp_socket_factory(socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(socket_factory, SOCK_DGRAM)


@pytest.fixture(scope="package")
def stream_protocol() -> StreamProtocol[str, str]:
    return StreamProtocol(StringSerializer())


@pytest.fixture(scope="package")
def datagram_protocol() -> DatagramProtocol[str, str]:
    return DatagramProtocol(StringSerializer())


# Origin: https://gist.github.com/4325783, by Geert Jansen.  Public domain.
# Cannot use socket.socketpair() vendored with Python on unix since it is required to use AF_UNIX family :)
@pytest.fixture
def socket_pair(localhost_ip: str, tcp_socket_factory: Callable[[], Socket]) -> Iterator[tuple[Socket, Socket]]:
    # We create a connected TCP socket. Note the trick with
    # setblocking(False) that prevents us from having to create a thread.
    lsock = tcp_socket_factory()
    try:
        lsock.bind((localhost_ip, 0))
        lsock.listen()
        # On IPv6, ignore flow_info and scope_id
        addr, port = lsock.getsockname()[:2]
        csock = tcp_socket_factory()
        try:
            csock.setblocking(False)
            try:
                csock.connect((addr, port))
            except (BlockingIOError, InterruptedError):
                pass
            csock.setblocking(True)
            ssock, _ = lsock.accept()
        except:  # noqa
            csock.close()
            raise
    finally:
        lsock.close()
    with ssock:  # csock will be closed later by tcp_socket_factory() teardown
        yield ssock, csock


@pytest.fixture(scope="session")
def ssl_certificate_authority() -> trustme.CA:
    return trustme.CA()


@pytest.fixture(scope="session")
def server_certificate(ssl_certificate_authority: trustme.CA) -> trustme.LeafCert:
    return ssl_certificate_authority.issue_cert("*.example.com")


@pytest.fixture(scope="session")
def client_certificate(ssl_certificate_authority: trustme.CA) -> trustme.LeafCert:
    return ssl_certificate_authority.issue_cert("client@example.com")


@pytest.fixture
def server_ssl_context(ssl_certificate_authority: trustme.CA, server_certificate: trustme.LeafCert) -> ssl.SSLContext:
    server_ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    server_certificate.configure_cert(server_ssl_context)
    ssl_certificate_authority.configure_trust(server_ssl_context)

    server_ssl_context.verify_mode = ssl.CERT_REQUIRED

    return server_ssl_context


@pytest.fixture
def client_ssl_context(ssl_certificate_authority: trustme.CA, client_certificate: trustme.LeafCert) -> ssl.SSLContext:
    client_ssl_context = ssl.create_default_context()

    client_certificate.configure_cert(client_ssl_context)
    ssl_certificate_authority.configure_trust(client_ssl_context)

    return client_ssl_context
