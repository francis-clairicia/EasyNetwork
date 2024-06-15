from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.hookimpl(wrapper=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> Generator[None, int, int]:
    """determine how many workers to use based on how many tests were selected in the test explorer"""
    num_workers = yield
    if "vscode_pytest" in config.option.plugins:
        nb_launched_tests = len(config.option.file_or_dir)
        if nb_launched_tests == 1:
            # "0" means no workers
            return 0
        return min(num_workers, nb_launched_tests)
    return num_workers
