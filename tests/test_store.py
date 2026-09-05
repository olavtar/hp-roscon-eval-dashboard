from eval_dashboard.main import Store


def rec(episode_id, model_version="v1", has_failure=False, task_success=True, curation_verdict="pass"):
    return {
        "episode_id": episode_id,
        "model_version": model_version,
        "has_failure": has_failure,
        "task_success": task_success,
        "cubes_placed": 3 if task_success else 1,
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


def test_dedupes_by_episode_id_last_write_wins():
    store = Store()
    store.merge([rec("a", task_success=False)])
    store.merge([rec("a", task_success=True)])  # e.g. re-listing the same bucket
    snap = store.snapshot()
    assert snap["episode_count"] == 1
    assert snap["versions"]["v1"]["success_count"] == 1


def test_episodes_filterable_by_version():
    store = Store()
    store.merge([rec("a", model_version="v1"), rec("b", model_version="v2")])
    assert len(store.episodes("v1")) == 1
    assert len(store.episodes()) == 2


def test_reidentical_verdict_reread_is_not_a_duplicate():
    # Simulates the 30s episodes-rejected poll re-listing the same records
    # every cycle -- must not inflate the duplicate counter each time.
    store = Store()
    store.merge([rec("a", curation_verdict="reject")])
    store.merge([rec("a", curation_verdict="reject")])
    store.merge([rec("a", curation_verdict="reject")])
    assert store.snapshot()["duplicate_episode_ids"] == 0


def test_conflicting_verdict_is_a_duplicate():
    # Same episode_id seen as both curated (pass) and rejected -- the real
    # warning sign.
    store = Store()
    store.merge([rec("a", curation_verdict="pass")])
    store.merge([rec("a", curation_verdict="reject")])
    assert store.snapshot()["duplicate_episode_ids"] == 1


def test_success_rate_incomplete_flag_reaches_snapshot():
    store = Store()
    store.merge([rec("a", curation_verdict="pass"), rec("b", curation_verdict="pass")])
    snap = store.snapshot()
    assert snap["versions"]["v1"]["success_rate_incomplete"] is True
    assert snap["versions"]["v1"]["success_rate"] == 1.0  # data is present, just flagged


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
