"""Minimal parser for Valve's text KeyValues format (.vdf / .acf)."""

from __future__ import annotations

from typing import Any


class VDFError(ValueError):
    pass


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            out = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, "\\" + nxt))
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            if i >= n:
                raise VDFError("unterminated string")
            i += 1
            yield ("str", "".join(out))
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            yield ("str", text[start:i])


def loads(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack = [root]
    key = None
    for tok in _tokens(text):
        if tok == "{":
            if key is None:
                raise VDFError("unexpected '{'")
            child: dict[str, Any] = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif tok == "}":
            if len(stack) == 1 or key is not None:
                raise VDFError("unexpected '}'")
            stack.pop()
        else:
            value = tok[1]
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    if len(stack) != 1 or key is not None:
        raise VDFError("unexpected end of input")
    return root


def load(path) -> dict[str, Any]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return loads(fh.read())


def iget(mapping: Any, *keys: str, default: Any = None) -> Any:
    """Case-insensitive nested lookup (Steam isn't consistent about key case)."""
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        if key in current:
            current = current[key]
            continue
        low = key.lower()
        for k, v in current.items():
            if k.lower() == low:
                current = v
                break
        else:
            return default
    return current


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(data: dict[str, Any], indent: int = 0) -> str:
    """Serialise nested dicts back into Valve's text format (tab indented like Steam)."""
    tabs = "\t" * indent
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{tabs}{_quote(key)}")
            lines.append(f"{tabs}{{")
            body = dumps(value, indent + 1)
            if body:
                lines.append(body.rstrip("\n"))
            lines.append(f"{tabs}}}")
        else:
            lines.append(f"{tabs}{_quote(key)}\t\t{_quote(value)}")
    return "\n".join(lines) + "\n"
