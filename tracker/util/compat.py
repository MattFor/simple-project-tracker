# pyright: reportUnreachable=false

import sys
from collections.abc import Callable
from typing import TypeVar

__all__ = ["override"]

if sys.version_info >= (3, 12):
	from typing import override
else:
	# typing.override is Python 3.12, this makes 3.11 work
	Method = TypeVar("Method", bound=Callable[..., object])

	def override(method: Method, /) -> Method:
		return method
