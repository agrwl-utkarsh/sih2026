/* ============================================================
   ulp · operator console — frontend controller
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
      health: $('health-badge'),
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
    const renderEmpty = () => {
      els.stream.innerHTML = `
        <div class="stream-empty">
          <span class="se-mark">▤</span>
          <p>no records yet</p>
          <small>run a fixture — first sighting is <b>discovery</b>, repeats are <b>cached</b></small>
        </div>`;
    };

    /** Build one parsed-output record row. */
    const renderRecord = (r) => {
      const cls = MODE_CLASS[r.mode] || 'other';
      const badge = r.mode === 'Discovery'
        ? `discovery·${r.inferred_by === 'llm' ? 'llm' : 'heur'}`
        : esc(String(r.mode || 'unknown')).toLowerCase();

      const norm = r.normalized || {};
      const preview = norm.message || norm.raw || r.error || '';

      const row = document.createElement('div');
      row.className = `record m-${cls}`;

      const notes = [];
      if (r.llm_error) notes.push(`<div class="rec-note">${esc(r.llm_error)}</div>`);
      if (r.gate) {
        const g = r.gate;
        notes.push(`<div class="rec-note is-gate">gate: ${g.novel ? 'NOVEL' : 'known'} · d=${esc(g.distance ?? '?')} · guess=${esc(g.family_guess ?? '?')}</div>`);
      }
      if (r.quarantine) {
        const q = r.quarantine;
        notes.push(`<div class="rec-note is-gate">quarantine: ${esc(q.count ?? '?')}/${esc(q.graduate_after ?? '?')} seen before graduation</div>`);
      }

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

    const scrollToBottom = () => { els.stream.scrollTop = els.stream.scrollHeight; };

    /* ── inspector ─────────────────────────────────────── */
    const fetchHealth = async () => {
      const h = await fetchJSON('/api/health');
      if (!h) {
        els.health.textContent = 'system offline';
        els.health.className = 'health-badge is-error';
        return;
      }
      const families = h.family_cache?.families_learned ?? 0;
      els.fams.textContent = num(families);
      els.counts.family.textContent = num(families);

      const tt = h.template_tier || {};
      const gate = h.format_gate || {};
      const bits = [];
      if (h.llm_configured && h.provider) bits.push(`${h.provider}/${h.model}`);
      else bits.push('heuristic');
      bits.push(`${families} fam`);
      if (tt.drain3_available === false) bits.push('drain3 off');
      if (tt.enforce_mode) bits.push('enforce');
      if (gate.loaded === false) bits.push('gate off');

      els.health.textContent = bits.join(' · ');
      els.health.className = `health-badge ${h.llm_configured ? 'is-ok' : 'is-warn'}`;
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
      els.counts.quarantine.textContent = num(q.novel_templates ?? 0);
      els.gateStats.textContent =
        `${num(q.novel_templates)} novel · ${q.enforce_mode ? 'enforce' : 'shadow mode'}`;

      els.quarantineOut.classList.toggle('dim', items.length === 0);
      els.quarantineOut.innerHTML = items.length
        ? items.slice(0, 20).map((item) => {
            const g = item.gate || {};
            return `
              <div class="q-item">
                <div class="q-head">
                  <span class="q-flag ${g.novel ? 'novel' : 'watched'}">[${g.novel ? 'NOVEL' : 'watched'}]</span>
                  <span class="q-meta">×${esc(item.count ?? '?')} · d=${esc(g.distance ?? '?')} · guess=${esc(g.family_guess ?? '?')}</span>
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
        alert('Paste some logs first');
        els.input.focus();
        return;
      }
      if (els.run.disabled) return;

      els.run.disabled = true;
      els.runLabel.textContent = 'running…';
      setMode('running', 'running');

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
        const records = data.processed_logs || [];
        const wall = performance.now() - wallStart;

        const empty = els.stream.querySelector('.stream-empty');
        if (empty) empty.remove();

        runCount += 1;
        const divider = document.createElement('div');
        divider.className = 'run-divider';
        divider.innerHTML = `<span>run #${runCount} · ${records.length} line${records.length === 1 ? '' : 's'} · ${wall.toFixed(1)}ms</span>`;
        els.stream.appendChild(divider);

        const frag = document.createDocumentFragment();
        records.forEach((r, i) => {
          const row = renderRecord(r);
          if (records.length <= 3 && i === 0) {
            row.classList.add('is-open');
            row.querySelector('.rec-head').setAttribute('aria-expanded', 'true');
          }
          frag.appendChild(row);

          totals.total += 1;
          totals.latSum += Number(r.latency_ms) || 0;
          if (r.mode === 'Cached') totals.cached += 1;
          if (r.mode === 'Discovery') totals.disc += 1;
        });
        els.stream.appendChild(frag);
        scrollToBottom();

        els.hint.textContent = `${num(records.length)} record(s) · ${num(totals.cached)} cached · ${num(totals.disc)} discovery`;
        els.lastrun.textContent = `${wall.toFixed(0)}ms`;
        paintTelemetry();
        setMode('done', 'done');
        refreshAll();
      } catch (e) {
        setMode('error', 'error');
        alert('Ingest failed: ' + e.message);
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
