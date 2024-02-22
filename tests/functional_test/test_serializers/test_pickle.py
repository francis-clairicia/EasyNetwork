from __future__ import annotations

import dataclasses
import pickle
import pickletools
from typing import Any, final

from easynetwork.serializers.pickle import PicklerConfig, PickleSerializer, UnpicklerConfig

import pytest

from .base import BaseTestSerializerExtraData
from .samples.pickle import SAMPLES

ALL_PROTOCOLS: tuple[int, ...] = tuple(range(0, pickle.HIGHEST_PROTOCOL + 1))


@final
class TestPickleSerializer(BaseTestSerializerExtraData):
    @pytest.fixture(scope="class", params=ALL_PROTOCOLS, ids=lambda p: f"pickle_data_protocol=={p}")
    @staticmethod
    def pickle_data_protocol(request: Any) -> int:
        return request.param

    #### Serializers

    @pytest.fixture(scope="class")
    @staticmethod
    def pickler_config(pickle_data_protocol: int) -> PicklerConfig:
        return PicklerConfig(protocol=pickle_data_protocol)

    @pytest.fixture(scope="class", params=[False, True], ids=lambda boolean: f"optimize=={boolean}")
    @staticmethod
    def pickler_optimize(request: Any) -> bool:
        return request.param

    @pytest.fixture(
        scope="class",
        params=[UnpicklerConfig(encoding=encoding) for encoding in ["utf-8", "ascii"]],
        ids=repr,
    )
    @staticmethod
    def unpickler_config(request: Any) -> UnpicklerConfig:
        return request.param

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_serialization(pickler_config: PicklerConfig, pickler_optimize: bool) -> PickleSerializer:
        return PickleSerializer(pickler_config=pickler_config, pickler_optimize=pickler_optimize)

    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_for_deserialization(unpickler_config: UnpicklerConfig) -> PickleSerializer:
        return PickleSerializer(unpickler_config=unpickler_config)

    #### Packets to test

    @pytest.fixture(scope="class", params=[pytest.param(p, id=f"packet: {id}") for p, id in SAMPLES])
    @staticmethod
    def packet_to_serialize(request: Any) -> Any:
        return request.param

    #### One-shot Serialize

    @pytest.fixture(scope="class")
    @staticmethod
    def expected_complete_data(packet_to_serialize: Any, pickler_config: PicklerConfig | None, pickler_optimize: bool) -> bytes:
        if pickler_config is None:
            pickler_config = PicklerConfig()
        data = pickle.dumps(packet_to_serialize, **dataclasses.asdict(pickler_config), buffer_callback=None)
        if pickler_optimize:
            data = pickletools.optimize(data)
        return data

    #### One-shot Deserialize

    @pytest.fixture(scope="class")
    @staticmethod
    def complete_data(
        packet_to_serialize: Any,
        pickle_data_protocol: int,
        unpickler_config: UnpicklerConfig | None,
        pickler_optimize: bool,
    ) -> bytes:
        if unpickler_config is None:
            unpickler_config = UnpicklerConfig()
        data = pickle.dumps(packet_to_serialize, protocol=pickle_data_protocol, fix_imports=unpickler_config.fix_imports)
        if pickler_optimize:
            data = pickletools.optimize(data)
        return data

    #### Invalid data

    @pytest.fixture(scope="class")
    @staticmethod
    def invalid_complete_data() -> bytes:
        pytest.skip("pickle.Unpickler() raises SystemError for some invalid inputs :)")
