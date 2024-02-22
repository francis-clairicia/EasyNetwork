from __future__ import annotations

import os


def pytest_report_header() -> list[str]:
    addopts: str = os.environ.get("PYTEST_ADDOPTS", "")
    if not addopts:
        return []
    return [f"PYTEST_ADDOPTS: {addopts}"]
