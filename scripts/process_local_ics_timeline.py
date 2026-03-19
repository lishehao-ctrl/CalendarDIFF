#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "ics_timeline" / "derived_sets"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect local ICS timeline derived sets.")
    parser.add_argument("--derived-set", help="Derived-set name under tests/fixtures/private/ics_timeline/derived_sets.")
    parser.add_argument("--list-derived-sets", action="store_true", help="List available ICS derived sets and exit.")
    parser.add_argument("--list-transitions", action="store_true", help="Print transitions for the selected derived set and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_derived_sets:
        print(json.dumps(sorted(path.stem for path in DERIVED_ROOT.glob("*.json")), ensure_ascii=False, indent=2))
        return
    if not args.derived_set:
        raise SystemExit("--derived-set is required unless --list-derived-sets is used")
    payload = json.loads((DERIVED_ROOT / f"{args.derived_set}.json").read_text(encoding="utf-8"))
    if args.list_transitions:
        print(json.dumps(payload.get("transitions") or [], ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
