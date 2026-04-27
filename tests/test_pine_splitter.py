from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from hyperview.pine.splitter import split_pine_bundle


_SAMPLE = """
//@version=5
strategy("A", overlay=true)
x = input.int(10, "X", minval=1)

//@version=5
indicator("I", overlay=true)

//@version=5
strategy(title="B", overlay=true)
"""


class PineSplitterTests(unittest.TestCase):
    def test_split_bundle_outputs_only_strategies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "raw.pine"
            out_dir = Path(tmp) / "split"
            src.write_text(_SAMPLE.strip() + "\n", encoding="utf-8")
            blocks = split_pine_bundle(src, out_dir)
            strategies = [b for b in blocks if b.kind == "strategy"]
            indicators = [b for b in blocks if b.kind == "indicator"]
            self.assertEqual(len(strategies), 2)
            self.assertEqual(len(indicators), 1)
            files = sorted(out_dir.glob("*.pine"))
            self.assertEqual(len(files), 2)
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["strategy_count"], 2)
            self.assertEqual(manifest["indicator_count"], 1)


if __name__ == "__main__":
    unittest.main()
