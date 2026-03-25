#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "synthetic" / "year_timeline_demo" / "year_timeline_manifest.json"
DEFAULT_EMAIL_BUCKET = "year_timeline_gmail"
DEFAULT_ICS_DERIVED_SET = "year_timeline_smoke_16"
OUTPUT_ROOT = REPO_ROOT / "output"

PHASE_TO_SEMESTER = {
    "WI26": 1,
    "SP26": 2,
    "SU26": 3,
    "FA26": 4,
}
SCENARIO_TO_SEMESTER = {
    "year-timeline-wi26": 1,
    "year-timeline-sp26": 2,
    "year-timeline-su26": 3,
    "year-timeline-fa26": 4,
}


@dataclass(frozen=True)
class BundleSpec:
    semester: int
    batch: int
    scenario_id: str
    transition_id: str
    email_sample_ids: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build mixed Gmail + ICS year timeline bundle specs.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--email-bucket", default=DEFAULT_EMAIL_BUCKET)
    parser.add_argument("--ics-derived-set", default=DEFAULT_ICS_DERIVED_SET)
    parser.add_argument("--bundle-parallel", type=int, default=4)
    parser.add_argument("--email-parallel", type=int, default=12)
    parser.add_argument("--ics-parallel", type=int, default=12)
    parser.add_argument("--provider-id", default="qwen_us_main")
    parser.add_argument("--cache-mode", choices=["enable", "disable"], default="enable")
    parser.add_argument("--source-id", type=int, default=2)
    parser.add_argument("--list-bundles", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    bundles = build_bundle_specs(manifest=manifest, ics_derived_set=args.ics_derived_set)
    if args.list_bundles:
        print(json.dumps([asdict(item) for item in bundles], ensure_ascii=False, indent=2))
        return

    started_at = datetime.now(timezone.utc)
    run_dir = OUTPUT_ROOT / f"year-timeline-mixed-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": started_at.isoformat(),
        "manifest_path": str(Path(args.manifest)),
        "email_bucket": args.email_bucket,
        "ics_derived_set": args.ics_derived_set,
        "bundle_parallel": int(args.bundle_parallel),
        "email_parallel": int(args.email_parallel),
        "ics_parallel": int(args.ics_parallel),
        "provider_id": args.provider_id,
        "cache_mode": args.cache_mode,
        "source_id": int(args.source_id),
        "bundle_count": len(bundles),
        "bundles": [asdict(item) for item in bundles],
        "notes": [
            "This lightweight runner only materializes bundle specs for the local year timeline regression workflow.",
            "Use --list-bundles to inspect the exact semester/batch pairings.",
        ],
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(render_summary(report), encoding="utf-8")
    print(run_dir)


def build_bundle_specs(*, manifest: dict[str, Any], ics_derived_set: str) -> list[BundleSpec]:
    email_by_bundle: dict[tuple[int, int], list[str]] = {}
    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        semester = PHASE_TO_SEMESTER.get(str(phase.get("phase_label") or ""))
        if semester is None:
            continue
        for batch in phase.get("batches", []):
            if not isinstance(batch, dict):
                continue
            batch_no = int(batch.get("batch") or 0)
            email_by_bundle[(semester, batch_no)] = [
                str(row.get("message_id"))
                for row in batch.get("gmail_messages", [])
                if isinstance(row, dict) and isinstance(row.get("message_id"), str)
            ]

    derived_path = REPO_ROOT / "tests" / "fixtures" / "private" / "ics_timeline" / "derived_sets" / f"{ics_derived_set}.json"
    derived = json.loads(derived_path.read_text(encoding="utf-8"))
    transitions = derived.get("transitions")
    if not isinstance(transitions, list):
        raise RuntimeError(f"invalid ICS derived set: {ics_derived_set}")

    bundles: list[BundleSpec] = []
    for item in transitions:
        if not isinstance(item, dict):
            continue
        scenario_id = str(item.get("scenario_id") or "")
        transition_id = str(item.get("transition_id") or "")
        semester = SCENARIO_TO_SEMESTER.get(scenario_id)
        if semester is None:
            continue
        batch = parse_batch_from_transition(transition_id)
        sample_ids = email_by_bundle.get((semester, batch), [])
        bundles.append(
            BundleSpec(
                semester=semester,
                batch=batch,
                scenario_id=scenario_id,
                transition_id=transition_id,
                email_sample_ids=sample_ids,
            )
        )
    return bundles


def parse_batch_from_transition(transition_id: str) -> int:
    try:
        _from_round, to_round = transition_id.split("__to__")
        return int(to_round.replace("round-", ""))
    except Exception as exc:
        raise RuntimeError(f"invalid transition id: {transition_id}") from exc


def render_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Year Timeline Mixed Regression",
            "",
            f"- Manifest: `{report['manifest_path']}`",
            f"- ICS derived set: `{report['ics_derived_set']}`",
            f"- Bundles: {report['bundle_count']}",
            "",
        ]
    )


if __name__ == "__main__":
    main()
