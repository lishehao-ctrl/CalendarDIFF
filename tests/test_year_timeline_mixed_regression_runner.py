from __future__ import annotations

from scripts.run_year_timeline_mixed_regression import build_bundle_specs
from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest


def test_year_timeline_mixed_runner_builds_batch_bundles() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    bundles = build_bundle_specs(manifest=manifest, ics_derived_set="year_timeline_smoke_16")

    assert len(bundles) == 16
    first = bundles[0]
    assert first.semester == 1
    assert first.batch == 1
    assert first.scenario_id == "year-timeline-wi26"
    assert first.transition_id == "round-00__to__round-01"
    assert len(first.email_sample_ids) == 12
    assert all(sample_id.startswith("y01-b01-gmail-") for sample_id in first.email_sample_ids)


def test_year_timeline_mixed_runner_bundles_cover_smoke_transitions() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    bundles = build_bundle_specs(manifest=manifest, ics_derived_set="year_timeline_smoke_16")
    observed = {(row.semester, row.batch) for row in bundles}
    assert (1, 1) in observed
    assert (1, 4) in observed
    assert (1, 8) in observed
    assert (1, 12) in observed
    assert (4, 12) in observed
