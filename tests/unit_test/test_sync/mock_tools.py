from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import weak_method_proxy
from easynetwork.lowlevel.api_sync.transports.abc import BaseTransport
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


def make_transport_mock(*, mocker: MockerFixture, spec: Any) -> MagicMock:
    assert issubclass(spec, BaseTransport)
    mock_transport = mocker.NonCallableMagicMock(spec=spec)
    mock_transport.is_closed.return_value = False

    def close_side_effect() -> None:
        mock_transport.is_closed.return_value = True

    mock_transport.close.side_effect = close_side_effect
    mock_transport.extra_attributes = {}
    mock_transport.extra.side_effect = weak_method_proxy(TypedAttributeProvider.extra.__get__(mock_transport))
    return mock_transport
