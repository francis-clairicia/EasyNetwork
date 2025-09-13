from __future__ import annotations


# Tell pytest-retry plugin to skip KeyboardInterrupt
# (I wonder why this isn't the default setting...)
def pytest_set_excluded_exceptions() -> tuple[type[BaseException], ...]:
    return (KeyboardInterrupt,)
