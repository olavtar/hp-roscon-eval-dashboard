const SERIES_VARS = ['--series-1', '--series-2', '--series-3'];
const REFRESH_MS = 5000;
const POLICY_LABELS = ['Policy A', 'Policy B', 'Policy C'];
const EVIDENCE_PAGE_SIZE = 200;

function makeSelectionState() { return { selected: ['', '', ''], lastKey: '' }; }
const selection = makeSelectionState();
let lastStats = null;
let renderGeneration = 0;
const evidenceGroups = new Map();
let evidenceGroupSeq = 0;

function esc(s) {
  return String(s).replace(/[&<>"'`]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;',
  }[c]));
}

function seriesColor(slotIndex) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(SERIES_VARS[slotIndex] || SERIES_VARS[SERIES_VARS.length - 1]).trim();
}

function sortedVersions(versionsObj) {
  return Object.entries(versionsObj).sort((a, b) => {
    const da = a[1].dataset_size, db = b[1].dataset_size;
    if (da == null && db == null) return a[0].localeCompare(b[0]);
    if (da == null) return 1;
    if (db == null) return -1;
    return da - db;
  }).map(([name]) => name);
}

function activeSelected(state) {
  return state.selected.filter(Boolean);
}

function colorSlotFor(version, versionList) {
  const idx = versionList.indexOf(version);
  return idx >= 0 && idx < 3 ? idx : -1;
}

function findBaselineKey(versionsObj) {
  // Only a version tagged with 0 fine-tune episodes is the baseline.
  // Alphabetical order is not a role.
  const zeros = Object.entries(versionsObj)
    .filter(([, s]) => s.dataset_size === 0)
    .map(([k]) => k);
  return zeros.length === 1 ? zeros[0] : null;
}

function roleFor(s, isBaseline) {
  if (isBaseline || s.dataset_size === 0) {
    return { badge: 'baseline', label: 'Baseline', meta: '+0 curated fine-tune episodes' };
  }
  if (s.dataset_size != null) {
    return { badge: 'finetuned', label: 'Fine-tuned', meta: `+${s.dataset_size} curated episodes` };
  }
  return { badge: 'untagged', label: 'Unmapped', meta: 'No training-set size yet — not labeled baseline or fine-tune' };
}

function finetuneEpisodesLabel(datasetSize) {
  if (datasetSize == null) return '—';
  if (datasetSize === 0) return '0 (baseline)';
  return String(datasetSize);
}

function pct(x) { return x == null ? '--' : (x * 100).toFixed(0) + '%'; }

function ciSentence(s) {
  const [lo, hi] = s.success_ci || [null, null];
  const n = s.episode_count;
  if (lo == null || hi == null || !n) return '';
  const ep = n === 1 ? 'episode' : 'episodes';
  return `Based on ${n} observed ${ep}, we're 95% confident the true success rate is somewhere between ${pct(lo)} and ${pct(hi)}.`;
}

function niceTicks(maxCount, targetLines = 4) {
  const step = Math.max(1, Math.ceil(maxCount / targetLines));
  return { step, top: step * targetLines };
}
function fmtNum(x, d = 4) { return x == null ? '--' : x.toFixed(d); }
function fmtDuration(s) { return s == null ? '--' : `${Number(s).toFixed(1)}s`; }

function originLabel(origin) {
  if (!origin) return '';
  if (origin.startsWith('files:')) return origin.slice(6);
  if (origin.startsWith('live')) return 'Kafka + MinIO';
  return origin;
}

async function fetchStats() {
  const r = await fetch('/api/stats');
  return r.json();
}

async function fetchEpisodes(versions, offset = 0) {
  const query = new URLSearchParams({ limit: EVIDENCE_PAGE_SIZE, offset });
  versions.forEach(v => query.append('model_version', v));
  const response = await fetch(`/api/episodes?${query}`);
  if (!response.ok) throw new Error(`episode request failed (${response.status})`);
  return response.json();
}

function renderHeader(stats) {
  const isLive = stats.source_mode === 'live';
  document.getElementById('source-label').textContent = isLive ? 'Live via Tailscale' : 'Saved files';
  document.getElementById('source-chip').classList.toggle('live', isLive);
  document.getElementById('loaded-chip').textContent = 'Loaded ' + new Date().toLocaleTimeString();
  const back = document.getElementById('backlink');
  back.href = stats.live_dashboard_url;
  document.getElementById('origin-label').textContent = originLabel(stats.snapshot.origin);
}

