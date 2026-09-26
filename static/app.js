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
  const { esc, clip, num, highlightJSON, modeClass, Store } = window.ULP;

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

    /** Keep only the newest result groups expanded; older runs collapse to one line. */
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
        ? `<a class="btn btn-mini" href="${esc(explorerHref(run))}">Explore full records <span aria-hidden="true">↗</span></a>`
        : '';
      overview.innerHTML = `
        <div class="overview-top">
          <div>
            <div class="overview-eyebrow">INGEST COMPLETE · RUN SUMMARY</div>
            <h3>${esc(status)}</h3>
            <p>${num(records.length)} log ${records.length === 1 ? 'entry was' : 'entries were'} translated into a consistent format.</p>
          </div>
          <div class="overview-actions">${explorer}<span class="overview-time">${wallMs == null ? '' : `${Number(wallMs).toFixed(0)} ms total`}</span></div>
        </div>
        <div class="overview-stats" aria-label="Run summary">
          <div class="overview-stat"><span class="stat-dot dot-total"></span><b>${num(records.length)}</b><span>records</span></div>
          <div class="overview-stat"><span class="stat-dot dot-cached"></span><b>${num(known)}</b><span>recognized</span></div>
          <div class="overview-stat"><span class="stat-dot dot-discovery"></span><b>${num(discovered)}</b><span>new formats learned</span></div>
          <div class="overview-stat"><span class="stat-dot dot-issues"></span><b>${num(issues)}</b><span>need attention</span></div>
          <div class="overview-stat avg-stat"><b>${esc(avg)}<small>ms</small></b><span>avg per record</span></div>
        </div>
        <div class="mode-explainer">
          <span><i class="legend-known"></i><b>Recognized</b> · a saved parsing rule was reused</span>
          <span><i class="legend-new"></i><b>Learned</b> · a rule was created for a new format</span>
          ${issues ? '<span><i class="legend-issue"></i><b>Attention</b> · held or failed; open details to inspect</span>' : ''}
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
        const message = norm.message || norm.raw || r.error || 'No message content';
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
            <div class="result-card-top"><span class="mode-tag ${cls}">${esc(details[0])}</span>${severity ? `<span class="severity-pill sev-${esc(severity.toLowerCase())}">${esc(severity)}</span>` : ''}<span class="result-format">${esc(r.family || r.format || 'log record')}</span><span class="result-latency">${esc(r.latency_ms ?? '—')} ms</span></div>
            <p class="result-message" title="${esc(message)}">${esc(clip(message, 260))}</p>
            ${meta ? `<div class="result-meta">${meta}</div>` : ''}${fields}
            <p class="result-why">${esc(details[1])}</p>
          </div>
          ${href ? '<span class="result-open" aria-hidden="true">Details <b>↗</b></span>' : ''}
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

        group.appendChild(renderSummary(records, run, wall));

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
