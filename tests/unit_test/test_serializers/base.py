from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest


class BaseSerializerConfigInstanceCheck:
    def test____config____invalid_object(self, config_param: tuple[str, str], serializer_cls: Callable[..., Any]) -> None:
        # Arrange
        config_param_name, config_cls_name = config_param
        kwargs: dict[str, Any] = {f"{config_param_name}_config": object()}

        # Act & Assert
        with pytest.raises(TypeError, match=f"^Invalid {config_param_name} config: expected {config_cls_name}, got object$"):
            serializer_cls(**kwargs)