function renderPicker(elId, allVersions, versionsObj, state) {
  const el = document.getElementById(elId);
  if (allVersions.length === 0) {
    el.innerHTML = '';
    state.lastKey = '';
    state.selected = ['', '', ''];
    return;
  }
  if (!state.selected.some(Boolean)) {
    // Demo default: compare the first two mapped versions (teacher vs fine-tune).
    // Policy C stays empty until the viewer picks a third.
    state.selected = [allVersions[0] || '', allVersions[1] || '', ''];
  } else {
    state.selected = state.selected.map(v => (v && allVersions.includes(v)) ? v : '');
  }
  const key = allVersions.join('\0') + '|' + state.selected.join('\0');
  if (key === state.lastKey) return;
  state.lastKey = key;

  // Options already picked in another slot stay selectable (never disabled)
  // -- picking one swaps the two slots (see the change handler below), so
  // reordering/swapping never requires clearing a slot first. The label
  // just says where it currently lives, since a bare <option> can't be
  // styled to hint at that otherwise.
  const optionTag = (v, selectedValue, elsewhereLabel) => {
    const sel = selectedValue === v ? ' selected' : '';
    const suffix = elsewhereLabel ? ` (currently ${elsewhereLabel})` : '';
    return `<option value="${esc(v)}"${sel}>${esc(v)}${esc(suffix)}</option>`;
  };

  el.innerHTML = POLICY_LABELS.map((label, i) => {
    const elsewhere = {};
    state.selected.forEach((v, j) => { if (v && j !== i) elsewhere[v] = POLICY_LABELS[j]; });
    let opts = '<option value="">—</option>';
    allVersions.forEach(v => {
      opts += optionTag(v, state.selected[i], elsewhere[v]);
    });
    return `<div class="field"><label>${label}</label><select data-slot="${i}">${opts}</select></div>`;
  }).join('');
  el.querySelectorAll('select').forEach(sel => {
    sel.addEventListener('change', () => {
      const slot = +sel.dataset.slot;
      const newValue = sel.value;
      const previousValue = state.selected[slot];
      if (newValue) {
        // Picking a version that's already in another slot swaps the two
        // slots instead of being blocked -- lets you reorder Policy A/B/C
        // by just picking directly, no need to clear one first.
        const conflictSlot = state.selected.findIndex((v, j) => j !== slot && v === newValue);
        if (conflictSlot !== -1) state.selected[conflictSlot] = previousValue;
      }
      state.selected[slot] = newValue;
      state.lastKey = '';
      // Repaint from cached stats immediately — render() only updates after fetchStats().
      if (lastStats) {
        renderViews(lastStats);
        renderEvidenceGroups(lastStats.snapshot.versions);
      }
      render();
    });
  });
}

