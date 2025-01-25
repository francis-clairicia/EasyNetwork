from __future__ import annotations

import os

import pytest

PAYLOAD_SIZE_LEVEL = "payload_size_level"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("benchmark")
    group.addoption(
        "--payload-size-level",
        dest=PAYLOAD_SIZE_LEVEL,
        type=lambda x: tuple(map(int, x.split(","))),
        default=(1, 10),
        help="a list of message size levels to use (in kilobytes)",
    )


def pytest_report_header(config: pytest.Config) -> list[str]:
    headers: list[str] = []
    addopts: str = os.environ.get("PYTEST_ADDOPTS", "")
    if addopts:
        headers.append(f"PYTEST_ADDOPTS: {addopts}")
    headers.append(
        f"Payload size levels: {', '.join(f'{payload_size}kb' for payload_size in config.getoption(PAYLOAD_SIZE_LEVEL))}"
    )
    return headers
