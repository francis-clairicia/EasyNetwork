from __future__ import annotations

import importlib.resources
import json
from typing import Any

import pytest

DATA_FILE = importlib.resources.files(__package__) / "samples" / "data.json"


@pytest.fixture(scope="module")
def json_object() -> Any:
    return json.loads(DATA_FILE.read_text())


@pytest.fixture(scope="module")
def json_data(json_object: Any) -> bytes:
    return json.dumps(json_object, indent=None, separators=(",", ":")).encode() + b"\n"