function renderCards(containerId, versionsObj, versionList) {
  const container = document.getElementById(containerId);
  if (versionList.length === 0) {
    container.innerHTML = '';
    return;
  }
  const baselineKey = findBaselineKey(versionsObj);
  const baseline = baselineKey ? versionsObj[baselineKey] : null;
  const baselineRate = baseline && !baseline.success_rate_incomplete ? baseline.success_rate : null;

  // "Smoothest of the compared set" is a real, relative ranking among only
  // the versions on screen right now -- not an invented absolute
  // smooth/jerky cutoff. There's no documented threshold for that at this
  // scale (the curator's own 0.15 gate is ~30x every real observed value),
  // so a fabricated category would be worse than no category.
  const smoothnessValues = versionList
    .map(v => (versionsObj[v] || {}).mean_smoothness)
    .filter(x => x != null);
  const minSmoothness = smoothnessValues.length > 1 ? Math.min(...smoothnessValues) : null;

  container.innerHTML = versionList.map((v) => {
    const s = versionsObj[v];
    if (!s) return '';
    const slot = colorSlotFor(v, versionList);
    const color = slot >= 0 ? seriesColor(slot) : 'var(--text-muted)';
    const isBaseline = v === baselineKey;
    const role = roleFor(s, isBaseline);

    if (s.success_rate_incomplete) {
      return `
        <article class="model-card" style="--series:${color}">
          <div class="model-title">
            <span class="series-dot"></span>
            <span class="model-id">${esc(v)}</span>
            <span class="badge ${role.badge}">${role.label}</span>
          </div>
          <div class="model-meta">${s.episode_count} curated episode(s) loaded</div>
          <div class="check-title" style="margin-top:8px"><span class="warning">!</span> Incomplete result</div>
          <p style="color:var(--text-muted);font-size:11px;margin:4px 0 0 20px">
            Curated records only. Rejected episodes are required for success rate &mdash;
            a curated-only population is ~100% success by construction, not a real rate.
          </p>
        </article>`;
    }

    let delta = '';
    if (baselineKey && !isBaseline && baselineRate != null && s.success_rate != null) {
      const pts = (s.success_rate - baselineRate) * 100;
      const cls = pts > 0 ? 'up' : pts < 0 ? 'down' : 'same';
      const sign = pts > 0 ? '+' : '';
      delta = `<div class="delta ${cls}">${sign}${pts.toFixed(0)} pts observed vs baseline</div>`;
    } else if (isBaseline) {
      delta = `<div class="delta same">reference policy</div>`;
    }
    const exactly100 = s.success_rate === 1 && s.episode_count > 0
      ? ' <span class="check-title" style="display:inline"><span class="warning">!</span> verify</span>' : '';
    const smoothN = s.smoothness_n != null ? s.smoothness_n : s.success_count;
    return `
      <article class="model-card" style="--series:${color}">
        <div class="model-title">
          <span class="series-dot"></span>
          <span class="model-id">${esc(v)}</span>
          <span class="badge ${role.badge}">${role.label}</span>
        </div>
        <div class="model-meta">${esc(role.meta)}</div>
        <div class="rate-row">
          <div class="rate">${pct(s.success_rate)}</div>
          <div class="fraction">${s.success_count} / ${s.episode_count} successes</div>
          ${delta}
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${s.success_rate != null ? s.success_rate * 100 : 0}%"></div></div>
        <div class="ci-text">${esc(ciSentence(s))}${exactly100}</div>
        <div class="mini-grid">
          <div title="Average of each episode’s peak cubes on the tray, including failures">
            <span>Mean cubes on tray</span>
            <strong>${s.avg_cubes_placed != null ? s.avg_cubes_placed.toFixed(2) : '--'} / 3</strong>
            <span>peak per episode, all ${s.episode_count} runs</span>
          </div>
          <div title="Mean absolute per-joint delta between consecutive joint commands, successful episodes only -- smaller number = smoother motion">
            <span>Mean smoothness of successes (lower = smoother)</span>
            <strong>${fmtNum(s.mean_smoothness)}${s.mean_smoothness != null && s.mean_smoothness === minSmoothness ? ' <span class="badge finetuned" style="font-size:9px;vertical-align:middle">smoothest here</span>' : ''}</strong>
            <span>n=${smoothN == null ? 0 : smoothN}</span>
          </div>
        </div>
      </article>`;
  }).join('');
}

function svgEl(tag, attrs) {
  return `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(' ')}/>`;
}

