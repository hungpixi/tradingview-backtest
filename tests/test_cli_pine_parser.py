from __future__ import annotations

import sys
import types
import unittest

sys.modules.setdefault("talib", types.ModuleType("talib"))

from hyperview.cli import build_parser


class CliPineParserTests(unittest.TestCase):
    def test_pine_optimize_supports_new_export_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "pine-optimize",
                "--pine-file",
                "strategies/raw/example.pine",
                "--symbol",
                "OANDA:XAUUSD",
                "--timeframe",
                "15m",
            ]
        )
        self.assertTrue(args.emit_optimized_pine)
        self.assertEqual(args.optimized_dir, "strategies/optimized")
        self.assertEqual(args.filename_template, "{symbol}_{tf}_{strategy}_np{net}_dd{dd}_pf{pf}_tc{trades}.pine")

    def test_pine_batch_optimize_command_is_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "pine-batch-optimize",
                "--input-dir",
                "strategies/raw",
                "--symbols",
                "OANDA:XAUUSD",
                "--timeframes",
                "15m",
            ]
        )
        self.assertEqual(args.command, "pine-batch-optimize")
        self.assertEqual(args.input_dir, "strategies/raw")
        self.assertEqual(args.symbols, ["OANDA:XAUUSD"])
        self.assertEqual(args.timeframes, ["15m"])

    def test_pine_split_command_is_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "pine-split",
                "--input",
                "source-pine-strategy/raw.pine",
                "--out",
                "strategies/raw_split",
            ]
        )
        self.assertEqual(args.command, "pine-split")
        self.assertEqual(args.input, "source-pine-strategy/raw.pine")
        self.assertEqual(args.out, "strategies/raw_split")

    def test_tv_optimize_command_is_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "tv-optimize",
                "--input-dir",
                "strategies/raw_split",
                "--symbols",
                "OANDA:XAUUSD",
                "--timeframes",
                "15m",
                "--collector-cmd",
                "python collector.py",
            ]
        )
        self.assertEqual(args.command, "tv-optimize")
        self.assertEqual(args.coarse_trials, 30)
        self.assertEqual(args.fine_trials, 60)
        self.assertEqual(args.collector_cmd, "python collector.py")


if __name__ == "__main__":
    unittest.main()
