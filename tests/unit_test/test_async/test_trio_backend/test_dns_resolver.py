from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

    from pytest_mock import MockerFixture


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioDNSResolver:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_trio_connect_sock(mocker: MockerFixture) -> AsyncMock:
        import trio

        async def connect_sock_to_resolved_address(sock: Any, address: Any) -> None:
            await trio.lowlevel.checkpoint()

        return mocker.patch(
            "easynetwork.lowlevel.api_async.backend._trio._trio_utils.connect_sock_to_resolved_address",
            autospec=True,
            side_effect=connect_sock_to_resolved_address,
        )

    @pytest.fixture
    @staticmethod
    def dns_resolver() -> TrioDNSResolver:
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        return TrioDNSResolver()

    async def test____connect_socket____uses_internal_trio_connect_sock(
        self,
        dns_resolver: TrioDNSResolver,
        mock_tcp_socket: MagicMock,
        mock_trio_connect_sock: AsyncMock,
    ) -> None:
        # Arrange

        # Act
        await dns_resolver.connect_socket(mock_tcp_socket, ("127.0.0.1", 12345))

        # Assert
        mock_trio_connect_sock.assert_awaited_once_with(mock_tcp_socket, ("127.0.0.1", 12345))
