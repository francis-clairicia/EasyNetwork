# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

pytest.register_assert_rewrite(f"{__package__}.base")

from .base import BaseTestIncrementalSerializer, BaseTestSerializer

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet


def _make_pytest_params_from_sample(sample_list: list[tuple[Any, bytes] | tuple[Any, bytes, str]]) -> list[ParameterSet]:
    params: list[ParameterSet] = []

    for sample in sample_list:
        match sample:
            case (packet, data):
                params.append(pytest.param(packet, data))
            case (packet, data, id):
                params.append(pytest.param(packet, data, id=id))
            case _:
                raise AssertionError("Invalid tuple")

    assert len(params) > 0
    return params


def _make_pytest_params_from_remaining_data(sample_list: list[bytes | tuple[bytes, str]]) -> list[ParameterSet]:
    params: list[ParameterSet] = []

    for sample in sample_list:
        match sample:
            case bytes() as data:
                assert len(data) > 0
                params.append(pytest.param(data))
            case (data, id):
                assert len(data) > 0
                params.append(pytest.param(data, id=id))
            case _:
                raise AssertionError("Invalid object")

    assert len(params) > 0
    return params


BASE_SERIALIZER_TEST_PARAMS = {
    "test____serialize____sample": ["packet", "expected_data"],
    "test____deserialize____sample": ["expected_packet", "data"],
}

BASE_INCREMENTAL_SERIALIZER_TEST_PARAMS = {
    "test____incremental_serialize____concatenated_chunks": ["packet", "expected_data"],
    "test____incremental_deserialize____one_shot_chunk": ["expected_packet", "data"],
    "test____incremental_deserialize____with_remaining_data": ["expected_packet", "data"],
    "test____incremental_deserialize____give_chunk_byte_per_byte": ["expected_packet", "data"],
}


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if issubclass(metafunc.cls, BaseTestSerializer):
        try:
            argnames = BASE_SERIALIZER_TEST_PARAMS[metafunc.definition.originalname]
        except KeyError:
            pass
        else:
            metafunc.parametrize(argnames, _make_pytest_params_from_sample(metafunc.cls.get_oneshot_serialize_sample()))
    if issubclass(metafunc.cls, BaseTestIncrementalSerializer):
        try:
            argnames = BASE_INCREMENTAL_SERIALIZER_TEST_PARAMS[metafunc.definition.originalname]
        except KeyError:
            pass
        else:
            metafunc.parametrize(argnames, _make_pytest_params_from_sample(metafunc.cls.get_incremental_serialize_sample()))
            if "expected_remaining_data" in metafunc.fixturenames:
                metafunc.parametrize(
                    "expected_remaining_data",
                    _make_pytest_params_from_remaining_data(metafunc.cls.get_possible_remaining_data()),
                )
