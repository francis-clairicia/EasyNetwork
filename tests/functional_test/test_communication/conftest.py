from __future__ import annotations

import ssl
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from functools import partial
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM, has_ipv6 as HAS_IPV6, socket as Socket
from typing import TYPE_CHECKING, Any

from easynetwork.protocol import AnyStreamProtocolType, BufferedStreamProtocol, DatagramProtocol, StreamProtocol

import pytest

from ...fixtures.socket import AF_UNIX_or_skip
from .serializer import BadSerializeStringSerializer, NotGoodStringSerializer, StringSerializer

if TYPE_CHECKING:
    import trustme


_FAMILY_TO_LOCALHOST: dict[int, str] = {
    AF_INET: "127.0.0.1",
    AF_INET6: "::1",
}

_SUPPORTED_FAMILIES = tuple(_FAMILY_TO_LOCALHOST)


@pytest.fixture(params=_SUPPORTED_FAMILIES, ids=lambda f: str(getattr(f, "name", f)))
def socket_family(request: Any) -> int:
    family: str | int = request.param
    if isinstance(family, str):
        import socket as _socket

        family = _socket.AddressFamily(getattr(_socket, family))
    return family


@pytest.fixture
def localhost_ip(socket_family: int) -> str:
    return _FAMILY_TO_LOCALHOST[socket_family]


@pytest.fixture
def inet_socket_factory(socket_family: int) -> Iterator[Callable[[int], Socket]]:
    if not HAS_IPV6 and socket_family == AF_INET6:
        pytest.skip("socket.has_ipv6 is False")

    socket_stack = ExitStack()

    def inet_socket_factory(type: int) -> Socket:
        return socket_stack.enter_context(Socket(socket_family, type))

    with socket_stack:
        yield inet_socket_factory


@pytest.fixture
def tcp_socket_factory(inet_socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(inet_socket_factory, SOCK_STREAM)


@pytest.fixture
def udp_socket_factory(inet_socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(inet_socket_factory, SOCK_DGRAM)


@pytest.fixture
def unix_socket_factory() -> Iterator[Callable[[int], Socket]]:
    from ...fixtures.socket import AF_UNIX_or_skip

    socket_stack = ExitStack()

    def unix_socket_factory(type: int) -> Socket:
        return socket_stack.enter_context(Socket(AF_UNIX_or_skip(), type))

    with socket_stack:
        yield unix_socket_factory


@pytest.fixture
def unix_stream_socket_factory(unix_socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(unix_socket_factory, SOCK_STREAM)


@pytest.fixture
def unix_datagram_socket_factory(unix_socket_factory: Callable[[int], Socket]) -> Callable[[], Socket]:
    return partial(unix_socket_factory, SOCK_DGRAM)


@pytest.fixture(params=["data"])
def datagram_protocol(request: pytest.FixtureRequest) -> DatagramProtocol[str, str]:
    match request.param:
        case "data":
            return DatagramProtocol(StringSerializer())
        case "invalid":
            return DatagramProtocol(NotGoodStringSerializer())
        case "bad_serialize":
            return DatagramProtocol(BadSerializeStringSerializer())
        case _:
            pytest.fail("Invalid parameter")


@pytest.fixture(params=["data", "buffered"])
def stream_protocol(request: pytest.FixtureRequest) -> AnyStreamProtocolType[str, str]:
    match request.param:
        case "data":
            return StreamProtocol(StringSerializer())
        case "buffered":
            return BufferedStreamProtocol(StringSerializer())
        case "invalid":
            return StreamProtocol(NotGoodStringSerializer())
        case "invalid_buffered":
            return BufferedStreamProtocol(NotGoodStringSerializer())
        case "bad_serialize":
            return StreamProtocol(BadSerializeStringSerializer())
        case _:
            pytest.fail("Invalid parameter")


# Origin: https://gist.github.com/4325783, by Geert Jansen.  Public domain.
# Cannot use socket.socketpair() vendored with Python on unix since it is required to use AF_UNIX family :)
@pytest.fixture
def inet_socket_pair(localhost_ip: str, tcp_socket_factory: Callable[[], Socket]) -> Iterator[tuple[Socket, Socket]]:
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
        except:  # noqa: E722
            csock.close()
            raise
    finally:
        lsock.close()
    with ssock:  # csock will be closed later by tcp_socket_factory() teardown
        yield ssock, csock


@pytest.fixture
def unix_socket_pair() -> Iterator[tuple[Socket, Socket]]:
    from socket import socketpair

    from easynetwork.lowlevel import _unix_utils

    left_sock, right_sock = socketpair(AF_UNIX_or_skip())
    with left_sock, right_sock:
        if _unix_utils.platform_supports_automatic_socket_bind():
            left_sock.bind("")
            right_sock.bind("")

        yield left_sock, right_sock


@pytest.fixture(scope="session")
def ssl_certificate_authority() -> trustme.CA | None:
    try:
        import trustme
    except ModuleNotFoundError:
        return None
    else:
        return trustme.CA()


@pytest.fixture(scope="session")
def server_certificate(ssl_certificate_authority: trustme.CA | None) -> trustme.LeafCert | None:
    if ssl_certificate_authority is None:
        return None
    return ssl_certificate_authority.issue_cert("*.example.com")


@pytest.fixture(scope="session")
def client_certificate(ssl_certificate_authority: trustme.CA | None) -> trustme.LeafCert | None:
    if ssl_certificate_authority is None:
        return None
    return ssl_certificate_authority.issue_cert("client@example.com")


@pytest.fixture
def server_ssl_context(
    ssl_certificate_authority: trustme.CA | None,
    server_certificate: trustme.LeafCert | None,
) -> ssl.SSLContext | None:
    if ssl_certificate_authority is None or server_certificate is None:
        return None

    server_ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    server_certificate.configure_cert(server_ssl_context)
    ssl_certificate_authority.configure_trust(server_ssl_context)

    server_ssl_context.verify_mode = ssl.CERT_REQUIRED

    return server_ssl_context


@pytest.fixture
def client_ssl_context(
    ssl_certificate_authority: trustme.CA | None,
    client_certificate: trustme.LeafCert | None,
) -> ssl.SSLContext | None:
    if ssl_certificate_authority is None or client_certificate is None:
        return None

    client_ssl_context = ssl.create_default_context()

    client_certificate.configure_cert(client_ssl_context)
    ssl_certificate_authority.configure_trust(client_ssl_context)

    return client_ssl_context
