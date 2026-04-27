from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class TVInputSpec:
    name: str
    kind: str
    default: Any
    minval: float | int | None = None
    maxval: float | int | None = None
    step: float | int | None = None
    options: list[Any] | None = None


_DOT_PATTERN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*input\.(\w+)\((.*)\)\s*$")
_LEGACY_PATTERN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*input\((.*)\)\s*$")


def parse_pine_inputs(pine_text: str) -> list[TVInputSpec]:
    items: list[TVInputSpec] = []
    for raw in pine_text.splitlines():
        line = raw.strip()
        dot_match = _DOT_PATTERN.match(line)
        if dot_match:
            name, kind, args_text = dot_match.group(1), dot_match.group(2).lower(), dot_match.group(3)
            parsed = _parse_args(args_text)
            if parsed is None:
                continue
            default, kwargs = parsed
            items.append(_build_spec(name, kind, default, kwargs))
            continue

        legacy_match = _LEGACY_PATTERN.match(line)
        if legacy_match:
            name, args_text = legacy_match.group(1), legacy_match.group(2)
            parsed = _parse_args(args_text)
            if parsed is None:
                continue
            default, kwargs = parsed
            kind = _legacy_kind(kwargs, default)
            items.append(_build_spec(name, kind, default, kwargs))
    return items


def default_params(inputs: list[TVInputSpec]) -> dict[str, Any]:
    return {item.name: item.default for item in inputs}


def to_dimensions(inputs: list[TVInputSpec]) -> list[dict[str, Any]]:
    dims: list[dict[str, Any]] = []
    for item in inputs:
        if item.options:
            dims.append({"name": item.name, "kind": "categorical", "values": item.options, "default": item.default})
            continue
        if item.kind == "bool":
            dims.append({"name": item.name, "kind": "categorical", "values": [True, False], "default": bool(item.default)})
            continue
        if item.kind in {"int", "integer"} and isinstance(item.default, int):
            minval = int(item.minval) if item.minval is not None else max(1, item.default // 2)
            maxval = int(item.maxval) if item.maxval is not None else max(minval + 1, item.default * 2)
            step = int(item.step) if item.step is not None else 1
            dims.append({"name": item.name, "kind": "int", "minval": minval, "maxval": maxval, "step": max(1, step), "default": item.default})
            continue
        if item.kind in {"float"} and isinstance(item.default, (int, float)):
            base = float(item.default)
            minval = float(item.minval) if item.minval is not None else max(0.0, base * 0.5)
            maxval = float(item.maxval) if item.maxval is not None else max(minval + 0.01, base * 2.0)
            step = float(item.step) if item.step is not None else 0.05
            dims.append({"name": item.name, "kind": "float", "minval": minval, "maxval": maxval, "step": max(0.0001, step), "default": base})
    return dims


def _legacy_kind(kwargs: dict[str, Any], default: Any) -> str:
    raw_type = kwargs.get("type")
    if isinstance(raw_type, str):
        low = raw_type.lower()
        if "integer" in low:
            return "int"
        if "float" in low:
            return "float"
        if "bool" in low:
            return "bool"
        if "string" in low:
            return "string"
        if "symbol" in low:
            return "string"
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    return "string"


def _build_spec(name: str, kind: str, default: Any, kwargs: dict[str, Any]) -> TVInputSpec:
    options = kwargs.get("options")
    if not isinstance(options, list):
        options = None
    return TVInputSpec(
        name=name,
        kind=kind,
        default=default,
        minval=_to_number(kwargs.get("minval")),
        maxval=_to_number(kwargs.get("maxval")),
        step=_to_number(kwargs.get("step")),
        options=options,
    )


def _parse_args(raw_args: str) -> tuple[Any, dict[str, Any]] | None:
    chunks = _split_top_level(raw_args)
    if not chunks:
        return None
    default = _literal(chunks[0])
    kwargs: dict[str, Any] = {}
    for chunk in chunks[1:]:
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        kwargs[key.strip()] = _literal(value.strip())
    return default, kwargs


def _split_top_level(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    for char in text:
        if quote is not None:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char in {"(", "[", "{"}:
            depth += 1
            current.append(char)
            continue
        if char in {")", "]", "}"}:
            depth = max(0, depth - 1)
            current.append(char)
            continue
        if char == "," and depth == 0:
            chunks.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        chunks.append("".join(current).strip())
    return chunks


def _literal(raw: str) -> Any:
    text = raw.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    try:
        return ast.literal_eval(text)
    except Exception:
        return text.strip('"').strip("'")


def _to_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None
