from __future__ import annotations

import pytest

from ....fixtures.trio import trio_fixture


@pytest.mark.feature_trio
class TestTrioBackend:

    @trio_fixture
    @staticmethod
    async def async_fixture() -> int:
        import trio

        await trio.sleep(0)
        return 42

    async def test____place_holder____with_trio(self, async_fixture: int) -> None:
        import trio

        await trio.sleep(0.5)

        assert async_fixture == 42
