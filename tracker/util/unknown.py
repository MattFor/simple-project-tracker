from typing import Any, final, override
from collections.abc import Iterator


@final
class Unknown:
	__slots__: tuple[str, ...] = ()

	def __getitem__(self, key: object) -> "Unknown":
		return self

	def __getattr__(self, name: str) -> "Unknown":
		return self

	def get(self, key: object, default: Any = None) -> Any:
		del key

		return default if default is not None else self

	def __iter__(self) -> Iterator[Any]:
		return iter(())

	def __len__(self) -> int:
		return 0

	def __contains__(self, item: object) -> bool:
		return False

	@override
	def __eq__(self, other: object) -> bool:
		return isinstance(other, Unknown)

	@override
	def __hash__(self) -> int:
		return hash("<unknown>")

	@override
	def __str__(self) -> str:
		return "unknown"

	@override
	def __repr__(self) -> str:
		return "unknown"

	def __bool__(self) -> bool:
		return False
