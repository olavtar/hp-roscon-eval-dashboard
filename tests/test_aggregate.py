from eval_dashboard import aggregate


def ep(model_version, task_success, cubes_placed, avg_smoothness, curation_verdict="pass"):
    return {
        "episode_id": "irrelevant",
        "model_version": model_version,
        "has_failure": False,
        "task_success": task_success,
        "cubes_placed": cubes_placed,
        "avg_smoothness": avg_smoothness,
        "scene": "place_cubes_on_tray",
        "timestamp": None,
        "curation_verdict": curation_verdict,
        "rollout_steps": 100,
    }


def test_success_rate_per_version():
    records = [
        ep("v1", True, 3, 0.01),
        ep("v1", False, 1, 0.05),
        ep("v2", True, 3, 0.01),
        ep("v2", True, 3, 0.02),
    ]
    stats = aggregate.aggregate(records)
    assert stats["v1"].success_rate == 0.5
    assert stats["v2"].success_rate == 1.0
    assert stats["v1"].episode_count == 2
    assert stats["v2"].episode_count == 2


def test_cubes_placed_distribution():
    records = [ep("v1", True, 3, 0.01), ep("v1", False, 0, 0.01), ep("v1", False, 2, 0.01)]
    stats = aggregate.aggregate(records)
    assert stats["v1"].cubes_placed == {0: 1, 1: 0, 2: 1, 3: 1}
    assert stats["v1"].cube_bins_reconcile is True


def test_cube_bins_reconcile_flags_missing_data():
    records = [ep("v1", True, None, 0.01), ep("v1", True, 3, 0.01)]
    stats = aggregate.aggregate(records)
    assert stats["v1"].cube_bins_reconcile is False


def test_smoothness_bucketing():
    records = [ep("v1", True, 3, 0.005), ep("v1", True, 3, 0.019), ep("v1", True, 3, None)]
    stats = aggregate.aggregate(records)
    hist = stats["v1"].smoothness_hist
    assert hist["0.004-0.006"] == 1
    assert hist[">=0.015"] == 1
    assert hist["unknown"] == 1


def test_failed_episode_excluded_from_smoothness():
    # A failed episode with tiny joint deltas must not pull mean smoothness
    # down — that's what made a weak policy look ~2.6× "smoother".
    records = [ep("v1", True, 3, 0.005), ep("v1", False, 1, 0.001)]
    stats = aggregate.aggregate(records)["v1"]
    assert stats.mean_smoothness == 0.005
    assert stats.smoothness_n == 1
    assert stats.episode_count == 2
    assert stats.success_count == 1
    assert stats.smoothness_hist.get("0.000-0.002", 0) == 0
    assert stats.smoothness_hist["0.004-0.006"] == 1


def test_smoothness_mean_none_when_no_successes():
    records = [ep("v1", False, 1, 0.001)]
    stats = aggregate.aggregate(records)["v1"]
    assert stats.mean_smoothness is None
    assert stats.smoothness_hist == {}


def test_wilson_ci_widens_for_small_n():
    small_lo, small_hi = aggregate.wilson_ci(4, 5)
    large_lo, large_hi = aggregate.wilson_ci(400, 500)
    assert (small_hi - small_lo) > (large_hi - large_lo)


def test_wilson_ci_empty():
    assert aggregate.wilson_ci(0, 0) == (None, None)


def test_avg_cubes_and_mean_smoothness():
    records = [ep("v1", True, 3, 0.02), ep("v1", False, 1, 0.06)]
    stats = aggregate.aggregate(records)
    assert stats["v1"].avg_cubes_placed == 2.0
    # 0.02 is a success; 0.06 is a failure and must not enter the mean.
    # 0.02 lands in the >=0.015 tail with the ACT-scale bins.
    assert stats["v1"].mean_smoothness == 0.02


def test_curated_only_population_is_flagged_incomplete():
    # All curator "pass" verdicts, no "reject" -- the exact signature of
    # only having read episodes-curated, never episodes-rejected. The
    # curator gates hard on task_success, so this population would read
    # ~100% by construction, which is why it must be flagged rather than
    # trusted.
    records = [ep("v1", True, 3, 0.01, "pass") for _ in range(5)]
    stats = aggregate.aggregate(records)
    assert stats["v1"].success_rate == 1.0
    assert stats["v1"].success_rate_incomplete is True


def test_mixed_verdicts_are_not_incomplete():
    records = [ep("v1", True, 3, 0.01, "pass"), ep("v1", False, 1, 0.01, "reject")]
    stats = aggregate.aggregate(records)
    assert stats["v1"].success_rate_incomplete is False


def test_records_with_no_verdict_are_not_flagged_incomplete():
    # Controlled eval files aren't curator output at all -- no verdict field,
    # so the curated-only check doesn't apply; the file is trusted to be the
    # complete population by contract.
    records = [ep("v1", True, 3, 0.01, curation_verdict=None) for _ in range(5)]
    stats = aggregate.aggregate(records)
    assert stats["v1"].success_rate_incomplete is False


def test_success_matches_full_cubes():
    matching = aggregate.aggregate([ep("v1", True, 3, 0.01), ep("v1", False, 1, 0.01)])
    assert matching["v1"].success_matches_full_cubes is True

    mismatched = aggregate.aggregate([ep("v1", True, 2, 0.01)])  # success but not 3 cubes
    assert mismatched["v1"].success_matches_full_cubes is False
