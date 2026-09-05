# hp-roscon-eval-dashboard

Read-only evaluation dashboard for the [hp-roscon-flywheel](https://github.com/RHPhysicalAI/hp-roscon-flywheel)
demo. Answers one question, per `model_version`: **is this policy actually
better than the last one?**

It never writes to Kafka, MinIO, or the sim, and it never runs on the demo
box — it runs on your own machine, over Tailscale, against the endpoints
below.

## Two panels, deliberately not conflated

- **Controlled evaluation** (primary claim) — the fixed-seed green-cube-shift
  A/B study: baseline policy vs. the same policy fine-tuned on 5/10/20/40
  curated success episodes. Prefer `EVAL_DIR`
  (`/data/eval/<model_version>.json`, array of full episode records). In
  file mode, if that's missing, `/records` is used instead so a single
  directory of files still fills the comparison (the ASK). Always
  file-based, because these records aren't published to Kafka/MinIO yet
  (see "Current limitation" below).
- **Operational (live)** — the running flywheel's curated + rejected
  population. Health-of-the-pipeline signal, not the controlled claim.
  `SOURCE_MODE=live` reads it over Tailscale; `SOURCE_MODE=files` replays it
  from a directory of exported records.

Both panels compute success rate, cube-placement distribution, and a
smoothness histogram the same way — one normalize/aggregate code path
(`schema.py` → `aggregate.py`) regardless of source, which is what makes
"file replay reproduces the same numbers as live" true by construction.

**These two numbers are expected to disagree, and that's not a bug.** The
controlled evaluation resets the arm to a clean state every episode; the live
flywheel doesn't, so one failure can cascade into the next episode. A
controlled baseline might read 74% (37/50) while the live loop reads ~38%
over the same period — neither is wrong, they're answering different
questions. They're never combined into one chart.

In file mode the same directory is never loaded into both panels. If you only
mount `/records`, that tree is the comparison (the ASK's "directory of
record files"). Operational stays empty and is hidden. Mount a *second*,
different tree if you also want the live-flywheel export alongside.

## Success rate — exact definition

For each `model_version`:

```
eligible   = [e for e in episodes if e.model_version == version and e.has_failure is not True]
successes  = sum(1 for e in eligible if e.task_success is True)
success_rate = successes / len(eligible)
```

Two things this deliberately gets right:

- **Computed from `task_success`, never from `curation_verdict`.** Curation
  answers "should this become training data?"; task success answers "did the
  arm place all three cubes?" `aggregate.py` never reads `curation_verdict`
  for the rate itself — only `schema.normalize()` carries it through, for the
  completeness check below.
- **The denominator must include rejected episodes, or the number is
  meaningless.** The curator gates hard on `task_success` — a curated-only
  population (Kafka/MinIO `episodes-curated` alone) reads ~100% *by
  construction*, not because the policy is that good. If a version's loaded
  episodes are all curator "pass" verdicts and none are "reject"
  (`success_rate_incomplete` in the API), the dashboard does **not** show a
  percentage — it shows "Incomplete result — curated records only. Rejected
  episodes are required for success rate." A version with no curator verdict
  at all (controlled eval files, which aren't curator output) isn't subject
  to this check — that source is trusted to hand over its complete
  population by contract.

**Smoothness (mean and histogram) is computed on successful episodes only.**
Failed episodes often barely move, which produces a tiny `avg_smoothness`
and would make a worse policy look smoother — the opposite of the demo
claim. The cube-placement distribution still includes failures.

## Data integrity checks (Data Integrity panel)

| Check | What it verifies |
|---|---|
| Both outcomes loaded | Per version: at least one rejected-verdict episode alongside curated ones (or no verdict at all) — else success rate is hidden |
| Injected failures excluded | Count of `has_failure=true` records dropped before scoring |
| Cube-count reconciliation | `sum(cubes_placed buckets) == episode_count` per version |
| Success consistency | `task_success` count matches the 3-cube count per version |
| Deduplication | Same `episode_id` never counted twice; flags it if seen with a *different* verdict (e.g. present in both curated and rejected) |
| Lineage | Static caveat: `model_version` grouped as-is, known mislabeling not corrected |
| Replay | No persisted state — restated from the "no persisted state" section above |
| Baseline identified | A version tagged `dataset_size: 0` in `versions.yaml` is Baseline; without that, nothing is labeled baseline (name order is not a role) |
| Comparable runs | **Not automatically checkable** — the episode contract has no seed/reset-mode field, so same-seed/same-reset can't be verified from data alone; called out as an open gap rather than faked green |

Strongest warning signs to watch for (from the brief): every version reading
exactly 100%, cube-distribution total not matching the success denominator,
3-cube count not matching success count, a version with an unexplained
episode-count shortfall, and the same `episode_id` appearing in both curated
and rejected data. All but "comparable runs" are computed and surfaced live;
an exact 100% on an already-complete population still displays (it's real
data) but carries a "verify" warning badge rather than passing silently.

## Design decisions worth knowing about

- **No persisted state.** Each panel is one in-memory dict keyed by
  `episode_id`, rebuilt from its source(s) on every process start. Kafka
  uses a fresh, never-committed consumer group each run
  (`auto_offset_reset=earliest`), so a restart always replays the whole
  topic — nothing to get out of sync.
- **Kafka is a notification, MinIO is authoritative.** The `episode-manifests`
  message only carries `{episode_id, s3_uri, ...}`; on receipt, the dashboard
  fetches the full record from MinIO via `s3_uri` and recomputes. Rejected
  episodes never get a Kafka notification (only `sync-agent`, on curation
  passes, publishes), so `episodes-rejected` is additionally re-listed every
  30s. The UI shows `Rejected records last checked <time>` so a stale number
  is visible rather than silently trusted — the upstream rejected-mirror job
  runs every 5 minutes, so this can lag by that much.
- **Injected demo failures are excluded everywhere.** Any record with
  `has_failure == true` is dropped before it reaches the aggregate — that
  field marks a curation-gate test fixture, not a real policy outcome, and
  counting it would understate success rate. The dashboard reports how many
  were dropped (Data Integrity panel).
- **`dataset_path` is ignored.** Per the episode JSON contract, this field is
  landing soon; `schema.normalize()` only reads what it needs.
- **`model_version` is grouped as-is.** Existing mislabeled data is not
  corrected here — that's a separate relabel effort. The UI surfaces this as
  a standing caveat rather than hiding it.
- **Duplicate `episode_id` = last write wins.** Makes re-listing a bucket, or
  a Kafka-triggered re-fetch of something already seen, a safe no-op.

## Current limitation: controlled files aren't wired into Kafka/MinIO

The controlled fixed-seed evaluation files (`/data/eval/<model_version>.json`)
are not currently published to Kafka or MinIO — they have to be handed over
as files. Live flywheel statistics (curated/rejected) can be loaded over
Tailscale; the central "did the policy improve" comparison currently can't.
Flagging this as a real gap per the brief, not routing around it.

## Run it

### File mode — no Tailscale, no MinIO, no Kafka

```
docker build -t evaluation-dashboard .
docker run --rm -p 8080:8080 \
  -v ./episode-records:/records:ro \
  -e SOURCE_MODE=files \
  evaluation-dashboard
```

Open http://localhost:8080. Header shows **Source: saved files**. Point
`-v .../episode-records:/records:ro` at any directory of `*.json` episode
records — one object per file, or a JSON array per file (the documented
eval handover format). Flat or nested like MinIO
`<model_version>/<episode_id>.json` both work. That directory is the
**comparison** view (not a second "operational" copy). `tests/fixtures/`
has 40 sample records
(18 curated + 22 rejected, from Jeremy's `olga-fixtures`) across two
`model_version`s — **synthetic, not real** (see `tests/fixtures/README.md`):
`fixture-strong-v0` (17/20 success) and `fixture-weak-v0` (1/20 success),
deliberately with a real gap so the comparison view has something to show
before live multi-version data exists. No dataset-size mapping is included
for these — don't infer one from the names. Until `config/versions.yaml`
tags a version with `0`, nothing is labeled Baseline.

### Live mode — Kafka + MinIO over Tailscale

Requires the SNO node (`10.0.0.49`) to be on your tailnet, and NodePort
Services for `edge-kafka` and `minio` (see "Hooking up to the cluster" —
they don't exist yet as of this writing).

```
docker run --rm -p 8080:8080 --env-file .env.local \
  -e SOURCE_MODE=live \
  -e S3_ENDPOINT=http://10.0.0.49:30900 \
  -e S3_CURATED_BUCKET=episodes-curated \
  -e S3_REJECTED_BUCKET=episodes-rejected \
  -e KAFKA_BOOTSTRAP=10.0.0.49:30903 \
  -e KAFKA_TOPIC=episode-manifests \
  evaluation-dashboard
```

`.env.local` (never committed — see `.gitignore`) holds:
```
S3_ACCESS_KEY=olga-readonly
S3_SECRET_KEY=<your-secret>
```

### Controlled-evaluation files (either mode)

```
-v ./eval:/data/eval:ro
```

Mount a directory of `<model_version>.json` files (each an array of full
episode records for that version) at `/data/eval` (or set `EVAL_DIR`). If
absent, the controlled panel just shows "no data yet" rather than fabricating
placeholder numbers.

### Config: version → dataset size

Copy `config/versions.example.yaml` to `config/versions.yaml` and fill in
the mapping once it's provided; mount it at `/app/config/versions.yaml` or
point `VERSIONS_FILE` elsewhere. Drives the learning-curve chart and the
"+N curated episodes" label on each card.

## Where it lives / how you get there

This dashboard is a **separate app on your own machine** — it does not live
in the flywheel cluster or repo. You get to it by opening
`http://localhost:8080` in a new tab.

Adding a "Policy Evaluation" nav link on the existing flywheel dashboard
(`http://10.0.0.49:30801`) that opens this one, plus a "Back to Live
Flywheel" link here (via a `LIVE_DASHBOARD_URL` env var, defaulting to
`http://10.0.0.49:30801`), is deferred until the rest of this is running end
to end — see the project memory. It needs a small edit to
`gitops/flywheel/dashboard.yaml` in the `hp-roscon-flywheel` repo, which
isn't checked out here.

## Hooking up to the cluster — what's missing today

1. **Kafka and MinIO are ClusterIP-only.** `edge-kafka.flywheel.svc:9092`
   and `minio.minio.svc:9000` (and an `episodes-rejected` bucket, if it
   doesn't exist yet) only resolve inside the cluster. NodePort Services are
   needed for both (`30900` for MinIO API, `30903` for Kafka) — a gitops
   change, not pipeline code.
2. **Kafka needs a second listener, not just a NodePort.** `edge-kafka`'s
   `server.properties` advertises `PLAINTEXT://edge-kafka.flywheel.svc:9092`
   for all listeners. A laptop client connects fine to the NodePort
   initially, then hangs on metadata refresh, because Kafka hands back that
   unresolvable internal address. Needs a second `EXTERNAL` listener
   advertising the node's tailscale IP + NodePort, e.g.:
   ```
   listeners=PLAINTEXT://:9092,EXTERNAL://:9094,CONTROLLER://:9093
   advertised.listeners=PLAINTEXT://edge-kafka.flywheel.svc:9092,EXTERNAL://<tailscale-ip>:30903,...
   listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
   ```
   MinIO doesn't have this problem — S3 clients only ever talk to the
   endpoint you give them, no broker-style redirect.
3. **Read-only MinIO credentials** (`olga-readonly` or equivalent) need to be
   provisioned — the sync-agent's existing `hub-credentials` secret is a
   read/write key, not appropriate to hand to a laptop.

Until these land, `SOURCE_MODE=files` is the only path that works end to end
from a laptop.

## Layout

```
src/eval_dashboard/
  schema.py             # normalizes any source's record into one shape
  aggregate.py           # pure per-version stats: success rate (+ Wilson CI),
                          # cubes_placed, smoothness histogram, cube-count sanity check
  sources/
    file_source.py       # directory of *.json (offline mode + controlled-eval files)
    kafka_source.py       # episode-manifests notifications, replayed from earliest every run
    minio_source.py        # bucket listing (full replay) + single-object fetch by s3_uri
  main.py                 # Store (dedup/filter/merge) + SOURCE_MODE wiring
  web/app.py               # read-only Flask API + static UI
  web/static/               # index.html, dashboard.js, styles.css (vanilla, no build step)
tests/
  test_aggregate.py         # aggregation math
  test_store.py               # dedup + has_failure exclusion
  test_file_source.py           # against tests/fixtures/ (synthetic sample records)
  fixtures/                       # 18 curated + 22 rejected synthetic episode records, 2 versions
config/versions.example.yaml
```
