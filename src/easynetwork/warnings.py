# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Warning categories definition module.

Here are all the warning classes defined and used by the library.
"""

from __future__ import annotations

__all__ = [
    "EasyNetworkWarning",
    "ManualBufferAllocationWarning",
]


class EasyNetworkWarning(UserWarning):
    """
    Base class for all warning categories emitted by EasyNetwork.
    """


class ManualBufferAllocationWarning(EasyNetworkWarning):
    """
    Warning emitted by stream endpoints about manual buffer allocation.
    """
