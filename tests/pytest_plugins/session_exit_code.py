# -*- coding: utf-8 -*-

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suppress-no-test-exit-code",
        action="store_true",
        default=False,
        help='Suppress the "no tests collected" exit code.',
    )


@pytest.hookimpl(trylast=True)  # type: ignore[misc]
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if session.config.getoption("--suppress-no-test-exit-code"):
        if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
            session.exitstatus = pytest.ExitCode.OK
