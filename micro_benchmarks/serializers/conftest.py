from __future__ import annotations

import importlib.resources
import json
from typing import Any

import pytest

SAMPLES = importlib.resources.files(__package__) / "samples"


@pytest.fixture(scope="package", params=["data_1kb.json", "data_10kb.json"])
def json_object(request: pytest.FixtureRequest) -> Any:
    file = SAMPLES / str(request.param)
    return json.loads(file.read_text())


@pytest.fixture(scope="module")
def json_data(json_object: Any) -> bytes:
    return json.dumps(json_object, indent=None, separators=(",", ":")).encode() + b"\n"


@pytest.fixture(scope="module")
def cbor_data(json_object: Any) -> bytes:
    import cbor2

    return cbor2.dumps(json_object)


@pytest.fixture(scope="module")
def msgpack_data(json_object: Any) -> bytes:
    import msgpack

    return msgpack.packb(json_object)


@pytest.fixture(scope="module")
def pickle_data(json_object: Any) -> bytes:
    import pickle

    return pickle.dumps(json_object, fix_imports=False)
