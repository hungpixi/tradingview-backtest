from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

_VERSION_LINE = "//@version"


@dataclass(frozen=True)
class PineBlock:
    index: int
    start_line: int
    end_line: int
    kind: str
    title: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_pine_bundle(input_path: str | Path, output_dir: str | Path) -> list[PineBlock]:
    source_path = Path(input_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Pine bundle not found: {source_path}")

    text = source_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip().startswith(_VERSION_LINE)]
    if not starts:
        return []

    starts.append(len(lines))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks: list[PineBlock] = []
    for idx, (start, end) in enumerate(zip(starts, starts[1:]), start=1):
        raw = "\n".join(lines[start:end]).strip() + "\n"
        kind = _detect_kind(raw)
        title = _extract_title(raw)
        if kind == "unknown":
            continue
        if kind != "strategy":
            blocks.append(
                PineBlock(
                    index=idx,
                    start_line=start + 1,
                    end_line=end,
                    kind=kind,
                    title=title,
                    source="",
                )
            )
            continue
        slug = _slugify(title or f"strategy_{idx}")
        filename = f"{idx:02d}_{slug}.pine"
        target = out_dir / filename
        target.write_text(raw, encoding="utf-8")
        blocks.append(
            PineBlock(
                index=idx,
                start_line=start + 1,
                end_line=end,
                kind=kind,
                title=title,
                source=str(target),
            )
        )

    manifest_path = out_dir / "manifest.json"
    payload = {
        "input_file": str(source_path),
        "strategy_count": sum(1 for block in blocks if block.kind == "strategy"),
        "indicator_count": sum(1 for block in blocks if block.kind == "indicator"),
        "items": [block.to_dict() for block in blocks],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return blocks


def _detect_kind(block_text: str) -> str:
    for line in block_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("strategy("):
            return "strategy"
        if stripped.startswith("indicator("):
            return "indicator"
    return "unknown"


def _extract_title(block_text: str) -> str:
    title_patterns = [
        re.compile(r'title\s*=\s*"([^"]+)"'),
        re.compile(r'^strategy\(\s*"([^"]+)"'),
        re.compile(r'^indicator\(\s*"([^"]+)"'),
    ]
    for line in block_text.splitlines():
        stripped = line.strip()
        for pattern in title_patterns:
            match = pattern.search(stripped)
            if match:
                return match.group(1).strip()
    return ""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "strategy"