function renderLearningCurve(versionsObj) {
  const points = Object.entries(versionsObj)
    .filter(([, s]) => s.dataset_size != null && s.success_rate != null && !s.success_rate_incomplete)
    .sort((a, b) => a[1].dataset_size - b[1].dataset_size);
  const svg = document.getElementById('learning-curve');
  const incompleteCount = Object.values(versionsObj).filter(s => s.success_rate_incomplete).length;
  if (points.length === 0) {
    const msg = incompleteCount > 0
      ? 'Tagged versions are curated-only — rejected episodes are required before plotting a rate'
      : 'No version → dataset-size map yet (config/versions.yaml). Curve appears once a version is tagged 0, 10, 40, …';
    svg.innerHTML = `<text x="360" y="130" text-anchor="middle">${esc(msg)}</text>`;
    return;
  }
  const W = 720, H = 260, padL = 60, padR = 20, padT = 20, padB = 40;
  const xs = points.map(([, s]) => s.dataset_size);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const x = v => padL + (xMax === xMin ? (W - padL - padR) / 2 : (v - xMin) / (xMax - xMin) * (W - padL - padR));
  const y = v => padT + (1 - v) * (H - padT - padB);
  let grid = '';
  for (let g = 0; g <= 4; g++) {
    const yy = padT + (g / 4) * (H - padT - padB);
    grid += svgEl('line', { class: 'grid', x1: padL, y1: yy.toFixed(1), x2: W - padR, y2: yy.toFixed(1) });
    grid += `<text x="${padL - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end">${(100 - g * 25)}%</text>`;
  }
  const line = points.map(([, s]) => `${x(s.dataset_size).toFixed(1)},${y(s.success_rate).toFixed(1)}`).join(' ');
  const whiskers = points.map(([v, s]) => {
    const [lo, hi] = s.success_ci || [null, null];
    if (lo == null || hi == null) return '';
    const cx = x(s.dataset_size);
    const color = seriesColor(Math.max(0, colorSlotFor(v, activeSelected(selection))));
    const yHi = y(hi).toFixed(1), yLo = y(lo).toFixed(1);
    return `
      <line x1="${cx.toFixed(1)}" y1="${yHi}" x2="${cx.toFixed(1)}" y2="${yLo}" stroke="${color}" stroke-width="1.5" opacity="0.5"/>
      <line x1="${(cx - 4).toFixed(1)}" y1="${yHi}" x2="${(cx + 4).toFixed(1)}" y2="${yHi}" stroke="${color}" opacity="0.5"/>
      <line x1="${(cx - 4).toFixed(1)}" y1="${yLo}" x2="${(cx + 4).toFixed(1)}" y2="${yLo}" stroke="${color}" opacity="0.5"/>`;
  }).join('');
  const dots = points.map(([v, s]) => {
    const color = seriesColor(Math.max(0, colorSlotFor(v, activeSelected(selection))));
    return `
    <circle cx="${x(s.dataset_size).toFixed(1)}" cy="${y(s.success_rate).toFixed(1)}" r="5" fill="${color}"><title>${esc(v)}: ${pct(s.success_rate)} (n=${s.episode_count})</title></circle>
    <text x="${x(s.dataset_size).toFixed(1)}" y="${(y(s.success_rate) - 12).toFixed(1)}" text-anchor="middle" class="label">${pct(s.success_rate)}</text>
    <text x="${x(s.dataset_size).toFixed(1)}" y="${H - padB + 16}" text-anchor="middle">${s.dataset_size}</text>`;
  }).join('');
  svg.innerHTML = grid +
    svgEl('line', { class: 'axis', x1: padL, y1: padT, x2: padL, y2: H - padB }) +
    svgEl('line', { class: 'axis', x1: padL, y1: H - padB, x2: W - padR, y2: H - padB }) +
    `<polyline points="${line}" fill="none" stroke="${seriesColor(0)}" stroke-width="2.5"/>` +
    whiskers +
    dots +
    `<text x="${(padL + W - padR) / 2}" y="${H - 4}" text-anchor="middle" class="caption">Curated fine-tune episodes</text>`;
}

function cubeCount(cubesPlaced, bucket) {
  const c = cubesPlaced || {};
  return c[bucket] ?? c[String(bucket)] ?? 0;
}

