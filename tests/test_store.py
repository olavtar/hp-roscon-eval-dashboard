from eval_dashboard.main import Store


def rec(episode_id, model_version="v1", has_failure=False, task_success=True, curation_verdict="pass", cubes_placed=None):
    if cubes_placed is None:
        cubes_placed = 3 if task_success else 1
    return {
        "episode_id": episode_id,
        "model_version": model_version,
        "has_failure": has_failure,
        "task_success": task_success,
        "cubes_placed": cubes_placed,
        "avg_smoothness": 0.01,
        "scene": "place_cubes_on_tray",
        "timestamp": "2026-09-04T00:00:00Z",
        "curation_verdict": curation_verdict,
        "rollout_steps": 100,
    }


def test_drops_injected_failures():
    store = Store()
    store.merge([rec("a", has_failure=True), rec("b", has_failure=False)])
    snap = store.snapshot()
    assert snap["episode_count"] == 1
    assert snap["dropped_has_failure"] == 1


def test_identical_reread_is_no_op():
    store = Store()
    store.merge([rec("a", task_success=False)])
    store.merge([rec("a", task_success=False)])
    snap = store.snapshot()
    assert snap["episode_count"] == 1
    assert snap["conflicting_episode_ids"] == 0


def test_conflicting_fields_are_quarantined():
    store = Store()
    store.merge([rec("a", task_success=False)])
    store.merge([rec("a", task_success=True)])
    snap = store.snapshot()
    assert snap["episode_count"] == 0
    assert snap["conflicting_episode_ids"] == 1


def test_episodes_filterable_by_version():
    store = Store()
    store.merge([rec("a", model_version="v1"), rec("b", model_version="v2")])
    assert len(store.episodes("v1")) == 1
    assert len(store.episodes()) == 2


def test_reidentical_verdict_reread_is_not_a_duplicate():
    store = Store()
    store.merge([rec("a", curation_verdict="reject")])
    store.merge([rec("a", curation_verdict="reject")])
    store.merge([rec("a", curation_verdict="reject")])
    assert store.snapshot()["duplicate_episode_ids"] == 0
    assert store.snapshot()["conflicting_episode_ids"] == 0


def test_conflicting_verdict_is_counted():
    store = Store()
    store.merge([rec("a", curation_verdict="pass")])
    store.merge([rec("a", curation_verdict="reject")])
    snap = store.snapshot()
    assert snap["duplicate_episode_ids"] == 1
    assert snap["conflicting_episode_ids"] == 1
    assert snap["episode_count"] == 0


def test_success_rate_incomplete_flag_reaches_snapshot():
    store = Store()
    store.merge([rec("a", curation_verdict="pass"), rec("b", curation_verdict="pass")])
    snap = store.snapshot()
    assert snap["versions"]["v1"]["success_rate_incomplete"] is True
    assert snap["versions"]["v1"]["success_rate"] == 1.0


def test_has_failure_recount_is_idempotent():
    store = Store()
    store.merge([rec("a", has_failure=True)])
    store.merge([rec("a", has_failure=True)])
    store.merge([rec("a", has_failure=True)])
    assert store.snapshot()["dropped_has_failure"] == 1
    assert store.snapshot()["episode_count"] == 0


def test_replace_rebuilds_without_inflating_counters():
    store = Store()
    store.merge([rec("a"), rec("b", has_failure=True)])
    store.replace([rec("a"), rec("b", has_failure=True)])
    snap = store.snapshot()
    assert snap["episode_count"] == 1
    assert snap["dropped_has_failure"] == 1
    assert snap["duplicate_episode_ids"] == 0
    assert snap["conflicting_episode_ids"] == 0


def test_invalid_records_are_dropped():
    store = Store()
    store.merge([
        {
            "episode_id": "bad",
            "model_version": "v1",
            "has_failure": False,
            "task_success": True,
            "cubes_placed": 9,
        }
    ])
    snap = store.snapshot()
    assert snap["episode_count"] == 0
    assert snap["dropped_invalid"] == 1
