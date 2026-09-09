from eval_dashboard import schema


def ep(model_version, episode_id="e1", **kwargs):
    base = {
        "episode_id": episode_id,
        "model_version": model_version,
        "task_success": True,
        "cubes_placed": 3,
        "avg_smoothness": 0.005,
        "has_failure": False,
        "curation_verdict": "pass",
    }
    base.update(kwargs)
    return schema.normalize(base)


def test_eval_prefixed_versions_are_dropped():
    records = [ep("eval-teacher-v1"), ep("upstream-act-teacher")]
    kept = list(schema.apply_lineage_rules(records))
    assert [r["model_version"] for r in kept] == ["upstream-act-teacher"]


def test_legacy_versions_grouped_as_pre_teacher():
    records = [ep("soarm-act-v1"), ep("soarm-act-10ep-10k")]
    kept = list(schema.apply_lineage_rules(records))
    assert all(r["model_version"] == "pre-teacher" for r in kept)
    assert {r["raw_model_version"] for r in kept} == {"soarm-act-v1", "soarm-act-10ep-10k"}


def test_current_versions_pass_through_unchanged():
    records = [ep("upstream-act-teacher"), ep("act-v2-ft160")]
    kept = list(schema.apply_lineage_rules(records))
    assert {r["model_version"] for r in kept} == {"upstream-act-teacher", "act-v2-ft160"}
    assert all("raw_model_version" not in r for r in kept)


def test_missing_task_success_is_rejected():
    assert schema.normalize({"episode_id": "a", "model_version": "v1"}) is None


def test_invalid_cubes_placed_is_rejected():
    assert schema.normalize({
        "episode_id": "a",
        "model_version": "v1",
        "task_success": True,
        "cubes_placed": 9,
    }) is None


def test_records_conflict_detects_field_differences():
    a = ep("v1")
    b = ep("v1", task_success=False)
    assert schema.records_conflict(a, b) is True
    assert schema.records_conflict(a, a) is False
