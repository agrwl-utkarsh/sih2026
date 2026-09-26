/* ============================================================
   Universal Log Pre-processing Framework · frontend controller
   Preserves: ingest, sample fixtures, cache reset, inspector.
   ============================================================ */

(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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
  const { esc, clip, num, highlightJSON, modeClass, recordNotes, Store } = window.ULP;

  document.addEventListener('DOMContentLoaded', () => {

    /* ── element map ───────────────────────────────────── */
    const els = {
      sample: $('sample-select'),
      input: $('log-input'),
      gutter: $('gutter'),
      run: $('process-btn'),
      runLabel: $('process-label'),
      clear: $('clear-btn'),
      clearStream: $('clear-stream-btn'),
      refreshInspector: $('refresh-inspector-btn'),
      clearCache: $('clear-cache-btn'),
      stream: $('results-container'),
      hint: $('results-hint'),
      slMode: $('sl-mode'),
      slCount: $('sl-count'),
      // telemetry
      total: $('stat-total'),
      cached: $('stat-cached'),
      disc: $('stat-discovery'),
      fams: $('stat-families'),
      lat: $('stat-latency'),
      saved: $('stat-saved'),
      lastrun: $('stat-lastrun'),
      // inspector
      familyOut: $('family-output'),
      cacheOut: $('cache-output'),
      healthOut: $('health-output'),
      tierStats: $('tier-stats'),
      templatesBody: $('templates-body'),
      quarantineOut: $('quarantine-output'),
      gateStats: $('gate-stats'),
      counts: {
        family: $('count-family'),
        fingerprint: $('count-fingerprint'),
        templates: $('count-templates'),
        quarantine: $('count-quarantine')
      }
    };

    const totals = { total: 0, cached: 0, disc: 0, latSum: 0 };
    let runCount = 0;

    /** Above this many records per batch the console shows the table only. */
    const CARD_LIMIT = 25;

    /** Full tables kept in the console; older batches collapse to one line. */
    const RUN_GROUPS = 3;

    /* ── telemetry ─────────────────────────────────────── */
    const paintTelemetry = () => {
      els.total.textContent = num(totals.total);
      els.cached.textContent = num(totals.cached);
      els.disc.textContent = num(totals.disc);
      els.lat.textContent = totals.total ? `${(totals.latSum / totals.total).toFixed(1)}ms` : '—';
      els.saved.textContent = totals.total ? `${Math.round((totals.cached / totals.total) * 100)}%` : '0%';
    };

    const resetTotals = () => {
      totals.total = totals.cached = totals.disc = totals.latSum = 0;
      els.lastrun.textContent = '—';
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
      const last = Store.latestRun();
      els.stream.innerHTML = `
        <div class="stream-empty">
          <span class="se-mark">▤</span>
          <p>no records yet</p>
          <small>run a fixture — first sighting is <b>discovery</b>, repeats are <b>cached</b></small>
          ${last ? `<p class="se-last"><a class="btn btn-mini" href="${esc(explorerHref(last))}">open last run · ${num(last.counts?.total ?? last.records.length)} records →</a></p>` : ''}
        </div>`;
    };

    /** Build one parsed-output record row. */
    const renderRecord = (r) => {
      const cls = modeClass(r.mode);
      const badge = r.mode === 'Discovery'
        ? `discovery·${r.inferred_by === 'llm' ? 'llm' : 'heur'}`
        : esc(String(r.mode || 'unknown')).toLowerCase();

      const norm = r.normalized || {};
      const preview = norm.message || norm.raw || r.error || '';

      const row = document.createElement('div');
      row.className = `record m-${cls}`;

      const notes = recordNotes(r).map((n) =>
        `<div class="rec-note${n.kind === 'hold' ? ' is-gate' : ''}">${esc(n.text)}</div>`);

      row.innerHTML = `
        <div class="rec-head" role="button" tabindex="0" aria-expanded="false">
          <span class="mode-tag ${cls}">${badge}</span>
          <span class="rec-kv"><b>fmt</b><span title="${esc(r.format || '')}">${esc(clip(r.format || 'unknown', 34))}</span></span>
          <span class="rec-kv"><b>fam</b><span>${esc(r.family || 'generic')}</span></span>
          <span class="rec-kv"><b>by</b><span>${esc(r.inferred_by || '—')}</span></span>
          <span class="rec-kv"><b>lat</b><span class="v-lat">${esc(r.latency_ms ?? '—')}ms</span></span>
          ${r.template ? `<span class="rec-kv"><b>tpl</b><span title="cluster #${esc(r.cluster_id ?? '')}">#${esc(r.cluster_id ?? '?')}</span></span>` : ''}
          <span class="rec-spacer"></span>
          <span class="rec-caret">▶</span>
        </div>
        ${preview ? `<div class="rec-msg" title="${esc(clip(preview, 300))}">${esc(clip(preview, 220))}</div>` : ''}
        ${notes.join('')}
        <div class="rec-body">
          <div class="rec-section">
            <h4>extracted fields</h4>
            <table class="table"><tbody class="rec-fields"></tbody></table>
          </div>
          <div class="rec-section">
            <h4>normalized · common schema <button class="btn btn-mini rec-toggle">toggle</button></h4>
            <pre class="json rec-json"></pre>
          </div>
        </div>`;

      /* fields table */
      const tbody = row.querySelector('.rec-fields');
      if (r.mode === 'Error' && r.error) {
        tbody.innerHTML = `<tr><td class="k">error</td><td class="v">${esc(r.error)}</td></tr>`;
      } else {
        const merged = { ...(r.extracted_fields || {}), ...(norm.extra || {}) };
        const entries = Object.entries(merged).filter(([k, v]) => k !== 'raw_message' && v != null && v !== '');
        tbody.innerHTML = entries.length
          ? entries.map(([k, v]) =>
              `<tr><td class="k">${esc(k)}</td><td class="v">${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('')
          : `<tr><td colspan="2" class="dim">no fields extracted</td></tr>`;
      }

      /* normalized payload */
      row.querySelector('.rec-json').innerHTML = highlightJSON(norm);

      /* interactions */
      const head = row.querySelector('.rec-head');
      const toggle = () => {
        const open = row.classList.toggle('is-open');
        head.setAttribute('aria-expanded', String(open));
      };
      head.addEventListener('click', toggle);
      head.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
      row.querySelector('.rec-toggle').addEventListener('click', (e) => {
        e.stopPropagation();
        row.querySelector('.rec-json').classList.toggle('is-hidden');
      });

      return row;
    };

    /**
     * One row per record, which stays readable at any batch size. Each row
     * links into the explorer for that record's full normalized JSON — the
     * console deliberately no longer builds a detail card per line (at 1,000
     * lines those cards were ~56k DOM nodes on their own).
     */
    const renderSummary = (records, run) => {
      const wrap = document.createElement('div');
      wrap.className = 'table-wrap output-table-wrap';
      wrap.innerHTML = `
        <table class="table output-table" aria-label="Parsed output table">
          <thead><tr><th class="num">#</th><th>mode</th><th>format</th><th>timestamp</th><th>severity</th><th>source</th><th>message</th><th class="num">lat</th></tr></thead>
          <tbody>${records.map((r, i) => {
            const norm = r.normalized || {};
            const mode = String(r.mode || 'unknown');
            const cls = modeClass(mode);
            const href = run ? explorerHref(run, i) : null;
            // One anchor per row (the index cell) keeps keyboard access without
            // paying for a link element in every one of the eight cells.
            const idx = href
              ? `<a class="row-link" href="${esc(href)}" title="Open this record's normalized JSON in the explorer">${i + 1}</a>`
              : String(i + 1);
            return `<tr data-i="${i}"${href ? ` title="Open record #${i + 1} in the explorer"` : ''}>
              <td class="num">${idx}</td>
              <td><span class="mode-tag ${cls}">${esc(mode)}</span></td>
              <td>${esc(r.format || '—')}</td>
              <td>${esc(norm.timestamp || '—')}</td>
              <td>${esc(norm.severity || '—')}</td>
              <td>${esc(norm.source || '—')}</td>
              <td class="output-message" title="${esc(clip(norm.message || norm.raw || r.error || '', 300))}">${esc(clip(norm.message || norm.raw || r.error || '—', 200))}</td>
              <td class="num">${esc(r.latency_ms ?? '—')}</td>
            </tr>`;
          }).join('')}</tbody>
        </table>`;

      if (run) {
        // Whole-row click opens that record; the index anchor keeps keyboard
        // access, and a live text selection (someone copying table cells) wins
        // over navigation.
        wrap.addEventListener('click', (e) => {
          const row = e.target.closest('tbody tr[data-i]');
          if (!row || e.target.closest('a')) return;
          if (String(window.getSelection?.() ?? '').trim()) return;
          window.location.assign(explorerHref(run, Number(row.dataset.i)));
        });
      }
      return wrap;
    };

    /** Call-to-action strip: the console shows the table, the explorer shows JSON. */
    const renderRunActions = (records, run) => {
      const el = document.createElement('div');
      el.className = 'run-actions';
      el.innerHTML = `
        <a class="btn btn-primary" href="${esc(explorerHref(run))}">
          <span class="btn-key">▤</span>open record explorer
        </a>
        <span class="run-actions-hint">
          normalized JSON for all ${num(records.length)} records — searchable, one page at a time
        </span>`;
      return el;
    };

    /** Small batches keep the per-record cards: they are the nicer read at that size. */
    const renderCards = (records) => {
      const frag = document.createDocumentFragment();
      records.forEach((r, i) => {
        const row = renderRecord(r);
        if (records.length <= 3 && i === 0) {
          row.classList.add('is-open');
          row.querySelector('.rec-head').setAttribute('aria-expanded', 'true');
        }
        frag.appendChild(row);
      });
      return frag;
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
        group.querySelector('.table-wrap')?.remove();
        group.querySelector('.run-actions')?.remove();
        group.querySelector('.stream-note')?.remove();
        group.querySelectorAll('.record').forEach((card) => card.remove());
        const line = document.createElement('div');
        line.className = 'run-collapsed';
        line.innerHTML = `${esc(group.dataset.label || 'earlier run')} · table collapsed to keep this console responsive` +
          (group.dataset.run ? ` — <a href="/records?run=${encodeURIComponent(group.dataset.run)}">open in explorer</a>` : '');
        group.appendChild(line);
      });
    };

    const scrollToBottom = () => { els.stream.scrollTop = els.stream.scrollHeight; };

    /* ── inspector ─────────────────────────────────────── */
    const fetchHealth = async () => {
      const h = await fetchJSON('/api/health');
      if (!h) return;
      const families = h.family_cache?.families_learned ?? 0;
      els.fams.textContent = num(families);
      els.counts.family.textContent = num(families);

      els.healthOut.innerHTML = highlightJSON(h);
    };

    const refreshCache = async () => {
      const d = await fetchJSON('/api/logs/cache');
      if (!d) return;
      const fam = d.family_cache || {};
      const fps = Array.isArray(d.cache) ? d.cache : [];
      els.counts.fingerprint.textContent = num(fps.length);
      els.familyOut.innerHTML = highlightJSON(fam);
      els.cacheOut.innerHTML = highlightJSON(d.cache ?? []);
    };

    const refreshTemplates = async () => {
      const t = await fetchJSON('/api/logs/templates');
      if (!t) return;
      const tpls = t.templates || [];
      els.counts.templates.textContent = num(t.clusters ?? 0);
      els.tierStats.textContent =
        `${num(t.clusters)} clusters · ${num(t.rules_learned)} rules · ${t.rule_backend ?? '—'}` +
        `${t.enforce_mode ? ' · ENFORCE' : ' · shadow'}`;

      els.templatesBody.innerHTML = tpls.length
        ? tpls.map((tpl) => `
            <tr>
              <td title="cluster #${esc(tpl.cluster_id)}">${esc(tpl.template)}</td>
              <td class="num">${num(tpl.size)}</td>
              <td class="${tpl.has_rule ? 'has-rule' : 'no-rule'}">${tpl.has_rule ? 'rule ✓' : '—'}</td>
            </tr>`).join('')
        : `<tr><td colspan="3" class="dim">no templates mined yet</td></tr>`;
    };

    const refreshQuarantine = async () => {
      const q = await fetchJSON('/api/logs/quarantine');
      if (!q) return;
      const items = q.items || [];
      const novelCount = num(q.novel_templates ?? 0);
      els.counts.quarantine.textContent = novelCount;
      els.gateStats.textContent =
        `${novelCount} novel format${Number(q.novel_templates) === 1 ? '' : 's'} · ${q.enforce_mode ? 'enforce' : 'shadow mode'}`;

      els.quarantineOut.classList.toggle('dim', items.length === 0);
      els.quarantineOut.innerHTML = items.length
        ? items.slice(0, 20).map((item) => {
            const g = item.gate || {};
            const seen = Number(item.count) || 0;
            const sightings = `${num(seen)} sighting${seen === 1 ? '' : 's'}`;
            const family = g.family_guess
              ? ` · ${g.novel ? 'closest known family' : 'matched family'}: ${esc(g.family_guess)}`
              : '';
            const evidence = g.distance == null
              ? 'novelty score unavailable'
              : `novelty distance ${esc(g.distance)}${g.threshold == null ? '' : ` · threshold ${esc(g.threshold)}`}`;
            return `
              <div class="q-item">
                <div class="q-head">
                  <span class="q-flag ${g.novel ? 'novel' : 'watched'}" title="${evidence}">${g.novel ? 'novel' : 'known'}</span>
                  <span class="q-meta">${sightings}${family}</span>
                  — <span class="q-tpl">${esc(item.template ?? '')}</span>
                </div>
                <pre class="q-sample">${esc((item.samples || [])[0] || '—')}</pre>
              </div>`;
          }).join('')
        : 'no novel templates recorded';
    };

    const refreshAll = () => {
      fetchHealth();
      refreshCache();
      refreshTemplates();
      refreshQuarantine();
    };

    /* ── inspector tabs ────────────────────────────────── */
    $$('.tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        $$('.tab').forEach((b) => b.classList.toggle('is-active', b === btn));
        $$('.tab-pane').forEach((p) => p.classList.toggle('is-active', p.id === `tab-${btn.dataset.tab}`));
      });
    });

    els.refreshInspector.addEventListener('click', () => {
      els.refreshInspector.disabled = true;
      refreshAll();
      setTimeout(() => { els.refreshInspector.disabled = false; }, 350);
    });

    /* ── sample fixtures ───────────────────────────────── */
    els.sample.addEventListener('change', (e) => {
      if (!e.target.value) return;
      els.input.value = e.target.value;
      syncGutter();
      els.input.focus();
      setMode('loaded');
    });

    /* ── buffer / stream controls ──────────────────────── */
    els.clear.addEventListener('click', () => {
      els.input.value = '';
      els.sample.value = '';
      syncGutter();
      renderEmpty();
      els.hint.textContent = 'awaiting input';
      resetTotals();
      setMode('idle');
      refreshAll();
      els.input.focus();
    });

    els.clearStream.addEventListener('click', () => {
      renderEmpty();
      runCount = 0;
      resetTotals();
      els.hint.textContent = 'awaiting input';
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
        const data = await res.json().catch(() => ({}));
        const c = data.cleared || {};
        refreshAll();
        els.hint.textContent =
          `cache reset — ${num(c.family_cache)} fam, ${num(c.fingerprint_cache)} fp, ` +
          `${num(c.templates)} tpl, ${num(c.quarantine)} quarantined`;
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
        els.hint.textContent = 'awaiting input';
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

        // Hand the whole run to the explorer page before rendering anything.
        const run = Store.saveRun({ records, lines: logs, wallMs: wall });
        if (!run) els.hint.title = 'browser storage full — the explorer will show no run for this batch';

        runCount += 1;
        const label = `run #${runCount} · ${num(records.length)} record${records.length === 1 ? '' : 's'} · ${wall.toFixed(1)}ms`;
        const group = document.createElement('section');
        group.className = 'run-group';
        if (run) group.dataset.run = run.id;
        group.dataset.label = label;

        const divider = document.createElement('div');
        divider.className = 'run-divider';
        divider.innerHTML = `<span>${esc(label)}</span>`;
        group.appendChild(divider);

        if (run) group.appendChild(renderRunActions(records, run));
        group.appendChild(renderSummary(records, run));

        // Per-record cards only below the batch size where they stay readable.
        if (records.length <= CARD_LIMIT) {
          group.appendChild(renderCards(records));
        } else {
          const note = document.createElement('p');
          note.className = 'stream-note';
          note.innerHTML = `detail cards hidden for this ${num(records.length)}-record batch — ` +
            (run ? `open the <a href="${esc(explorerHref(run))}">record explorer</a> for any record's JSON` : 'the explorer is unavailable in this browser');
          group.appendChild(note);
        }

        els.stream.appendChild(group);
        pruneRunGroups();

        records.forEach((r) => {
          totals.total += 1;
          totals.latSum += Number(r.latency_ms) || 0;
          if (r.mode === 'Cached') totals.cached += 1;
          if (r.mode === 'Discovery') totals.disc += 1;
        });
        // Show the new run's table first, not the bottom of its cards.
        els.stream.scrollTop += divider.getBoundingClientRect().top - els.stream.getBoundingClientRect().top;

        els.hint.textContent = `${num(records.length)} record(s) · ${num(totals.cached)} cached · ${num(totals.disc)} discovery`;
        els.lastrun.textContent = `${wall.toFixed(0)}ms`;
        paintTelemetry();
        setMode('done', 'done');
        refreshAll();
      } catch (e) {
        setMode('error', 'error');
        pending.remove();
        const error = document.createElement('div');
        error.className = 'stream-error';
        error.setAttribute('role', 'alert');
        error.textContent = `Ingest failed: ${e.message}`;
        els.stream.appendChild(error);
        els.hint.textContent = 'ingest failed';
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
    renderEmpty();
    syncGutter();
    paintTelemetry();
    refreshAll();
    setMode('idle');
  });
})();
