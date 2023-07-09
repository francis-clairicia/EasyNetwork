from __future__ import annotations

import importlib.metadata as importlib_metadata

import pytest
import trove_classifiers


@pytest.fixture(scope="module")
def easynetwork_metadata() -> importlib_metadata.PackageMetadata:
    return importlib_metadata.metadata("easynetwork")


def test____project____classifiers_all_are_valids(easynetwork_metadata: importlib_metadata.PackageMetadata) -> None:
    unknown_classifiers = set(easynetwork_metadata.get_all("Classifier", [])).difference(trove_classifiers.classifiers)

    assert not unknown_classifiers
