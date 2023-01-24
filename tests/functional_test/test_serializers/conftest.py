# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

pytest.register_assert_rewrite(f"{__package__}.base")

from .base import BaseTestIncrementalSerializer, BaseTestSerializer

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet


def _make_pytest_params_from_sample(
    sample_list: list[tuple[Any, ...]],
    *,
    check_non_empty: bool = True,
) -> list[ParameterSet]:
    params: list[ParameterSet] = []

    for sample in sample_list:
        match sample:
            case (*p, id):
                params.append(pytest.param(*p, id=id))
            case _:
                raise AssertionError("Invalid tuple")

    if check_non_empty:
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
        if "invalid_complete_data" in metafunc.fixturenames:
            metafunc.parametrize(
                "invalid_complete_data",
                _make_pytest_params_from_sample(metafunc.cls.get_invalid_complete_data(), check_non_empty=False),
            )
    if issubclass(metafunc.cls, BaseTestIncrementalSerializer):
        try:
            argnames = BASE_INCREMENTAL_SERIALIZER_TEST_PARAMS[metafunc.definition.originalname]
        except KeyError:
            pass
        else:
            metafunc.parametrize(argnames, _make_pytest_params_from_sample(metafunc.cls.get_incremental_serialize_sample()))
        if "invalid_partial_data" in metafunc.fixturenames:
            if "expected_remaining_data" in metafunc.fixturenames:
                metafunc.parametrize(
                    ["invalid_partial_data", "expected_remaining_data"],
                    _make_pytest_params_from_sample(metafunc.cls.get_invalid_partial_data(), check_non_empty=False),
                )
            else:
                metafunc.parametrize(
                    "invalid_partial_data",
                    _make_pytest_params_from_sample(
                        [(p, id) for p, _, id in metafunc.cls.get_invalid_partial_data()],
                        check_non_empty=False,
                    ),
                )
        elif "expected_remaining_data" in metafunc.fixturenames:
            metafunc.parametrize(
                "expected_remaining_data",
                _make_pytest_params_from_sample(metafunc.cls.get_possible_remaining_data()),
            )
