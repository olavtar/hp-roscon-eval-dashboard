"""Pure aggregation over normalized episode records.

Deliberately source-agnostic: it only ever sees the shape schema.normalize()
produces, never a raw Kafka message or a raw file. That's what makes
"replaying from empty reproduces the same numbers" true by construction --
there's only one code path that turns records into stats, regardless of
where the records came from.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

# Observed ACT rollouts sit around 0.0005–0.006 (see the episode contract
# example, 0.005741). Edges are 0.002 wide so a histogram can actually
# move; the old 0.00–0.02 first bucket collapsed every real episode into
# one bar. A tail bin past 0.015 still catches curator-threshold outliers.
SMOOTHNESS_BINS = [0.0, 0.002, 0.004, 0.006, 0.008, 0.010, 0.015]

CUBE_BUCKETS = (0, 1, 2, 3)


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | tuple[None, None]:
    """95% Wilson score interval -- stable at the small n a booth demo will
    actually have (binomial-normal approximation breaks down there)."""
    if n == 0:
        return (None, None)
    phat = successes / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def smoothness_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    for lo, hi in zip(SMOOTHNESS_BINS, SMOOTHNESS_BINS[1:]):
        if lo <= value < hi:
            return f"{lo:.3f}-{hi:.3f}"
    return f">={SMOOTHNESS_BINS[-1]:.3f}"


@dataclass
class VersionStats:
    episode_count: int = 0
    success_count: int = 0
    cubes_placed: dict[int, int] = field(default_factory=lambda: {b: 0 for b in CUBE_BUCKETS})
    smoothness_hist: dict[str, int] = field(default_factory=dict)
    verdict_counts: dict[str, int] = field(default_factory=dict)
    _cubes_sum: int = 0
    _cubes_n: int = 0
    _smoothness_sum: float = 0.0
    _smoothness_n: int = 0

    @property
    def success_rate(self) -> float | None:
        return self.success_count / self.episode_count if self.episode_count else None

    @property
    def success_ci(self) -> tuple[float | None, float | None]:
        return wilson_ci(self.success_count, self.episode_count)

    @property
    def avg_cubes_placed(self) -> float | None:
        return self._cubes_sum / self._cubes_n if self._cubes_n else None

    @property
    def mean_smoothness(self) -> float | None:
        """Mean avg_smoothness of *successful* episodes only.

        Failed episodes often barely move (timeout, missed grasp), which
        produces a tiny smoothness number. Averaging those in makes a worse
        policy look smoother — the opposite of the demo claim.
        """
        return self._smoothness_sum / self._smoothness_n if self._smoothness_n else None

    @property
    def smoothness_n(self) -> int:
        return self._smoothness_n

    @property
    def cube_bins_reconcile(self) -> bool:
        """Sanity check surfaced in the UI: bucketed cube counts should sum
        to the episode count. A mismatch means some episodes are missing
        `cubes_placed` -- an honest "this data is incomplete" signal rather
        than something to silently paper over."""
        return sum(self.cubes_placed.values()) == self.episode_count

    @property
    def success_matches_full_cubes(self) -> bool:
        """task_success asks "did the arm complete the placement task",
        cubes_placed==3 asks "did all three cubes land on the tray" -- they
        should agree. A mismatch means the two signals disagree about what
        counts as success and the numbers shouldn't be trusted blindly."""
        return self.success_count == self.cubes_placed.get(3, 0)

    @property
    def success_rate_incomplete(self) -> bool:
        """True when every episode we've seen for this version carries a
        curator "pass" verdict and none carry "reject" -- the signature of
        having only curated (Kafka/MinIO episodes-curated) data loaded, with
        episodes-rejected never having been read. The curator gates hard on
        task_success, so a curated-only population is ~100% success *by
        construction*, not because the policy is actually that good. Records
        with no verdict at all (e.g. controlled eval files, which aren't
        curator output) don't trip this -- there's nothing to be incomplete
        relative to."""
        pass_n = self.verdict_counts.get("pass", 0)
        reject_n = self.verdict_counts.get("reject", 0)
        return pass_n > 0 and reject_n == 0


def aggregate(records: list[dict]) -> dict[str, VersionStats]:
    """records must already be normalized (schema.normalize output)."""
    by_version: dict[str, VersionStats] = defaultdict(VersionStats)
    for r in records:
        v = by_version[r["model_version"]]
        v.episode_count += 1
        if r["task_success"]:
            v.success_count += 1
        cubes = r.get("cubes_placed")
        if cubes in CUBE_BUCKETS:
            v.cubes_placed[cubes] += 1
            v._cubes_sum += cubes
            v._cubes_n += 1
        # Smoothness is a quality signal about *successful* motion. Failures
        # still count toward success rate and the cube histogram.
        if r["task_success"]:
            smoothness = r.get("avg_smoothness")
            bucket = smoothness_bucket(smoothness)
            v.smoothness_hist[bucket] = v.smoothness_hist.get(bucket, 0) + 1
            if smoothness is not None:
                v._smoothness_sum += smoothness
                v._smoothness_n += 1
        verdict = r.get("curation_verdict")
        if verdict:
            v.verdict_counts[verdict] = v.verdict_counts.get(verdict, 0) + 1
    return dict(by_version)
