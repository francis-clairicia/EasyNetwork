from __future__ import annotations

import errno

from easynetwork.lowlevel._utils import error_from_errno

import pytest


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____ClosedResourceError() -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    import trio

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            try:
                raise error_from_errno(errno.EBADF)
            except OSError:
                raise trio.ClosedResourceError from None

    # Assert
    assert exc_info.value.errno == errno.EBADF
    assert isinstance(exc_info.value.__cause__, trio.ClosedResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____BusyResourceError() -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    import trio

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            raise trio.BusyResourceError

    # Assert
    assert exc_info.value.errno == errno.EBUSY
    assert isinstance(exc_info.value.__cause__, trio.BusyResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
@pytest.mark.parametrize("broken_resource_errno", [errno.ECONNABORTED, errno.EPIPE])
def test____convert_trio_resource_errors____BrokenResourceError____arbitrary(broken_resource_errno: int) -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    import trio

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=broken_resource_errno):
            raise trio.BrokenResourceError

    # Assert
    assert exc_info.value.errno == broken_resource_errno
    assert isinstance(exc_info.value.__cause__, trio.BrokenResourceError)
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
@pytest.mark.parametrize("broken_resource_errno", [errno.ECONNABORTED, errno.ECONNRESET, errno.EPIPE, errno.ENOTCONN])
def test____convert_trio_resource_errors____BrokenResourceError____because_of_OSError(broken_resource_errno: int) -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    import trio

    initial_error = error_from_errno(broken_resource_errno)

    # Act
    with pytest.raises(OSError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            try:
                raise initial_error
            except OSError as exc:
                raise trio.BrokenResourceError from exc

    # Assert
    assert exc_info.value is initial_error
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.feature_trio
def test____convert_trio_resource_errors____other_exceptions() -> None:
    # Arrange
    from easynetwork.lowlevel.api_async.backend._trio._trio_utils import convert_trio_resource_errors

    initial_error = ValueError("invalid bufsize")

    # Act
    with pytest.raises(ValueError) as exc_info:
        with convert_trio_resource_errors(broken_resource_errno=errno.ECONNABORTED):
            raise initial_error

    # Assert
    assert exc_info.value is initial_error
