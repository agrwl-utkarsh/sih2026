/* ============================================================
   Shared front-end toolkit for the console (app.js) and the
   record explorer (records.js): escaping, JSON highlighting,
   record notes, and the cross-page run store.

   The run store is what lets the explorer be a *second page*:
   the console writes the last few ingest runs into localStorage
   and the explorer reads them by id (sessionStorage alone is not
   dependable across tabs).
   ============================================================ */
window.ULP = (() => {
  'use strict';

  /* ── helpers ─────────────────────────────────────────── */

  /** For attribute contexts — escapes quotes as well. */
  const esc = (v) => String(v ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  /** For element content. Quotes stay literal so the JSON tokeniser can see them. */
  const escText = (v) => String(v ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const clip = (s, n = 200) => {
    const str = String(s ?? '');
    return str.length > n ? `${str.slice(0, n)}…` : str;
  };

  const num = (n) => Number(n || 0).toLocaleString('en-US');

  /** Escapes markup-sensitive chars, then colourises JSON tokens. */
  const highlightJSON = (value) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    return escText(text).replace(
      /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false)\b|\bnull\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      (match) => {
        let cls = 'j-num';
        if (match.startsWith('"')) cls = /:\s*$/.test(match) ? 'j-key' : 'j-str';
        else if (match === 'true' || match === 'false') cls = 'j-bool';
        else if (match === 'null') cls = 'j-null';
        return `<span class="${cls}">${match}</span>`;
      }
    );
  };

  const MODE_CLASS = {
    Cached: 'cached',
    Discovery: 'discovery',
    Quarantined: 'quarantined',
    Error: 'error'
  };
  const MODES = ['Cached', 'Discovery', 'Quarantined', 'Error'];
  const modeClass = (mode) => MODE_CLASS[mode] || 'other';

  /**
   * Plain-language notes for one processed record. No jargon: the gate's
   * internal shorthand (novel/distance/family guess) stays out of the
   * record cards — the explorer surfaces it as labelled detail rows.
   */
  const recordNotes = (r) => {
    const notes = [];
    if (r.quarantine) {
      const q = r.quarantine;
      notes.push({
        kind: 'hold',
        text: `held for review — ${q.count ?? '?'} of ${q.graduate_after ?? '?'} sightings seen; ` +
              'one discovery call then covers every line of this pattern'
      });
    } else if (r.llm_error) {
      notes.push({ kind: 'info', text: r.llm_error });
    }
    return notes;
  };

  /** Labelled rows for the explorer's "pipeline detail" section. */
  const gateRows = (r) => {
    const g = r.gate;
    if (!g) return [];
    const rows = [
      ['family verdict', g.novel ? 'novel format (held for review)' : 'known format'],
      [g.novel ? 'closest known family' : 'matched family', g.family_guess ?? '—']
    ];
    if (g.distance != null) {
      rows.push(['novelty distance', g.threshold != null ? `${g.distance} (cutoff ${g.threshold})` : String(g.distance)]);
    }
    return rows;
  };

  const fieldsOf = (r) => {
    const norm = r.normalized || {};
    const merged = { ...(r.extracted_fields || {}), ...(norm.extra || {}) };
    return Object.entries(merged)
      .filter(([k, v]) => k !== 'raw_message' && v != null && v !== '')
      .map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]);
  };

  /* ── run store ───────────────────────────────────────── */

  const STORE_KEY = 'ulp.runs.v1';
  const MAX_RUNS = 3;
  const MAX_BYTES = 3_500_000;

  const safeStorage = (() => {
    for (const kind of ['localStorage', 'sessionStorage']) {
      try {
        const s = window[kind];
        const probe = '__ulp_probe__';
        s.setItem(probe, '1');
        s.removeItem(probe);
        return s;
      } catch { /* blocked or unavailable — try the next one */ }
    }
    return null;
  })();

  const readRuns = () => {
    if (!safeStorage) return [];
    try {
      const parsed = JSON.parse(safeStorage.getItem(STORE_KEY) || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const writeRuns = (runs) => {
    if (!safeStorage) return false;
    try {
      safeStorage.setItem(STORE_KEY, JSON.stringify(runs));
      return true;
    } catch { /* quota — caller retries with a slimmer payload */
      return false;
    }
  };

  /** Normalized shape used by the explorer's meta strip and filters. */
  const summarize = (records) => {
    const counts = {};
    const formats = {};
    const families = {};
    let latSum = 0;
    records.forEach((r) => {
      counts[r.mode || 'unknown'] = (counts[r.mode || 'unknown'] || 0) + 1;
      if (r.format) formats[r.format] = (formats[r.format] || 0) + 1;
      if (r.family) families[r.family] = (families[r.family] || 0) + 1;
      latSum += Number(r.latency_ms) || 0;
    });
    const top = (obj, n = 5) => Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, n)
      .map(([name, count]) => ({ name, count }));
    return {
      total: records.length,
      modes: counts,
      formats: top(formats),
      families: top(families),
      avg_latency_ms: records.length ? Math.round((latSum / records.length) * 100) / 100 : 0
    };
  };

  /** Full payload minus the raw line — used only when the quota is hit. */
  const slim = (r) => {
    const { raw, ...rest } = r.normalized || {};
    return { ...r, normalized: rest };
  };

  const saveRun = ({ records, lines, wallMs, label }) => {
    const runs = readRuns();
    const run = {
      id: `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      at: new Date().toISOString(),
      label: label || '',
      lines: lines?.length ?? records.length,
      wall_ms: Math.round(wallMs || 0),
      trimmed: false,
      counts: summarize(records),
      records
    };

    let next = [run, ...runs].slice(0, MAX_RUNS);
    while (next.length > 1 && JSON.stringify(next).length > MAX_BYTES) next.pop();

    if (writeRuns(next)) return run;

    // Last resort: keep only the newest run, and drop raw lines from it.
    const fallback = { ...run, trimmed: true, records: run.records.map(slim) };
    return writeRuns([fallback]) ? fallback : null;
  };

  const listRuns = () => readRuns().map(({ records, ...meta }) => ({ ...meta, kept: records?.length ?? 0 }));
  const getRun = (id) => {
    const runs = readRuns();
    return (id && runs.find((r) => r.id === id)) || runs[0] || null;
  };
  const latestRun = () => readRuns()[0] || null;
  const clearRuns = () => { try { safeStorage?.removeItem(STORE_KEY); } catch { /* ignore */ } };

  return {
    esc, escText, clip, num, highlightJSON,
    MODE_CLASS, MODES, modeClass, recordNotes, gateRows, fieldsOf,
    Store: { saveRun, listRuns, getRun, latestRun, clearRuns, available: !!safeStorage }
  };
})();
