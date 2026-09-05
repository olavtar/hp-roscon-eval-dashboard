import json
import pathlib

import pytest

from eval_dashboard import aggregate
from eval_dashboard.sources.file_source import FileSource

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Expected numbers per tests/fixtures/README.md: 40 synthetic records, two
# model_versions, deliberately with a real gap between them so the
# comparison view has something to show before live multi-version data
# exists. If these ever drift, the fixture set changed -- update the
# README's documented numbers too, don't just bump these.
EXPECTED = {
    "fixture-strong-v0": {"episode_count": 20, "success_count": 17},
    "fixture-weak-v0": {"episode_count": 20, "success_count": 1},
}

# The fixture JSON files are Jeremy's synthetic data (tests/fixtures/README.md)
# and are gitignored rather than redistributed in this repo -- see
# tests/fixtures/README.md for where to get them. Tests below that depend on
# them skip cleanly on a fresh clone instead of failing.
requires_fixtures = pytest.mark.skipif(
    not any(FIXTURES.glob("*.json")),
    reason="tests/fixtures/*.json not present locally (gitignored, see tests/fixtures/README.md)",
)


@requires_fixtures
def test_reads_all_curated_and_rejected_fixtures():
    records = list(FileSource(str(FIXTURES)).read())
    assert len(records) == 40


@requires_fixtures
def test_dataset_path_field_is_ignored_without_error():
    records = list(FileSource(str(FIXTURES)).read())
    assert all("dataset_path" not in r for r in records)


@requires_fixtures
def test_fixture_success_rates_match_documented_ground_truth():
    # Whole population (curated + rejected) per version -- confirms success
    # rate reflects real outcomes, not just the curated (100%-by-construction)
    # slice, and that the two versions show a real, distinguishable gap.
    records = list(FileSource(str(FIXTURES)).read())
    stats = aggregate.aggregate(records)
    for version, expected in EXPECTED.items():
        v = stats[version]
        assert v.episode_count == expected["episode_count"], version
        assert v.success_count == expected["success_count"], version
        assert v.success_rate_incomplete is False, version  # both verdicts present


@requires_fixtures
def test_fixture_smoothness_is_success_only():
    records = list(FileSource(str(FIXTURES)).read())
    stats = aggregate.aggregate(records)
    strong = stats["fixture-strong-v0"]
    weak = stats["fixture-weak-v0"]
    assert strong.smoothness_n == 17
    assert weak.smoothness_n == 1
    # All-episode means were ~0.0047 (strong) and ~0.0018 (weak). Success-only
    # must not let the 19 weak failures make weak look smoother.
    assert weak.mean_smoothness > 0.003
    assert strong.mean_smoothness > 0.005
    assert set(strong.smoothness_hist) <= {"0.002-0.004", "0.004-0.006", "0.006-0.008"}


@requires_fixtures
def test_replay_is_deterministic_across_runs():
    first = aggregate.aggregate(list(FileSource(str(FIXTURES)).read()))
    second = aggregate.aggregate(list(FileSource(str(FIXTURES)).read()))
    for version in EXPECTED:
        assert first[version].success_rate == second[version].success_rate
        assert first[version].episode_count == second[version].episode_count


def test_reads_json_array_eval_file(tmp_path):
    payload = [
        {
            "episode_id": "a",
            "model_version": "teacher-ft-10",
            "task_success": True,
            "cubes_placed": 3,
            "avg_smoothness": 0.0042,
            "has_failure": False,
        },
        {
            "episode_id": "b",
            "model_version": "teacher-ft-10",
            "task_success": False,
            "cubes_placed": 1,
            "avg_smoothness": 0.001,
            "has_failure": False,
        },
    ]
    (tmp_path / "teacher-ft-10.json").write_text(json.dumps(payload))
    records = list(FileSource(str(tmp_path)).read())
    assert len(records) == 2
    stats = aggregate.aggregate(records)["teacher-ft-10"]
    assert stats.success_rate == 0.5
    assert stats.mean_smoothness == 0.0042


def test_string_false_is_not_treated_as_true(tmp_path):
    (tmp_path / "ep.json").write_text(
        json.dumps(
            {
                "episode_id": "a",
                "model_version": "v1",
                "task_success": "false",
                "has_failure": "false",
                "cubes_placed": 1,
                "avg_smoothness": 0.001,
            }
        )
    )
    records = list(FileSource(str(tmp_path)).read())
    assert records[0]["task_success"] is False
    assert records[0]["has_failure"] is False