function renderCubesTable(tableId, versionsObj, versionList) {
  const el = document.getElementById(tableId);
  if (!el) return;
  if (versionList.length === 0) {
    el.innerHTML = '';
    return;
  }
  const buckets = [0, 1, 2, 3];
  const header = buckets.map(b => {
    if (b === 0) return '<th>0 cubes <span class="col-hint">miss</span></th>';
    if (b === 3) return '<th>3 cubes <span class="col-hint">success</span></th>';
    return `<th>${b} cube${b === 1 ? '' : 's'}</th>`;
  }).join('');
  const rows = versionList.map((v, vi) => {
    const s = versionsObj[v] || {};
    const n = s.episode_count || 0;
    const color = seriesColor(vi);
    const cells = buckets.map(b => {
      const count = cubeCount(s.cubes_placed, b);
      const pct = n ? Math.round(100 * count / n) : 0;
      const cls = b === 3 ? ' class="placement-success"' : (b === 0 ? ' class="placement-miss"' : '');
      return `<td${cls}>${pct}%</td>`;
    }).join('');
    return `<tr>
      <td class="placement-policy"><span class="series-dot" style="background:${color}"></span>${esc(v)} <span class="placement-n">(${n} ep)</span></td>
      ${cells}
    </tr>`;
  }).join('');
  el.innerHTML = `
    <table class="placement-table">
      <thead><tr><th>Policy</th>${header}</tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function smoothnessKeys(edges) {
  const keys = [];
  for (let i = 0; i < edges.length - 1; i++) {
    keys.push(`${edges[i].toFixed(3)}-${edges[i + 1].toFixed(3)}`);
  }
  if (edges.length) keys.push(`>=${edges[edges.length - 1].toFixed(3)}`);
  return keys;
}

function xForSmoothness(value, edges, padL, barW) {
  if (value == null || !edges.length) return null;
  for (let i = 0; i < edges.length - 1; i++) {
    if (value >= edges[i] && value < edges[i + 1]) {
      const t = (value - edges[i]) / (edges[i + 1] - edges[i] || 1);
      return padL + (i + t) * barW;
    }
  }
  return padL + (edges.length - 1) * barW;
}

function renderSmoothnessChart(chartId, snapshot, versionList) {
  const svg = document.getElementById(chartId);
  const versionsObj = snapshot.versions || {};
  if (versionList.length === 0) { svg.innerHTML = ''; return; }
  const edges = snapshot.smoothness_bin_edges || [];
  let keys = smoothnessKeys(edges);
  const overflow = keys[keys.length - 1];
  const usedOverflow = versionList.some(v => ((versionsObj[v] || {}).smoothness_hist || {})[overflow]);
  if (overflow && !usedOverflow) keys = keys.slice(0, -1);
  if (keys.length === 0) {
    svg.innerHTML = `<text x="360" y="80" text-anchor="middle">No successful episodes with smoothness yet</text>`;
    return;
  }

  const W = 720, rowH = 72, padL = 150, padR = 16, padT = 10;
  const H = padT + rowH * versionList.length + 46;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const maxCount = Math.max(1, ...versionList.flatMap(v => keys.map(k => ((versionsObj[v] || {}).smoothness_hist || {})[k] || 0)));
  const barW = (W - padL - padR) / keys.length;
  let out = '';
  versionList.forEach((v, vi) => {
    const s = versionsObj[v] || {};
    const hist = s.smoothness_hist || {};
    const color = seriesColor(vi);
    const rowTop = padT + vi * rowH;
    const rowBase = rowTop + rowH - 18;
    const nSucc = s.success_count || 0;
    out += `<text x="4" y="${rowTop + 16}" class="label">${esc(v)}</text>`;
    out += `<text x="4" y="${rowTop + 33}" class="meta">${nSucc} successful · mean ${fmtNum(s.mean_smoothness)}</text>`;
    out += svgEl('line', { class: 'axis', x1: padL, y1: rowBase, x2: W - padR, y2: rowBase });
    keys.forEach((bin, bi) => {
      const count = hist[bin] || 0;
      const h = (count / maxCount) * (rowH - 24);
      const bx = padL + bi * barW;
      out += `<rect x="${bx.toFixed(1)}" y="${(rowBase - h).toFixed(1)}" width="${(barW - 2).toFixed(1)}" height="${h.toFixed(1)}" fill="${color}"><title>${bin}: ${count} successes</title></rect>`;
    });
    const mx = xForSmoothness(s.mean_smoothness, edges, padL, barW);
    if (mx != null && nSucc > 0) {
      out += `<line x1="${mx.toFixed(1)}" y1="${rowTop + 8}" x2="${mx.toFixed(1)}" y2="${rowBase}" stroke="${color}" stroke-width="2" stroke-dasharray="4 3"/>`;
    }
  });
  keys.forEach((bin, bi) => {
    // Bin keys are 3-decimal to match the backend's histogram dict keys
    // exactly (see aggregate.py) -- reformatted to 4 decimals here only
    // for display, so the tick precision matches the mean-value text
    // ("mean 0.0058") instead of looking inconsistent (3 vs 4 decimals).
    const edge = bin.startsWith('>=') ? bin.slice(2) : bin.split('-')[0];
    const label = (bin.startsWith('>=') ? '>=' : '') + parseFloat(edge).toFixed(4);
    out += `<text x="${(padL + bi * barW + barW / 2).toFixed(1)}" y="${H - 28}" text-anchor="middle">${label}</text>`;
  });
  out += `<text x="${(padL + W - padR) / 2}" y="${H - 6}" text-anchor="middle" class="caption">avg_smoothness of successes (lower = smoother)</text>`;
  svg.innerHTML = out;
}

function renderIntegrity(snapshot) {
  const el = document.getElementById('integrity-checks');
  const versions = Object.entries(snapshot.versions);
  const allReconcile = versions.every(([, s]) => s.cube_bins_reconcile);
  const allMatch = versions.every(([, s]) => s.success_matches_full_cubes);
  const anyIncomplete = versions.some(([, s]) => s.success_rate_incomplete);
  const noVerdictConflicts = (snapshot.duplicate_episode_ids || 0) === 0;
  const noFieldConflicts = (snapshot.conflicting_episode_ids || 0) === 0;
  const hasBaseline = findBaselineKey(snapshot.versions) != null;
  el.innerHTML = `
    <div class="check">
      <div class="check-title"><span class="${anyIncomplete ? 'warning' : 'good'}">${anyIncomplete ? '!' : '&check;'}</span> Curated-only detection</div>
      <p>${anyIncomplete
        ? 'At least one version has curator pass verdicts but zero reject verdicts — its success rate is hidden. This only proves the data is not curated-only; it does not prove every rejected episode was loaded.'
        : 'No version looks curated-only (pass verdicts with zero rejects), or carries no curator verdict at all.'}</p>
    </div>
    <div class="check">
      <div class="check-title"><span class="good">&check;</span> Injected failures excluded</div>
      <p>${snapshot.dropped_has_failure} episode(s) with has_failure=true dropped before scoring &mdash; a curation-gate test fixture, not a real outcome.</p>
    </div>
    <div class="check">
      <div class="check-title"><span class="${allReconcile ? 'good' : 'warning'}">${allReconcile ? '&check;' : '!'}</span> Cube-count reconciliation</div>
      <p>${allReconcile ? 'Cube-placement buckets sum to episode count for every version.' : 'At least one version has episodes missing cubes_placed &mdash; that version’s distribution is incomplete.'}</p>
    </div>
    <div class="check">
      <div class="check-title"><span class="${allMatch ? 'good' : 'warning'}">${allMatch ? '&check;' : '!'}</span> Success consistency</div>
      <p>${allMatch ? 'task_success count matches the 3-cube count for every version.' : 'At least one version disagrees between task_success and cubes_placed==3 &mdash; the two signals answer different questions and shouldn’t diverge.'}</p>
    </div>
    <div class="check">
      <div class="check-title"><span class="${noVerdictConflicts && noFieldConflicts ? 'good' : 'warning'}">${noVerdictConflicts && noFieldConflicts ? '&check;' : '!'}</span> Duplicate handling</div>
      <p>${noVerdictConflicts && noFieldConflicts
        ? 'Identical re-lists were ignored; no episode_id conflicts across scored fields.'
        : [
            snapshot.conflicting_episode_ids ? `${snapshot.conflicting_episode_ids} episode_id(s) quarantined after conflicting fields (model_version, task_success, cubes_placed, has_failure, or curation_verdict).` : '',
            snapshot.duplicate_episode_ids ? `${snapshot.duplicate_episode_ids} of those also had conflicting curator verdicts.` : '',
          ].filter(Boolean).join(' ') || 'Episode conflicts detected.'}</p>
    </div>
    <div class="check">
      <div class="check-title"><span class="${hasBaseline ? 'good' : 'warning'}">${hasBaseline ? '&check;' : '!'}</span> Baseline identified</div>
      <p>${hasBaseline
        ? `Baseline is ${esc(findBaselineKey(snapshot.versions))} (dataset_size = 0).`
        : 'No version is tagged with 0 fine-tune episodes in versions.yaml, so nothing is labeled Baseline. Alphabetical order is not a role.'}</p>
    </div>`;
}

function evidenceRowsMarkup(rows) {
  return rows.map(r => `
    <tr>
      <td>${esc((r.episode_id || '').slice(0, 8))}</td>
      <td class="${r.task_success ? 'success' : 'failed'}">${r.task_success ? '✓ Success' : '× Failed'}</td>
      <td>${r.cubes_placed != null ? r.cubes_placed + ' / 3' : '--'}</td>
      <td title="${r.task_success ? '' : 'Excluded from success-only mean'}">${r.task_success ? fmtNum(r.avg_smoothness) : '--'}</td>
      <td>${r.rollout_steps != null ? r.rollout_steps : '--'}</td>
      <td>${fmtDuration(r.rollout_duration_s)}</td>
    </tr>`).join('');
}

function groupMetaMarkup(version, versionsObj) {
  // Reuses the same badge classes/labels as the comparison cards above
  // (roleFor/findBaselineKey) so "Baseline"/"Fine-tuned" reads identically
  // in both places instead of a duller plain-text restatement here.
  const s = versionsObj[version] || {};
  const isBaseline = findBaselineKey(versionsObj) === version;
  const role = roleFor(s, isBaseline);
  const n = s.episode_count || 0;
  return `<span class="badge ${role.badge}">${esc(role.label)}</span><span class="evidence-group-count">${esc(role.meta)} · ${n} episode(s)</span>`;
}

function groupSkeletonMarkup(version, idx, versionsObj) {
  return `
  <details class="evidence-group" data-idx="${idx}">
    <summary class="evidence-group-summary">
      <span class="evidence-group-chevron" aria-hidden="true"></span>
      <span class="evidence-group-version">${esc(version)}</span>
      <span class="evidence-group-meta">${groupMetaMarkup(version, versionsObj)}</span>
    </summary>
    <div class="evidence-group-body">
      <table class="evidence-table">
        <colgroup>
          <col class="evidence-episode">
          <col class="evidence-result">
          <col class="evidence-cubes">
          <col class="evidence-smoothness">
          <col class="evidence-steps">
          <col class="evidence-duration">
        </colgroup>
        <thead>
          <tr>
            <th>Episode</th>
            <th>Result</th>
            <th>Cubes</th>
            <th title="Lower = smoother motion">Smoothness <span class="col-hint">&darr;=smoother</span></th>
            <th>Steps</th>
            <th title="Episode wall time from rollout.duration_s">Duration</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
      <div class="evidence-group-note"></div>
    </div>
  </details>`;
}

function updateGroupNote(group) {
  if (group.loadError) {
    group.noteEl.textContent = `Showing ${group.loaded} of ${group.totalEligible} · couldn’t load more rows`;
    return;
  }
  if (group.loading && group.loaded === 0) {
    group.noteEl.textContent = 'Loading…';
    return;
  }
  group.noteEl.textContent = `Showing ${group.loaded} of ${group.totalEligible} episode(s)`;
  if (group.loading) {
    group.noteEl.append(' · loading more…');
  } else if (!group.exhausted) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'load-more-btn';
    btn.textContent = 'Load more';
    btn.addEventListener('click', () => void loadGroupPage(group));
    group.noteEl.append(' · ', btn);
  }
}

async function loadGroupPage(group) {
  if (group.loading || group.exhausted) return;
  group.loading = true;
  group.loadError = false;
  updateGroupNote(group);
  try {
    const rows = await fetchEpisodes([group.version], group.offset);
    if (evidenceGroups.get(group.version) !== group) return; // selection changed mid-flight
    group.tbody.insertAdjacentHTML('beforeend', evidenceRowsMarkup(rows));
    group.loaded += rows.length;
    group.offset += rows.length;
    group.exhausted = rows.length < EVIDENCE_PAGE_SIZE || group.loaded >= group.totalEligible;
  } catch (err) {
    if (evidenceGroups.get(group.version) !== group) return;
    group.loadError = true;
    console.error('episode evidence request failed', err);
  } finally {
    if (evidenceGroups.get(group.version) === group) {
      group.loading = false;
      updateGroupNote(group);
    }
  }
}

function renderEvidenceGroups(versionsObj) {
  const container = document.getElementById('evidence-groups');
  const selected = new Set(activeSelected(selection));
  const orderedVersions = sortedVersions(versionsObj).filter(v => selected.has(v));

  if (orderedVersions.length === 0) {
    evidenceGroups.forEach(g => g.el.remove());
    evidenceGroups.clear();
    document.getElementById('evidence-note').textContent = '';
    return;
  }

  for (const [version, group] of evidenceGroups) {
    if (!selected.has(version)) {
      group.el.remove();
      evidenceGroups.delete(version);
    }
  }

  let prevEl = null;
  orderedVersions.forEach(version => {
    let group = evidenceGroups.get(version);
    if (!group) {
      const idx = evidenceGroupSeq++;
      container.insertAdjacentHTML('beforeend', groupSkeletonMarkup(version, idx, versionsObj));
      const el = container.querySelector(`[data-idx="${idx}"]`);
      group = {
        version, el,
        tbody: el.querySelector('tbody'),
        noteEl: el.querySelector('.evidence-group-note'),
        metaEl: el.querySelector('.evidence-group-meta'),
        offset: 0, loaded: 0, loading: false, loadError: false, opened: false,
        totalEligible: (versionsObj[version] || {}).episode_count || 0,
      };
      group.exhausted = group.totalEligible === 0;
      updateGroupNote(group);
      el.addEventListener('toggle', () => {
        if (el.open && !group.opened) {
          group.opened = true;
          void loadGroupPage(group);
        }
      });
      evidenceGroups.set(version, group);
    } else {
      group.totalEligible = (versionsObj[version] || {}).episode_count || 0;
      group.metaEl.innerHTML = groupMetaMarkup(version, versionsObj);
      if (group.loaded >= group.totalEligible) group.exhausted = true;
      updateGroupNote(group);
    }
    if (prevEl) prevEl.after(group.el); else container.prepend(group.el);
    prevEl = group.el;
  });

  const totalEligible = orderedVersions.reduce((n, v) => n + ((versionsObj[v] || {}).episode_count || 0), 0);
  document.getElementById('evidence-note').textContent =
    `${totalEligible} eligible episode(s) across ${orderedVersions.length} selected polic${orderedVersions.length === 1 ? 'y' : 'ies'} — expand a version below to view its episodes.`;
}

function renderViews(stats) {
  renderHeader(stats);
  const snap = stats.snapshot;

  const status = document.getElementById('status-line');
  const versionCount = Object.keys(snap.versions).length;
  const parts = [];
  if (stats.source_mode === 'live' && snap.seed_complete === false) {
    parts.push('Loading episodes from MinIO…');
  } else if (snap.episode_count) {
    parts.push(`${snap.episode_count} episode(s) loaded across ${versionCount} version(s)`);
  }
  if (stats.source_mode === 'live') {
    parts.push(snap.rejected_last_checked
      ? `Rejected records last checked ${new Date(snap.rejected_last_checked * 1000).toLocaleTimeString()}`
      : 'Rejected records not checked yet');
  }
  status.textContent = parts.join(' · ');

  const allSorted = sortedVersions(snap.versions);
  document.getElementById('empty-state').style.display = allSorted.length === 0 ? 'block' : 'none';
  renderPicker('version-picker', allSorted, snap.versions, selection);
  const shown = activeSelected(selection);
  renderCards('version-cards', snap.versions, shown);
  renderLearningCurve(snap.versions);
  renderCubesTable('cubes-table', snap.versions, shown);
  renderSmoothnessChart('smoothness-chart', snap, shown);
  renderIntegrity(snap);
  document.getElementById('footer-counts').textContent = `${snap.episode_count} records`;
}

async function render() {
  const generation = ++renderGeneration;
  try {
    const stats = await fetchStats();
    if (generation !== renderGeneration) return;
    lastStats = stats;
    renderViews(stats);
    renderEvidenceGroups(stats.snapshot.versions);
  } catch (err) {
    if (generation !== renderGeneration) return;
    document.getElementById('status-line').textContent =
      'Cannot reach dashboard API — container may still be starting after ./run.sh live. Retrying…';
    console.error('dashboard render failed', err);
  }
}

render();
setInterval(render, REFRESH_MS);
