"""Reading a nested document without confusing an absent value for a wrong path.

`document.get("a", {}).get("b", {}).get("c")` is the idiom this replaces. It returns `None`
for four different situations: `c` holds `None`, `c` is absent, `b` is absent, and `a` is
absent. Three of those are data and one is a bug, and the caller cannot tell them apart —
which is how a findings table came to be rendered entirely as `n/a` from a document that
held every number it was asked for.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def dig(document: Mapping[str, Any], *path: str) -> Any:
    """The value at `path`, raising if any step of the path does not exist.

    A key that is present and holds `None` returns `None`: that is a measurement the run did
    not make, and it is not the same as asking for something the document has never had.
    """

    node: Any = document
    for depth, key in enumerate(path):
        if not isinstance(node, Mapping):
            raise KeyError(
                f"{'.'.join(path[:depth])} is not a mapping, so {key!r} cannot be read from it"
            )
        if key not in node:
            available = ", ".join(sorted(str(name) for name in node)[:8]) or "nothing"
            raise KeyError(
                f"{'.'.join(path[: depth + 1])} does not exist; "
                f"{'.'.join(path[:depth]) or 'the document'} holds: {available}"
            )
        node = node[key]
    return node


def dig_optional(document: Mapping[str, Any], *path: str) -> Any:
    """Like `dig`, but the last step may be absent and returns `None` when it is.

    For the common case where a leaf is genuinely optional — a role a run did not fit, a
    diagnostic a producer does not emit — while the branch leading to it is not.
    """

    if not path:
        return document
    parent = dig(document, *path[:-1])
    if not isinstance(parent, Mapping):
        raise KeyError(f"{'.'.join(path[:-1])} is not a mapping")
    return parent.get(path[-1])
