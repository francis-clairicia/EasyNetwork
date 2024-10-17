from __future__ import annotations

import pathlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._unix_utils import (
    LazyPeerCredsContainer,
    check_unix_socket_family,
    convert_optional_unix_socket_address,
    convert_unix_socket_address,
    is_unix_socket_family,
    platform_supports_automatic_socket_bind,
)
from easynetwork.lowlevel.socket import UnixCredentials, UnixSocketAddress

import pytest

from tests.tools import PlatformMarkers

from ...fixtures.socket import socket_family_or_skip
from .._utils import unsupported_families
from ..base import UNIX_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(params=list(UNIX_FAMILIES))
def socket_family(request: pytest.FixtureRequest) -> Any:
    return socket_family_or_skip(request.param)


@pytest.mark.parametrize("socket_family", list(UNIX_FAMILIES), indirect=True)
def test____check_unix_socket_family____valid_family(socket_family: int) -> None:
    # Arrange

    # Act
    check_unix_socket_family(socket_family)

    # Assert
    ## There is no exception


@pytest.mark.parametrize("socket_family", list(unsupported_families(UNIX_FAMILIES)), indirect=True)
def test____check_unix_socket_family____invalid_family(socket_family: int) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Only these families are supported: AF_UNIX$"):
        check_unix_socket_family(socket_family)


def test____is_unix_socket_family____AF_UNIX_defined(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import socket
    from enum import IntEnum

    class AddressFamily(IntEnum):
        AF_UNIX = 1
        AF_INET = 2
        AF_INET6 = 10

    monkeypatch.setattr("socket.AddressFamily", AddressFamily)
    monkeypatch.setattr("socket.AF_UNIX", AddressFamily.AF_UNIX, raising=False)
    monkeypatch.setattr("socket.AF_INET", AddressFamily.AF_INET)
    monkeypatch.setattr("socket.AF_INET6", AddressFamily.AF_INET6)

    # Act & Assert
    assert is_unix_socket_family(getattr(socket, "AF_UNIX"))
    assert not is_unix_socket_family(socket.AF_INET)
    assert not is_unix_socket_family(socket.AF_INET6)


def test____is_unix_socket_family____AF_UNIX_undefined(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import socket
    from enum import IntEnum

    class AddressFamily(IntEnum):
        AF_INET = 2
        AF_INET6 = 10

    monkeypatch.setattr("socket.AddressFamily", AddressFamily)
    monkeypatch.delattr("socket.AF_UNIX", raising=False)
    monkeypatch.setattr("socket.AF_INET", AddressFamily.AF_INET)
    monkeypatch.setattr("socket.AF_INET6", AddressFamily.AF_INET6)

    # Act & Assert
    assert not is_unix_socket_family(socket.AF_INET)
    assert not is_unix_socket_family(socket.AF_INET6)


@pytest.mark.parametrize(
    ["input", "expected_output"],
    [
        pytest.param("/path/to/sock", "/path/to/sock"),
        pytest.param(pathlib.Path("/path/to/sock"), "/path/to/sock"),
        pytest.param(UnixSocketAddress.from_pathname("/path/to/sock"), "/path/to/sock"),
        pytest.param(b"\0abstract", b"\0abstract"),
        pytest.param(UnixSocketAddress.from_abstract_name(b"abstract"), b"\0abstract"),
        pytest.param("", ""),
        pytest.param(UnixSocketAddress(), ""),
    ],
)
@pytest.mark.parametrize("conversion_func", [convert_unix_socket_address, convert_optional_unix_socket_address])
@PlatformMarkers.skipif_platform_win32
def test_____convert_unix_socket_address____transform_to_raw_address(
    input: str | pathlib.Path | bytes | UnixSocketAddress,
    expected_output: str | bytes,
    conversion_func: Callable[[str | pathlib.Path | bytes | UnixSocketAddress], str | bytes],
) -> None:
    # Arrange

    # Act
    output = conversion_func(input)

    # Assert
    assert type(output) is type(expected_output)
    assert output == expected_output


@PlatformMarkers.skipif_platform_win32
def test_____convert_optional_unix_socket_address____skip_None() -> None:
    # Arrange

    # Act
    output = convert_optional_unix_socket_address(None)

    # Assert
    assert output is None


@pytest.mark.parametrize("platform", ["linux"])
def test____platform_supports_automatic_socket_bind____supported(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr("sys.platform", platform)

    # Act & Assert
    assert platform_supports_automatic_socket_bind()


@pytest.mark.parametrize("platform", ["darwin", "freebsdXX", "openbsdXX", "netbsdXX", "dragonflyXX"])
def test____platform_supports_automatic_socket_bind_____not_supported(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr("sys.platform", platform)

    # Act & Assert
    assert not platform_supports_automatic_socket_bind()


class TestLazyPeerCredsContainer:
    @pytest.fixture
    @staticmethod
    def get_peer_credentials(mocker: MockerFixture) -> MagicMock:
        stub = mocker.stub(name="get_peer_credentials")
        stub.return_value = UnixCredentials(12345, 1001, 1001)
        return stub

    def test____get____compute_credentials(
        self,
        mock_unix_stream_socket: MagicMock,
        get_peer_credentials: MagicMock,
    ) -> None:
        # Arrange
        peer_creds_container = LazyPeerCredsContainer()

        # Act
        peer_creds = peer_creds_container.get(mock_unix_stream_socket, get_peer_credentials)

        # Assert
        assert peer_creds.pid == 12345
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1001
        get_peer_credentials.assert_called_once_with(mock_unix_stream_socket)

    def test____get____cache_value(
        self,
        mock_unix_stream_socket: MagicMock,
        get_peer_credentials: MagicMock,
    ) -> None:
        # Arrange
        peer_creds_container = LazyPeerCredsContainer()
        cached_peer_creds = peer_creds_container.get(mock_unix_stream_socket, get_peer_credentials)
        get_peer_credentials.reset_mock()

        # Act
        peer_creds_1 = peer_creds_container.get(mock_unix_stream_socket, get_peer_credentials)
        peer_creds_2 = peer_creds_container.get(mock_unix_stream_socket, get_peer_credentials)
        peer_creds_3 = peer_creds_container.get(mock_unix_stream_socket, get_peer_credentials)

        # Assert
        assert peer_creds_1 is peer_creds_2 is peer_creds_3 is cached_peer_creds
        get_peer_credentials.assert_not_called()
