# hp-roscon-eval-dashboard

Read-only dashboard for the
[hp-roscon-flywheel](https://github.com/RHPhysicalAI/hp-roscon-flywheel) demo.
Surfaces **observed** policy outcomes per `model_version` — success rate (with
Wilson confidence intervals) as the primary metric, and mean smoothness among
successful episodes as a secondary signal.

It does **not** prove one policy is statistically better than another. The UI
uses conservative language: “higher observed success rate,” not “better.”

Runs on your machine. Live mode connects to Kafka and MinIO over Tailscale.
Never writes to Kafka, MinIO, or the sim.

## What it shows

One view, per `model_version`, fed by whichever source is active — a
directory of files, or Kafka+MinIO — so file replay and live mode produce
identical numbers for the same underlying records:

| Role | Metric | Compare against |
|---|---|---|
| Primary | Success rate | Baseline (0 curated fine-tune episodes) and the previous dataset-size rung |
| Secondary | Smoothness of successes (lower = smoother) | Selected policies — relative ranking only |

Pick up to three versions (Policy A/B/C) to see them side by side in the
cards, the cube-placement chart, and the smoothness histogram.

## Sources

| `SOURCE_MODE` | Reads from | Notes |
|---|---|---|
| `files` (default) | A directory of episode JSON records (`RECORDS_DIR`) | The booth/offline mode — no Kafka or MinIO needed |
| `live` | Kafka (`episode-manifests`) + MinIO (`episodes-curated`), merged with the MinIO `episodes-rejected` bucket | Rejected episodes never get a Kafka notification, so they're polled separately every 30s |

Success rate needs both curated *and* rejected episodes in the denominator —
a curated-only population reads ~100% by construction, since the curator
gates hard on `task_success`. This is the single most important thing the
dashboard gets right; see "Success rate" below.

## Success rate

For each `model_version`:

```
eligible     = episodes where has_failure is not true and the record is valid
successes    = count where task_success is true
success_rate = successes / len(eligible)
```

- Based on **`task_success`** (all three cubes placed), never on `curation_verdict`.
- **Invalid records are excluded**, not counted as failures.
- **Curated-only detection:** if every loaded episode has a curator “pass” and
  none have “reject,” the rate is hidden (~100% by construction). Seeing one
  reject proves the slice is not pass-only; it does **not** prove every reject
  in the bucket was loaded.

**Smoothness** is averaged over successful episodes only. Failures often barely
move, which would make a worse policy look smoother.

## Data integrity

The UI runs automated checks before you trust the numbers:

- Curated-only detection (not full coverage proof)
- Injected test failures (`has_failure`) excluded
- Malformed records excluded
- Cube-placement buckets reconcile to episode count
- `task_success` agrees with 3-cube count
- Duplicate `episode_id`s: identical re-lists ignored; conflicts quarantined
- Baseline version identified from config (`dataset_size: 0`)

## How it works

- **No persisted state** — rebuilt from source on every start.
- **Kafka notifies, MinIO is authoritative** — rejected episodes are polled
  separately because they lack Kafka notifications. Rejected-bucket mirror lag
  (~5 min upstream) means the numbers can be stale; the UI shows last check time.
- **Lineage rules, applied on every path**: drop leaked `eval-*` tags (a
  2026-09-08 bug let eval-harness test runs leak into production Kafka/MinIO);
  group the legacy Phase-2 tags `soarm-act-10ep-10k` and `soarm-act-v1` as
  `pre-teacher`.
- **Conflicting duplicates are quarantined**, not silently overwritten.

## Run it

```bash
./run.sh files   # offline — reads RECORDS_DIR (bundled test fixtures by default)
./run.sh live    # Tailscale + Kafka/MinIO — needs .env.local with read-only S3 keys
```

Uses podman when available, otherwise docker (`CONTAINER=` to override). Opens
[http://localhost:8080](http://localhost:8080) by default (`PORT=` to override).
No in-app mode switch — restart with the other command.

`./run.sh` with no args lists environment overrides.

### Live mode prerequisites

1. Tailscale connected; cluster node `10.0.0.49` reachable
2. NodePorts: MinIO `30900`, Kafka `30903`
3. `.env.local` with read-only MinIO credentials (never commit — copy
   `.env.local.example` and fill in real values):

   ```
   S3_ACCESS_KEY=<your scoped read-only access key>
   S3_SECRET_KEY=<from cluster admin>
   ```

Cluster and data-contract details: [hp-roscon-flywheel data contract](https://github.com/RHPhysicalAI/hp-roscon-flywheel/blob/desktop-gpu-split/docs/data-contract-eval-dashboard.md).

### Version mapping

Copy the example config to `config/versions.yaml` (auto-loaded by `run.sh`).
Maps each `model_version` to its curated training-set size, driving the
learning curve and Baseline / Fine-tuned labels. A version with no entry still
appears everywhere else, labeled **Unmapped** — this mapping is the only thing
that removes that label:

```yaml
upstream-act-teacher: 0    # baseline / teacher-as-shipped
act-v2-ft160: 160          # fine-tuned on 160 curated successes
```

### Where it lives

This dashboard is a separate app on your own machine — it doesn't live in the
flywheel cluster or repo, and there's no link to it from the live flywheel
screen. Open a new tab to `http://localhost:$PORT` (8080 by default) after
`./run.sh`.

The reverse direction — the "← Back to Live Flywheel" link in the header —
points at `LIVE_DASHBOARD_URL`, an environment variable rather than a hardcoded
path, since it's pointing at a *different* machine's dashboard than the one this
process is running on:

```bash
LIVE_DASHBOARD_URL=http://10.0.0.49:30801 ./run.sh live   # default value shown
```

Adding the reverse link — a "Policy Evaluation" tab on the live flywheel
dashboard that opens this one — needs an edit to
`gitops/flywheel/dashboard.yaml` in `hp-roscon-flywheel`, a repo not checked
out here. Deferred until this dashboard itself is running end to end.

### Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src SOURCE_MODE=files RECORDS_DIR=tests/fixtures
python -m eval_dashboard.main
pytest
```
