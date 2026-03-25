from __future__ import annotations

import json
from pathlib import Path

from tools.datasets.export_year_timeline_fixtures import (
    export_email_pool,
    export_ics_timeline,
    export_mixed_derived_sets,
)
from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest


def test_year_timeline_email_export_writes_bucket_artifacts() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    export_email_pool(manifest)

    bucket_dir = Path("tests/fixtures/private/email_pool/year_timeline_gmail")
    full_sim_dir = Path("tests/fixtures/private/email_pool/year_timeline_full_sim")
    assert (bucket_dir / "samples.jsonl").is_file()
    assert (bucket_dir / "manifest.json").is_file()
    assert (bucket_dir / "README.md").is_file()
    assert (full_sim_dir / "samples.jsonl").is_file()
    assert (full_sim_dir / "manifest.json").is_file()
    assert (full_sim_dir / "README.md").is_file()

    sample_count = sum(1 for _ in (bucket_dir / "samples.jsonl").open())
    assert sample_count == 4 * 12 * 12
    full_sim_count = sum(1 for _ in (full_sim_dir / "samples.jsonl").open())
    assert full_sim_count == sample_count + (4 * 12 * 204)

    manifest_payload = json.loads((bucket_dir / "manifest.json").read_text())
    full_sim_manifest_payload = json.loads((full_sim_dir / "manifest.json").read_text())
    assert manifest_payload["bucket"] == "year_timeline_gmail"
    assert manifest_payload["sample_count"] == sample_count
    assert manifest_payload["actor_role_breakdown"]["professor"] > 0
    assert full_sim_manifest_payload["bucket"] == "year_timeline_full_sim"
    assert full_sim_manifest_payload["sample_count"] == full_sim_count
    assert full_sim_manifest_payload["layer_breakdown"]["core_course"] == sample_count
    assert full_sim_manifest_payload["layer_breakdown"]["background_noise"] == 4 * 12 * 204
    assert full_sim_manifest_payload["prefilter_expected_route_breakdown"]["skip_unknown"] > 0
    assert full_sim_manifest_payload["prefilter_reason_family_breakdown"]["academic_non_target"] > 0

    smoke_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_smoke_24.json").read_text())
    directive_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_directive_48.json").read_text())
    alias_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_alias_hard_48.json").read_text())
    family_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_family_alias_48.json").read_text())
    prof_ta_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_prof_ta_conflict_48.json").read_text())
    wrapper_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_canvas_wrapper_48.json").read_text())
    junk_payload = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_junk_heavy_48.json").read_text())
    assert len(smoke_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 24
    assert len(directive_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48
    assert len(alias_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48
    assert len(family_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48
    assert len(prof_ta_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48
    assert len(wrapper_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48
    assert len(junk_payload["sample_ids_by_bucket"]["year_timeline_gmail"]) == 48

    full_sim_smoke = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_smoke_96.json").read_text())
    full_sim_bait = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_false_positive_bait_96.json").read_text())
    full_sim_academic = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_academic_noise_96.json").read_text())
    full_sim_wrapper = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_wrapper_heavy_96.json").read_text())
    full_sim_start = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_quarter_start_64.json").read_text())
    full_sim_finals = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_finals_window_64.json").read_text())
    full_sim_regression = json.loads(Path("tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_mixed_regression_192.json").read_text())
    assert len(full_sim_smoke["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 96
    assert len(full_sim_bait["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 96
    assert len(full_sim_academic["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 96
    assert len(full_sim_wrapper["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 96
    assert len(full_sim_start["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 64
    assert len(full_sim_finals["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 64
    assert len(full_sim_regression["sample_ids_by_bucket"]["year_timeline_full_sim"]) == 192

    first_sample = json.loads((bucket_dir / "samples.jsonl").read_text().splitlines()[0])
    assert "actor_role" in first_sample
    assert "channel_timing_mode" in first_sample
    assert "junk_profile" in first_sample
    assert "prefilter_expected_route" in first_sample
    first_full_sim_sample = json.loads((full_sim_dir / "samples.jsonl").read_text().splitlines()[0])
    assert "full_sim_layer" in first_full_sim_sample
    assert "prefilter_reason_family" in first_full_sim_sample
    assert "background_topic" in first_full_sim_sample

    catalog = json.loads(Path("tests/fixtures/private/email_pool/library_catalog.json").read_text())
    assert "year_timeline_gmail" in catalog["buckets"]
    assert "year_timeline_full_sim" in catalog["buckets"]


def test_year_timeline_ics_and_mixed_export_writes_scenarios_and_derived_sets() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    export_ics_timeline(manifest)
    export_mixed_derived_sets(manifest)

    scenario_ids = [
        "year-timeline-wi26",
        "year-timeline-sp26",
        "year-timeline-su26",
        "year-timeline-fa26",
    ]
    for scenario_id in scenario_ids:
        scenario_dir = Path("tests/fixtures/private/ics_timeline/scenarios") / scenario_id
        assert (scenario_dir / "round-00.ics").is_file()
        assert (scenario_dir / "round-12.ics").is_file()
        manifest_payload = json.loads((scenario_dir / "manifest.json").read_text())
        assert manifest_payload["transition_count"] == 12
        assert "channel_timing_breakdown" in manifest_payload["transitions"][0]

    smoke_payload = json.loads(Path("tests/fixtures/private/ics_timeline/derived_sets/year_timeline_smoke_16.json").read_text())
    heavy_payload = json.loads(Path("tests/fixtures/private/ics_timeline/derived_sets/year_timeline_change_heavy_24.json").read_text())
    removed_payload = json.loads(Path("tests/fixtures/private/ics_timeline/derived_sets/year_timeline_removed_focus_16.json").read_text())
    calendar_first_payload = json.loads(Path("tests/fixtures/private/ics_timeline/derived_sets/year_timeline_calendar_first_16.json").read_text())
    email_first_payload = json.loads(Path("tests/fixtures/private/ics_timeline/derived_sets/year_timeline_email_first_16.json").read_text())
    assert len(smoke_payload["transitions"]) == 16
    assert len(heavy_payload["transitions"]) == 24
    assert len(removed_payload["transitions"]) == 16
    assert len(calendar_first_payload["transitions"]) == 16
    assert len(email_first_payload["transitions"]) == 16

    mixed_payload = json.loads(Path("tests/fixtures/private/year_timeline_mixed/derived_sets/year_timeline_cross_channel_lag_24.json").read_text())
    assert len(mixed_payload["bundles"]) == 24
    assert mixed_payload["bundles"][0]["email_sample_ids"]

    catalog = json.loads(Path("tests/fixtures/private/ics_timeline/library_catalog.json").read_text())
    scenario_ids_in_catalog = {row["scenario_id"] for row in catalog["scenarios"]}
    assert {"year-timeline-wi26", "year-timeline-sp26", "year-timeline-su26", "year-timeline-fa26"}.issubset(scenario_ids_in_catalog)
