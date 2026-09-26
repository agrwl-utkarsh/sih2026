/* ============================================================
   Universal Log Pre-processing Framework · frontend controller
   Preserves: ingest, sample fixtures, cache reset, inspector.
   ============================================================ */

(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const fetchJSON = async (url, opts) => {
    try {
      const r = await fetch(url, opts);
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  };

  /* ── shared toolkit ──────────────────────────────────── */
  /* esc / escText / clip / num / highlightJSON / MODE_CLASS / Store live in
     ui.js so the console and the record explorer cannot drift apart. */
  const { esc, num, highlightJSON, modeClass, Store } = window.ULP;

  document.addEventListener('DOMContentLoaded', () => {

    /* ── element map ───────────────────────────────────── */
    const els = {
      sample: $('sample-select'),
      input: $('log-input'),
      gutter: $('gutter'),
      run: $('process-btn'),
      runLabel: $('process-label'),
      clearStream: $('clear-stream-btn'),
      clearCache: $('clear-cache-btn'),
      stream: $('results-container'),
      slMode: $('sl-mode'),
      slCount: $('sl-count'),
      // telemetry
      total: $('stat-total'),
      cached: $('stat-cached'),
      disc: $('stat-discovery'),
      saved: $('stat-saved'),
      // inspector — fingerprint cache only
      cacheOut: $('cache-output')
    };

    const totals = { total: 0, cached: 0, disc: 0 };
    let runCount = 0;

    /** Keep only the newest result groups expanded; older runs collapse to one line. */
    const RUN_GROUPS = 3;

    /* ── telemetry ─────────────────────────────────────── */
    const paintTelemetry = () => {
      els.total.textContent = num(totals.total);
      els.cached.textContent = num(totals.cached);
      els.disc.textContent = num(totals.disc);
      els.saved.textContent = totals.total ? `${Math.round((totals.cached / totals.total) * 100)}%` : '0%';
    };

    const resetTotals = () => {
      totals.total = totals.cached = totals.disc = 0;
      paintTelemetry();
    };

    /* ── editor: gutter + statusline ───────────────────── */
    const syncGutter = () => {
      const lines = els.input.value.split('\n').length;
      const gutter = els.gutter;
      const current = els.input.value.slice(0, els.input.selectionStart).split('\n').length;

      if (gutter.childElementCount !== lines) {
        const html = [];
        for (let i = 1; i <= lines; i++) {
          html.push(`<div class="gutter-line${i === current ? ' is-current' : ''}">${i}</div>`);
        }
        gutter.innerHTML = html.join('');
      } else {
        Array.from(gutter.children).forEach((el, i) => {
          el.classList.toggle('is-current', i + 1 === current);
        });
      }
      gutter.scrollTop = els.input.scrollTop;

      els.slCount.textContent =
        `${num(lines)} line${lines === 1 ? '' : 's'} · ${num(els.input.value.length)} chars · ln ${current}`;
    };

    const setMode = (label, cls = '') => {
      els.slMode.textContent = label;
      els.slMode.className = `sl-mode${cls ? ` is-${cls}` : ''}`;
    };

    els.input.addEventListener('input', syncGutter);
    els.input.addEventListener('scroll', () => { els.gutter.scrollTop = els.input.scrollTop; });
    els.input.addEventListener('click', syncGutter);
    els.input.addEventListener('keyup', syncGutter);

    /* ── stream ────────────────────────────────────────── */
    /** Runs kept in the browser, so the explorer can be opened again later. */
    const explorerHref = (run, index = null) =>
      `/records?run=${encodeURIComponent(run.id)}${index == null ? '' : `&i=${index + 1}`}`;

    const renderEmpty = () => {
      els.stream.innerHTML = `
        <div class="stream-empty">
          <span class="se-mark">▤</span>
          <p>no records yet</p>
        </div>`;
    };

    const renderSummary = (records, run, wallMs = null) => {
      const counts = records.reduce((acc, r) => {
        const key = r.mode || 'Other';
        acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});
      const issues = (counts.Error || 0) + (counts.Quarantined || 0);
      const known = counts.Cached || 0;
      const discovered = counts.Discovery || 0;
      const avg = records.length
        ? (records.reduce((sum, r) => sum + (Number(r.latency_ms) || 0), 0) / records.length).toFixed(1)
        : '0.0';
      const status = issues ? `${num(issues)} need${issues === 1 ? 's' : ''} attention` : 'All records processed';
      const statusClass = issues ? 'has-issues' : 'is-clear';
      const overview = document.createElement('section');
      overview.className = `output-overview ${statusClass}`;
      const explorer = run
        ? `<a class="btn btn-mini" href="${esc(explorerHref(run))}">open full records →</a>`
        : '';
      overview.innerHTML = `
        <div class="overview-top">
          <div>
            <div class="overview-eyebrow">run summary</div>
            <h3>${esc(status)}</h3>
            <p>${num(records.length)} log ${records.length === 1 ? 'entry' : 'entries'} normalized to the common schema.</p>
          </div>
          <div class="overview-actions">${explorer}<span class="overview-time">${wallMs == null ? '' : `${Number(wallMs).toFixed(0)} ms total`}</span></div>
        </div>
        <div class="overview-stats" aria-label="Run summary">
          <div class="overview-stat"><b>${num(records.length)}</b><span>records</span></div>
          <div class="overview-stat"><b>${num(known)}</b><span>recognized</span></div>
          <div class="overview-stat"><b>${num(discovered)}</b><span>new formats</span></div>
          <div class="overview-stat"><b>${num(issues)}</b><span>need attention</span></div>
          <div class="overview-stat"><b>${esc(avg)} ms</b><span>avg per record</span></div>
        </div>
        <div class="mode-explainer">
          <span><b>recognized</b> — reused a saved rule</span>
          <span><b>learned</b> — created a rule for a new format</span>
          ${issues ? '<span><b>attention</b> — held or failed; open details to inspect</span>' : ''}
        </div>`;

      const list = document.createElement('div');
      list.className = 'result-list';
      list.setAttribute('aria-label', 'Parsed log records');
      const cards = records.map((r, i) => {
        const norm = r.normalized || {};
        const mode = String(r.mode || 'Other');
        const cls = modeClass(mode);
        const details = {
          Cached: ['Recognized format', 'A known parsing rule was reused.'],
          Discovery: ['New format learned', `Format identified by ${r.inferred_by === 'llm' ? 'AI discovery' : 'automatic detection'}.`],
          Quarantined: ['Held for review', 'This unfamiliar format is being checked before a rule is learned.'],
          Error: ['Could not parse', 'Review the error details for this record.']
        }[mode] || [mode, 'Record processed.'];
        const time = norm.timestamp ? String(norm.timestamp).replace('T', ' ').replace(/Z$/, ' UTC') : '';
        const severity = norm.severity && norm.severity !== 'unknown' ? String(norm.severity) : '';
        const source = norm.source && norm.source !== 'unknown' ? String(norm.source) : '';
        const href = run ? explorerHref(run, i) : null;
        const extra = Object.entries({ ...(r.extracted_fields || {}), ...(norm.extra || {}) })
          .filter(([k, v]) => !['raw_message', 'message', 'timestamp', 'severity', 'source'].includes(k) && v != null && v !== '')
          .slice(0, 3);
        const meta = [time, source].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join('<span class="meta-sep">·</span>');
        const fields = extra.length ? `<div class="result-fields">${extra.map(([k, v]) => `<span class="field-chip"><b>${esc(k)}</b> ${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</span>`).join('')}</div>` : '';
        return `<article class="result-card m-${cls}" data-i="${i}" ${href ? `tabindex="0" role="link" aria-label="Open details for record ${i + 1}"` : ''}>
          <div class="result-index">${String(i + 1).padStart(2, '0')}</div>
          <div class="result-main">
            <div class="result-card-top"><span class="mode-tag ${cls}">${esc(details[0])}</span>${severity ? `<span class="severity-pill">${esc(severity)}</span>` : ''}<span class="result-latency">${esc(r.latency_ms ?? '—')} ms</span></div>
            ${meta ? `<div class="result-meta">${meta}</div>` : ''}${fields}
            <p class="result-why">${esc(details[1])}</p>
          </div>
          ${href ? '<span class="result-open" aria-hidden="true">details →</span>' : ''}
        </article>`;
      }).join('');
      list.innerHTML = cards || '<p class="dim">No records returned.</p>';
      if (run) {
        list.addEventListener('click', (e) => {
          const card = e.target.closest('.result-card[data-i]');
          if (card && !String(window.getSelection?.() ?? '').trim()) window.location.assign(explorerHref(run, Number(card.dataset.i)));
        });
        list.addEventListener('keydown', (e) => {
          if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.result-card[data-i]')) {
            e.preventDefault(); window.location.assign(explorerHref(run, Number(e.target.dataset.i)));
          }
        });
      }
      const fragment = document.createDocumentFragment();
      fragment.append(overview, list);
      return fragment;
    };

    /**
     * Only the newest few batches keep a full table in the DOM; older ones
     * collapse to a one-line link, so a demo that keeps ingesting does not
     * pile tables up until the page crawls.
     */
    const pruneRunGroups = () => {
      const groups = Array.from(els.stream.querySelectorAll('.run-group'));
      groups.slice(0, Math.max(0, groups.length - RUN_GROUPS)).forEach((group) => {
        if (group.querySelector('.run-collapsed')) return;
        group.querySelector('.output-overview')?.remove();
        group.querySelector('.result-list')?.remove();
        const line = document.createElement('div');
        line.className = 'run-collapsed';
        line.innerHTML = `${esc(group.dataset.label || 'earlier run')} · result details collapsed to keep this console responsive` +
          (group.dataset.run ? ` — <a href="/records?run=${encodeURIComponent(group.dataset.run)}">open in explorer</a>` : '');
        group.appendChild(line);
      });
    };

    const appendRunGroup = (records, run, wallMs, label) => {
      const group = document.createElement('section');
      group.className = 'run-group';
      if (run) group.dataset.run = run.id;
      group.dataset.label = label;

      const divider = document.createElement('div');
      divider.className = 'run-divider';
      divider.innerHTML = `<span>${esc(label)}</span>`;
      group.appendChild(divider);
      group.appendChild(renderSummary(records, run, wallMs));
      els.stream.appendChild(group);
      return divider;
    };

    const restoreStream = () => {
      const runs = Store.getRuns().reverse();
      if (!runs.length) {
        renderEmpty();
        return;
      }

      els.stream.replaceChildren();
      runCount = runs.length;
      runs.forEach((run, index) => {
        const records = Array.isArray(run.records) ? run.records : [];
        const count = records.length;
        const wallMs = Number(run.wall_ms) || 0;
        const label = run.label || `run #${index + 1} · ${num(count)} record${count === 1 ? '' : 's'} · ${wallMs.toFixed(1)}ms`;
        appendRunGroup(records, run, wallMs, label);
        records.forEach((record) => {
          totals.total += 1;
          if (record.mode === 'Cached') totals.cached += 1;
          if (record.mode === 'Discovery') totals.disc += 1;
        });
      });
      pruneRunGroups();
      paintTelemetry();
    };

    const scrollToBottom = () => { els.stream.scrollTop = els.stream.scrollHeight; };

    /* ── inspector: fingerprint cache only ─────────────── */
    const refreshCache = async () => {
      const d = await fetchJSON('/api/logs/cache');
      if (!d) return;
      const fps = Array.isArray(d.cache) ? d.cache : [];
      els.cacheOut.innerHTML = highlightJSON(fps);
    };

    /* ── sample fixtures ───────────────────────────────── */
    els.sample.addEventListener('change', (e) => {
      if (!e.target.value) return;
      els.input.value = e.target.value;
      syncGutter();
      els.input.focus();
      setMode('loaded');
    });

    /* ── stream controls ───────────────────────────────── */
    els.clearStream.addEventListener('click', () => {
      Store.clearRuns();
      renderEmpty();
      runCount = 0;
      resetTotals();
    });

    /* ── cache reset ───────────────────────────────────── */
    els.clearCache.addEventListener('click', async () => {
      if (!confirm('Reset all learned families, fingerprints, templates and quarantine?')) return;
      const btn = els.clearCache;
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="btn-key">…</span>clearing';
      try {
        const res = await fetch('/api/logs/clear', { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        refreshCache();
        setMode('cache reset', 'done');
      } catch (e) {
        alert('Could not clear cache: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = original;
      }
    });

    /* ── ingest ────────────────────────────────────────── */
    const runIngest = async () => {
      const raw = els.input.value.trim();
      if (!raw) {
        els.stream.querySelector('.stream-empty')?.remove();
        const error = document.createElement('div');
        error.className = 'stream-error';
        error.setAttribute('role', 'alert');
        error.textContent = 'Paste logs or load a sample, then click run ingest.';
        els.stream.querySelector('.stream-error')?.remove();
        els.stream.appendChild(error);
        els.input.focus();
        return;
      }
      if (els.run.disabled) return;

      els.run.disabled = true;
      els.runLabel.textContent = 'running…';
      setMode('running', 'running');
      els.stream.querySelector('.stream-empty')?.remove();
      els.stream.querySelectorAll('.stream-error').forEach((error) => error.remove());
      const pending = document.createElement('div');
      pending.className = 'stream-pending';
      pending.setAttribute('role', 'status');
      pending.textContent = 'Processing logs…';
      els.stream.appendChild(pending);
      scrollToBottom();

      const wallStart = performance.now();
      try {
        const logs = raw.split('\n').filter((l) => l.trim());
        const res = await fetch('/api/logs/ingest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ logs })
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || {}));
        }

        const data = await res.json();
        if (!Array.isArray(data.processed_logs) || !data.processed_logs.length) {
          throw new Error('The server returned no parsed records. Check the input and try again.');
        }
        const records = data.processed_logs;
        const wall = performance.now() - wallStart;

        pending.remove();

        // Persist each run so the console can restore it after visiting the explorer.
        runCount += 1;
        const label = `run #${runCount} · ${num(records.length)} record${records.length === 1 ? '' : 's'} · ${wall.toFixed(1)}ms`;
        const run = Store.saveRun({ records, lines: logs, wallMs: wall, label });
        const divider = appendRunGroup(records, run, wall, label);
        pruneRunGroups();

        records.forEach((r) => {
          totals.total += 1;
          if (r.mode === 'Cached') totals.cached += 1;
          if (r.mode === 'Discovery') totals.disc += 1;
        });
        // Show the new run's table first, not the bottom of its cards.
        els.stream.scrollTop += divider.getBoundingClientRect().top - els.stream.getBoundingClientRect().top;

        paintTelemetry();
        setMode('done', 'done');
        refreshCache();
      } catch (e) {
        setMode('error', 'error');
        pending.remove();
        const error = document.createElement('div');
        error.className = 'stream-error';
        error.setAttribute('role', 'alert');
        error.textContent = `Ingest failed: ${e.message}`;
        els.stream.appendChild(error);
        scrollToBottom();
      } finally {
        els.run.disabled = false;
        els.runLabel.textContent = 'run ingest';
      }
    };

    els.run.addEventListener('click', runIngest);

    /* ⌘/ctrl + ⏎ runs the ingest from anywhere in the console */
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        runIngest();
      }
    });

    /* ── boot ──────────────────────────────────────────── */
    restoreStream();
    syncGutter();
    paintTelemetry();
    refreshCache();
    setMode('idle');
  });
})();
