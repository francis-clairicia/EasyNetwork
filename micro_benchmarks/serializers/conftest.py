from __future__ import annotations

import importlib.resources
import json
from typing import Any

import pytest

from ..conftest import PAYLOAD_SIZE_LEVEL

SAMPLES = importlib.resources.files(__package__) / "samples"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "json_object" in metafunc.fixturenames:
        metafunc.parametrize(
            "json_object",
            [f"data_{payload_size}kb.json" for payload_size in metafunc.config.getoption(PAYLOAD_SIZE_LEVEL)],
            indirect=True,
        )


@pytest.fixture(scope="package")
def json_object(request: pytest.FixtureRequest) -> Any:
    file = SAMPLES / str(request.param)
    return json.loads(file.read_text())


@pytest.fixture(scope="package")
def json_data(json_object: Any) -> bytes:
    return json.dumps(json_object, indent=None, separators=(",", ":")).encode() + b"\n"


@pytest.fixture(scope="package")
def cbor_data(json_object: Any) -> bytes:
    import cbor2

    return cbor2.dumps(json_object)


@pytest.fixture(scope="package")
def msgpack_data(json_object: Any) -> bytes:
    import msgpack

    return msgpack.packb(json_object)


@pytest.fixture(scope="package")
def pickle_data(json_object: Any) -> bytes:
    import pickle

    return pickle.dumps(json_object, fix_imports=False)
