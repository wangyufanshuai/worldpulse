"""Dependency-free deeply immutable JSON container values for Kernel V2."""

from __future__ import annotations

from typing import Any, NoReturn, SupportsIndex


class FrozenDict(dict[Any, Any]):
    """A recursively frozen dictionary that preserves normal JSON encoding."""

    def _immutable(self) -> NoReturn:
        raise TypeError("Kernel contract mappings are immutable")

    def __setitem__(self, key: Any, value: Any) -> NoReturn:
        self._immutable()

    def __delitem__(self, key: Any) -> NoReturn:
        self._immutable()

    def clear(self) -> NoReturn:
        self._immutable()

    def pop(self, key: Any, default: Any = None) -> NoReturn:
        self._immutable()

    def popitem(self) -> NoReturn:
        self._immutable()

    def setdefault(self, key: Any, default: Any = None) -> NoReturn:
        self._immutable()

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._immutable()

    def __ior__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        self._immutable()

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return self

    def copy(self) -> FrozenDict:
        return self


class FrozenList(list[Any]):
    """A recursively frozen list that preserves list equality and JSON shape."""

    def _immutable(self) -> NoReturn:
        raise TypeError("Kernel contract sequences are immutable")

    def __setitem__(self, key: SupportsIndex | slice, value: Any) -> NoReturn:
        self._immutable()

    def __delitem__(self, key: SupportsIndex | slice) -> NoReturn:
        self._immutable()

    def __iadd__(self, value: Any) -> NoReturn:  # type: ignore[misc]
        self._immutable()

    def __imul__(self, value: Any) -> NoReturn:  # type: ignore[misc]
        self._immutable()

    def append(self, value: Any) -> NoReturn:
        self._immutable()

    def clear(self) -> NoReturn:
        self._immutable()

    def extend(self, values: Any) -> NoReturn:
        self._immutable()

    def insert(self, index: SupportsIndex, value: Any) -> NoReturn:
        self._immutable()

    def pop(self, index: SupportsIndex = -1) -> NoReturn:
        self._immutable()

    def remove(self, value: Any) -> NoReturn:
        self._immutable()

    def reverse(self) -> NoReturn:
        self._immutable()

    def sort(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._immutable()

    def __copy__(self) -> FrozenList:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenList:
        return self

    def copy(self) -> FrozenList:
        return self


def freeze_value(value: Any) -> Any:
    """Recursively freeze mappings and sequences without changing JSON shape."""

    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, dict):
        return FrozenDict({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(item) for item in value)
    return value
