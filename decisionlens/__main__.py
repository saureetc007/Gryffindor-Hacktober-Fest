"""CLI entry point for DecisionLens."""

import argparse
import json
import sys

from decisionlens.pipeline import learn, load_records, save_records
from decisionlens.report import write_report
from decisionlens.style import format_warning_cli, paint
from decisionlens.surface import build_pr_context, surface


def main(argv=None):
    parser = argparse.ArgumentParser(prog="decisionlens", description="DecisionLens CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    learn_p = subparsers.add_parser("learn", help="Recover decisions from thread")
    learn_p.add_argument("thread", help="Path to discussion thread JSON or text")
    learn_p.add_argument("--out", required=True, help="Output path for decisions JSON")

    check_p = subparsers.add_parser("check", help="Check PR against past decisions")
    check_p.add_argument("pr_file", help="Path to PR JSON")
    check_p.add_argument("--decisions", required=True, help="Path to decisions JSON")

    report_p = subparsers.add_parser("report", help="Generate Markdown report from decisions")
    report_p.add_argument("decisions", help="Path to decisions JSON")
    report_p.add_argument("--out", required=True, help="Output path for report Markdown")

    if argv is None:
        argv = sys.argv[1:]

    parsed = parser.parse_args(argv)

    if parsed.command == "learn":
        records = learn(parsed.thread)
        save_records(records, parsed.out)
        count_str = paint(str(len(records)), "green", bold=True)
        out_str = paint(str(parsed.out), "green", bold=True)
        print(f"Learned {count_str} decision(s) saved to {out_str}")

    elif parsed.command == "check":
        with open(parsed.pr_file, "r", encoding="utf-8") as f:
            pr_data = json.load(f)
        records = load_records(parsed.decisions)
        pr_context = build_pr_context(pr_data)
        warnings = surface(pr_context, records)
        if not warnings:
            print("No decision conflicts detected.")
        else:
            for w in warnings:
                print(format_warning_cli(w))

    elif parsed.command == "report":
        records = load_records(parsed.decisions)
        write_report(records, parsed.out)
        out_str = paint(str(parsed.out), "green", bold=True)
        print(f"Report written to {out_str}")


if __name__ == "__main__":
    main()
