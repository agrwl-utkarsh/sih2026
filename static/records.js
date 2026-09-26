/* ============================================================
   Record explorer — the second page.

   The ingest console renders one row per record; this page is
   where the normalized JSON lives, so a 1,000-line run no longer
   has to build a detail card for every line. It reads the run the
   console captured (ULP.Store) and shows:

     · the record list, grown 200 rows at a time as you scroll
     · the selected record's full JSON in one detail panel
     · search + mode filters across the whole run, not just the page
   ============================================================ */
(() => {
  'use strict';

  const { esc, num, highlightJSON, MODES, modeClass, recordNotes, gateRows, fieldsOf, Store } = window.ULP;
  const $ = (id) => document.getElementById(id);

  const PAGE = 200;          // rows the list grows by as you scroll

  /** Plain words for the list rows — "quarantined" is too wide for the pane. */
  const SHORT_MODE = { Cached: 'cached', Discovery: 'discovery', Quarantined: 'held', Error: 'error' };

  /** Severities worth flagging inline; the rest stay in the detail pane. */
  const LOUD_SEV = new Set(['warn', 'warning', 'error', 'err', 'critical', 'crit',
                            'fatal', 'alert', 'emerg', 'emergency']);

  const els = {
    download: $('download-run'),
    meta: {
      total: $('meta-total'), cached: $('meta-cached'),
      discovery: $('meta-discovery'), at: $('meta-at')
    },
    search: $('search'),
    filters: $('mode-filters'),
    list: $('rec-list'),
    pageHint: $('page-hint'),
    detail: $('detail')
  };

  const state = {
    run: null,
    hay: null,          // lowercased per-record haystack, built on first search
    query: '',
    mode: 'All',
    page: 0,
    entries: [],        // filtered [{ r, abs }]
    sel: 0             // absolute index into run.records
  };

  const absLabel = (i) => `#${num(i + 1)}`;
  const stamp = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

  /* ── run loading ─────────────────────────────────────── */

  const loadRun = (id) => {
    state.run = Store.getRun(id);
    state.hay = null;
    state.query = '';
    state.mode = 'All';
    els.search.value = '';
    if (!state.run) { renderEmpty(); return; }
    state.sel = 0;
    state.page = 0;
    applyFilter({ keepSelection: false });
  };

  const renderRunMeta = () => {
    const { run } = state;
    if (!run) return;
    const c = run.counts || {};
    const modes = c.modes || {};
    els.meta.total.textContent = num(c.total ?? run.records.length);
    els.meta.cached.textContent = num(modes.Cached ?? 0);
    els.meta.discovery.textContent = num(modes.Discovery ?? 0);
    els.meta.at.textContent = stamp(run.at);
    document.title = `${num(c.total ?? run.records.length)} records · Record Explorer`;
  };

  /* ── filtering ───────────────────────────────────────── */

  const haystack = (i) => {
    if (!state.hay) state.hay = state.run.records.map((r) => JSON.stringify(r).toLowerCase());
    return state.hay[i];
  };

  const matches = (r, i) => {
    if (state.mode !== 'All' && (r.mode || 'unknown') !== state.mode) return false;
    if (!state.query) return true;
    return haystack(i).includes(state.query);
  };

  const applyFilter = ({ keepSelection = true, resetPage = true } = {}) => {
    if (!state.run) return;
    state.entries = [];
    state.run.records.forEach((r, i) => { if (matches(r, i)) state.entries.push({ r, abs: i }); });
    if (resetPage) state.page = 0;
    if (!keepSelection || !state.entries.some((e) => e.abs === state.sel)) {
      state.sel = state.entries.length ? state.entries[0].abs : 0;
    }
    clampPage();
    renderFilters();
    renderList();
    renderDetail();
  };

  /* ── list ────────────────────────────────────────────── */

  const pageCount = () => Math.max(1, Math.ceil(state.entries.length / PAGE));
  const clampPage = () => { state.page = Math.min(Math.max(0, state.page), pageCount() - 1); };

  const renderFilters = () => {
    const counts = state.run?.counts?.modes || {};
    const options = ['All', ...MODES.filter((m) => counts[m])];
    els.filters.innerHTML = options.map((m) => {
      const n = m === 'All' ? (state.run?.records.length ?? 0) : counts[m];
      return `<button class="chip ${state.mode === m ? 'is-active' : ''}" data-mode="${esc(m)}">` +
             `${esc(m === 'All' ? 'all' : m.toLowerCase())} <span class="chip-count">${num(n)}</span></button>`;
    }).join('');
  };

  /**
   * One list row, single line: mode · index · message, plus the only two
   * meta bits worth scanning for — a loud severity and the clock time.
   * Family, latency and the full timestamp live in the detail pane.
   */
  const rowHTML = ({ r, abs }) => {
    const norm = r.normalized || {};
    const msg = norm.message || norm.raw || r.error || '—';
    const mode = String(r.mode || '?');
    const on = abs === state.sel;

    const ts = String(norm.timestamp || '');
    const clock = ts.includes('T') ? ts.split('T')[1].replace('Z', '').replace(/\.\d+$/, '') : '';
    const sev = String(norm.severity || '').toLowerCase();

    return `
      <div class="rl-item ${on ? 'is-selected' : ''}" data-abs="${abs}" role="option"
           aria-selected="${on}" tabindex="-1">
        <span class="mode-tag ${modeClass(mode)}">${esc(SHORT_MODE[mode] || mode.toLowerCase())}</span>
        <span class="rl-index">${esc(absLabel(abs))}</span>
        <span class="rl-msg" title="${esc(msg)}">${esc(msg)}</span>
        ${LOUD_SEV.has(sev) ? `<span class="rl-sev ${/^(err|crit|fatal)/.test(sev) ? 'is-err' : 'is-warn'}">${esc(sev)}</span>` : ''}
        ${clock ? `<span class="rl-when" title="${esc(ts)}">${esc(clock)}</span>` : ''}
      </div>`;
  };

  /** Only speaks up while more rows are waiting further down the scroll. */
  const updateListHint = () => {
    const total = state.entries.length;
    const shown = Math.min(total, (state.page + 1) * PAGE);
    els.pageHint.textContent = !total ? 'no matches'
      : shown < total ? `${num(shown)} of ${num(total)} · scroll for more`
      : '';
  };

  const renderList = () => {
    const slice = state.entries.slice(0, (state.page + 1) * PAGE);
    updateListHint();

    if (!slice.length) {
      els.list.innerHTML = `<div class="list-empty">${state.run && state.run.records.length
        ? 'nothing matches this filter — clear the search or pick another mode'
        : 'this run has no records'}</div>`;
      return;
    }

    els.list.innerHTML = slice.map(rowHTML).join('');
  };

  /** The pager buttons are gone: hitting the bottom grows the list a page. */
  const appendPage = () => {
    const slice = state.entries.slice(state.page * PAGE, (state.page + 1) * PAGE);
    if (!slice.length) return;
    els.list.insertAdjacentHTML('beforeend', slice.map(rowHTML).join(''));
    updateListHint();
  };

  /* ── detail ──────────────────────────────────────────── */

  const renderDetail = () => {
    if (!state.run || !state.entries.length) { renderEmptyDetail(); return; }
    const r = state.run.records[state.sel] || state.entries[0].r;
    const norm = r.normalized || {};
    const notes = recordNotes(r);
    const fields = fieldsOf(r);
    const gate = gateRows(r);

    const pipeline = [
      ['processing mode', r.mode ?? '—'],
      ['inferred by', r.inferred_by ?? '—'],
      ['format', r.format ?? '—'],
      ['family', r.family ?? '—'],
      ['latency', `${r.latency_ms ?? '—'} ms`],
      ['drain3 cluster', r.cluster_id ?? '—'],
      ...gate,
      ...(r.quarantine ? [['held for review', `${r.quarantine.count ?? '?'} of ${r.quarantine.graduate_after ?? '?'} sightings`]] : []),
      ...(r.llm_error ? [['note', r.llm_error]] : []),
      ...(r.error ? [['error', r.error]] : [])
    ];

    const rowsHTML = (rows) => `<table class="table kv-table"><tbody>${rows.map(([k, v]) =>
      `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join('')}</tbody></table>`;

    els.detail.innerHTML = `
      <div class="detail-head">
        <span class="mode-tag ${modeClass(r.mode)}">${esc(String(r.mode || 'unknown').toLowerCase())}</span>
        <span class="detail-index">${esc(absLabel(state.sel))} of ${num(state.run.records.length)}</span>
      </div>
      ${notes.map((n) => `<div class="rec-note ${n.kind === 'hold' ? 'is-gate' : ''}">${esc(n.text)}</div>`).join('')}
      ${state.run.trimmed && !norm.raw ? '<div class="rec-note">raw line omitted for this run (browser storage limit)</div>' : ''}
      <div class="detail-section">
        <h4>normalized · common schema</h4>
        <pre class="json" id="detail-json">${highlightJSON(norm)}</pre>
      </div>
      <div class="detail-section">
        <h4>extracted fields</h4>
        ${fields.length ? rowsHTML(fields) : '<p class="dim">no fields extracted</p>'}
      </div>
      <div class="detail-section">
        <h4>raw line</h4>
        <pre class="raw">${esc(norm.raw || '—')}</pre>
      </div>
      <div class="detail-section">
        <h4>pipeline detail</h4>
        ${rowsHTML(pipeline)}
      </div>
      ${r.template ? `<div class="detail-section">
        <h4>drain3 template</h4>
        <pre class="raw">${esc(r.template)}</pre>
      </div>` : ''}`;
  };

  const renderEmptyDetail = () => {
    els.detail.innerHTML = `
      <div class="detail-empty">
        <span class="se-mark">▤</span>
        <p>no record selected</p>
        <small>pick a row on the left</small>
      </div>`;
  };

  const renderEmpty = () => {
    els.list.innerHTML = `<div class="list-empty">no ingest run captured yet — run the console's
      <b>run ingest</b> button and the records land here.</div>`;
    els.detail.innerHTML = `
      <div class="detail-empty">
        <span class="se-mark">▤</span>
        <p>nothing to explore</p>
        <small>the console keeps the last ${num(3)} runs in this browser</small>
        <p><a class="btn btn-mini" href="/">← back to the console</a></p>
      </div>`;
    els.pageHint.textContent = Store.available ? '' : 'browser storage unavailable';
    ['total', 'cached', 'discovery', 'at'].forEach((k) => { els.meta[k].textContent = '—'; });
    els.download.disabled = true;
  };

  /* ── selection & navigation ──────────────────────────── */

  const select = (abs, { scroll = true } = {}) => {
    if (!state.run) return;
    const max = state.run.records.length - 1;
    state.sel = Math.min(Math.max(0, abs), max);
    const pos = state.entries.findIndex((e) => e.abs === state.sel);
    if (pos >= 0) {
      const page = Math.floor(pos / PAGE);
      if (page > state.page) { state.page = page; renderList(); }   // rows already rendered stay put
      else { markSelected(); }
    }
    renderDetail();
    if (scroll) {
      const row = els.list.querySelector('.rl-item.is-selected');
      if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
    }
  };

  const markSelected = () => {
    els.list.querySelectorAll('.rl-item').forEach((el) => {
      const on = Number(el.dataset.abs) === state.sel;
      el.classList.toggle('is-selected', on);
      el.setAttribute('aria-selected', String(on));
    });
  };

  const step = (delta) => {
    if (!state.entries.length) return;
    const pos = state.entries.findIndex((e) => e.abs === state.sel);
    const next = state.entries[Math.min(Math.max(0, pos + delta), state.entries.length - 1)];
    if (next) select(next.abs);
  };

  /* ── events ──────────────────────────────────────────── */

  els.list.addEventListener('click', (e) => {
    const item = e.target.closest('.rl-item');
    if (item) select(Number(item.dataset.abs), { scroll: false });
  });

  els.list.addEventListener('scroll', () => {
    if (state.page >= pageCount() - 1) return;
    const { scrollTop, clientHeight, scrollHeight } = els.list;
    if (scrollTop + clientHeight >= scrollHeight - 240) { state.page += 1; appendPage(); }
  }, { passive: true });

  els.filters.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    state.mode = chip.dataset.mode;
    applyFilter({ keepSelection: true });
  });

  let searchTimer = null;
  els.search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = els.search.value.trim().toLowerCase();
      applyFilter({ keepSelection: true });
    }, 120);
  });

  els.download.addEventListener('click', () => {
    if (!state.run) return;
    const body = state.run.records.map((r) => JSON.stringify(r)).join('\n');
    const url = URL.createObjectURL(new Blob([body], { type: 'application/x-ndjson' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${state.run.id}.jsonl`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

  document.addEventListener('keydown', (e) => {
    const typing = e.target === els.search || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); els.search.focus(); els.search.select(); return; }
    if (e.key === 'Escape' && e.target === els.search) {
      els.search.value = '';
      state.query = '';
      applyFilter({ keepSelection: true });
      els.search.blur();
      return;
    }
    if (typing) return;
    if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); step(1); }
    if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); step(-1); }
    if (e.key === 'PageDown') { e.preventDefault(); step(PAGE); }
    if (e.key === 'PageUp') { e.preventDefault(); step(-PAGE); }
  });

  /* ── boot ────────────────────────────────────────────── */

  if (!Store.available) {
    renderEmpty();
    return;
  }

  const params = new URLSearchParams(location.search);
  loadRun(params.get('run'));   // ?run=<id>, else the newest captured run
  if (!state.run) return;
  renderRunMeta();

  const wanted = Number(params.get('i'));
  if (Number.isFinite(wanted) && wanted > 0 && state.run) select(wanted - 1, { scroll: false });
  else renderList();
})();
