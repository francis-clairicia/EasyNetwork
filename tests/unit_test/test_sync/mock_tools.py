from __future__ import annotations

import itertools
import math
import selectors
import time
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import weak_method_proxy
from easynetwork.lowlevel.api_sync.transports.abc import BaseTransport
from easynetwork.lowlevel.api_sync.transports.base_selector import SelectorBaseTransport
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


fd_count = itertools.count(start=123)


def make_transport_mock(*, mocker: MockerFixture, spec: Any) -> MagicMock:
    assert issubclass(spec, BaseTransport)
    mock_transport = mocker.NonCallableMagicMock(spec=spec)
    mock_transport.is_closed.return_value = False

    def close_side_effect() -> None:
        mock_transport.is_closed.return_value = True
        if issubclass(spec, SelectorBaseTransport):
            mock_transport.read_fileno.return_value = -1
            mock_transport.write_fileno.return_value = -1

    mock_transport.abort.side_effect = close_side_effect
    mock_transport.close.side_effect = close_side_effect
    mock_transport.extra_attributes = {}
    mock_transport.extra.side_effect = weak_method_proxy(TypedAttributeProvider.extra.__get__(mock_transport))

    if issubclass(spec, SelectorBaseTransport):
        fd = next(fd_count)
        mock_transport.read_fileno.return_value = fd
        mock_transport.write_fileno.return_value = fd

    return mock_transport


class FakeSelector(selectors.SelectSelector):

    # Always available
    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        time.sleep(min(0.1, math.inf if timeout is None else timeout))
        return [(key, key.events) for key in self.get_map().values()]
