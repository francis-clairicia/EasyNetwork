from __future__ import annotations

import os
import random
import threading
from typing import TYPE_CHECKING

from easynetwork.lowlevel._lock import ForkSafeLock

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestForkSafeLock:
    @pytest.fixture(scope="class")
    @staticmethod
    def RLock() -> type[threading.RLock]:
        return type(threading.RLock())

    @pytest.fixture(scope="class")
    @staticmethod
    def Lock() -> type[threading.Lock]:
        return type(threading.Lock())

    def test____dunder_init____create_threading_RLock_by_default(self, RLock: type[threading.RLock]) -> None:
        # Arrange
        safe_lock = ForkSafeLock()

        # Act
        lock = safe_lock.get()

        # Assert
        assert isinstance(lock, RLock)

    def test____dunder_init____custom_lock_factory(self, mocker: MockerFixture, Lock: type[threading.Lock]) -> None:
        # Arrange
        lock_factory: MagicMock = mocker.MagicMock(side_effect=threading.Lock)
        safe_lock: ForkSafeLock[threading.Lock] = ForkSafeLock(lock_factory)

        # Act
        lock = safe_lock.get()

        # Assert
        lock_factory.assert_called_once_with()
        assert isinstance(lock, Lock)

    def test____get____always_return_the_same_lock_object(self, mocker: MockerFixture) -> None:
        # Arrange
        lock_factory: MagicMock = mocker.MagicMock(side_effect=threading.Lock)
        safe_lock: ForkSafeLock[threading.Lock] = ForkSafeLock(lock_factory)
        lock = safe_lock.get()
        lock_factory.reset_mock()

        # Act & Assert
        assert all(safe_lock.get() is lock for _ in range(100))

        # Assert
        lock_factory.assert_not_called()

    def test____get____create_a_new_lock_if_the_pid_is_different(self, mocker: MockerFixture) -> None:
        # Arrange
        lock_factory: MagicMock = mocker.MagicMock(side_effect=threading.Lock)
        safe_lock: ForkSafeLock[threading.Lock] = ForkSafeLock(lock_factory)
        older_lock = safe_lock.get()
        lock_factory.reset_mock()

        # Act & Assert
        mocker.patch("os.getpid", return_value=os.getpid() + random.randint(1, 20))  # Simulate os.fork()
        new_lock = safe_lock.get()
        assert new_lock is not older_lock
        assert all(safe_lock.get() is new_lock for _ in range(100))

        # Assert
        lock_factory.assert_called_once_with()
