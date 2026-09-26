const $ = id => document.getElementById(id);
const fetchJSON = async url => { try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch { return null; } };

document.addEventListener('DOMContentLoaded', () => {
  const els = {
    sample: $('sample-select'), input: $('log-input'), run: $('process-btn'), clear: $('clear-btn'),
    results: $('results-container'), hint: $('results-hint'), tmpl: $('result-card-template'),
    total: $('stat-total'), cached: $('stat-cached'), disc: $('stat-discovery'),
    fams: $('stat-families'), lat: $('stat-latency'), saved: $('stat-saved'), health: $('health-badge')
  };
  let tot = { total: 0, cached: 0, disc: 0, latSum: 0 };

  const updStats = () => {
    els.total.textContent = tot.total;
    els.cached.textContent = tot.cached;
    els.disc.textContent = tot.disc;
    els.lat.textContent = tot.total ? `${(tot.latSum / tot.total).toFixed(1)} ms` : '—';
    els.saved.textContent = tot.total ? `${Math.round(tot.cached / tot.total * 100)}%` : '0%';
    fetchHealth();
  };

  const fetchHealth = async () => {
    const h = await fetchJSON('/api/health');
    if (!h) { els.health.textContent = 'System offline'; els.health.className = 'health-badge warn'; return; }
    const n = h.family_cache?.families_learned ?? 0;
    els.fams.textContent = n;
    const ok = h.llm_configured;
    els.health.textContent = ok ? `LLM: ${h.provider} • ${h.model} • ${n} families` : `Heuristic • ${n} families`;
    els.health.className = `health-badge ${ok ? 'ok' : 'warn'}`;
    $('health-output').textContent = JSON.stringify(h, null, 2);
  };

  const refreshCache = async () => {
    const d = await fetchJSON('/api/logs/cache');
    if (!d) return;
    $('family-output').textContent = JSON.stringify(d.family_cache || {}, null, 2);
    $('cache-output').textContent = JSON.stringify(d.cache || [], null, 2);
  };

  const refreshTemplates = async () => {
    const t = await fetchJSON('/api/logs/templates');
    if (!t) return;
    $('tier-stats').textContent = `${t.clusters} clusters • ${t.rules_learned} rules • ${t.rule_backend}${t.enforce_mode ? ' • ENFORCE' : ''}`;
    const body = $('templates-body'); body.innerHTML = '';
    if (!t.templates?.length) {
      body.innerHTML = '<tr><td colspan="3" class="muted">No templates mined yet</td></tr>'; return;
    }
    body.append(...t.templates.map(tpl => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td style="font-family:var(--mono)" title="cluster #${tpl.cluster_id}">${tpl.template}</td><td>${tpl.size}</td><td style="color:${tpl.has_rule ? 'var(--green)' : 'var(--muted)'}">${tpl.has_rule ? 'rule ✓' : '—'}</td>`;
      return tr;
    }));
  };

  const refreshQuarantine = async () => {
    const q = await fetchJSON('/api/logs/quarantine');
    if (!q) return;
    const out = $('quarantine-output'); out.innerHTML = '';
    if (!q.items?.length) { out.textContent = 'No novel templates seen.'; return; }
    out.append(...q.items.slice(0, 20).map(item => {
      const g = item.gate || {};
      const div = document.createElement('div');
      div.style.cssText = 'margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--border)';
      div.innerHTML = `<div style="font-family:var(--mono);font-size:11px;color:${g.novel ? 'var(--yellow)' : 'var(--muted)'}">[${g.novel ? 'NOVEL' : 'watched'}] ×${item.count} d=${g.distance ?? '?'} guess=${g.family_guess ?? '?'} — ${item.template}</div><pre style="margin:6px 0 0;font-size:10px">${(item.samples || [])[0] || ''}</pre>`;
      return div;
    }));
    $('gate-stats').textContent = `${q.novel_templates} novel`;
  };

  els.sample.addEventListener('change', e => { if (e.target.value) { els.input.value = e.target.value; els.input.focus(); } });
  els.clear.addEventListener('click', () => {
    els.input.value = '';
    els.results.innerHTML = '<div class="empty-state"><div class="empty-icon">◫</div><p>Results will appear here</p><small>Try CSV: first=Discovery, second=Cached</small></div>';
    els.hint.textContent = 'No logs processed yet';
    tot = { total: 0, cached: 0, disc: 0, latSum: 0 }; updStats();
  });

  document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn,.tab-pane').forEach(x => x.classList.remove('active'));
    b.classList.add('active'); $(`tab-${b.dataset.tab}`).classList.add('active');
  }));

  ['family','cache'].forEach(id => $(`refresh-${id}-btn`)?.addEventListener('click', refreshCache));
  $('refresh-templates-btn').addEventListener('click', refreshTemplates);
  $('refresh-quarantine-btn').addEventListener('click', refreshQuarantine);
  $('refresh-health-btn').addEventListener('click', fetchHealth);

  fetchHealth(); refreshCache(); refreshTemplates(); refreshQuarantine();

  els.run.addEventListener('click', async () => {
    const raw = els.input.value.trim();
    if (!raw) return alert('Paste some logs first');
    els.run.disabled = true; els.run.innerHTML = '<span class="btn-icon">⏳</span> Running...';
    try {
      const logs = raw.split('\n').filter(l => l.trim());
      const res = await fetch('/api/logs/ingest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ logs }) });
      if (!res.ok) throw new Error(JSON.stringify((await res.json()).detail || {}));
      const data = await res.json();
      if (els.results.querySelector('.empty-state')) els.results.innerHTML = '';
      const frag = document.createDocumentFragment();

      data.processed_logs.forEach(r => {
        const c = els.tmpl.content.cloneNode(true);
        const badge = c.querySelector('.mode-badge');
        c.querySelector('.val-format').textContent = r.format || 'Unknown';
        c.querySelector('.val-family').textContent = r.family || 'generic';
        c.querySelector('.val-latency').textContent = `${r.latency_ms} ms`;
        c.querySelector('.val-by').textContent = r.inferred_by || '—';
        badge.textContent = r.mode === 'Cached' ? 'Cached' : r.mode === 'Discovery' ? `Discovery (${r.inferred_by === 'llm' ? 'LLM' : 'Heuristic'})` : r.mode;
        badge.classList.add({ Cached: 'cached', Discovery: 'discovery', Quarantined: 'quarantined' }[r.mode] || 'error');

        const note = c.querySelector('.llm-note');
        if (r.llm_error) { note.textContent = r.llm_error; note.style.display = 'block'; }
        if (r.gate) {
          const g = r.gate, d = document.createElement('div');
          d.style.cssText = 'font-size:11px;font-family:var(--mono);margin-top:6px;color:' + (g.novel ? 'var(--yellow)' : 'var(--cyan)');
          d.textContent = `Gate: ${g.novel ? 'NOVEL' : 'known'} d=${g.distance} guess=${g.family_guess}`;
          note.parentNode.insertBefore(d, note.nextSibling);
        }

        const body = c.querySelector('.fields-body'); body.innerHTML = '';
        if (r.mode === 'Error' && r.error) {
          body.innerHTML = `<tr><td>error</td><td>${r.error}</td></tr>`;
        } else {
          const all = { ...r.extracted_fields, ...r.normalized.extra };
          const rows = Object.entries(all).filter(([k, v]) => k !== 'raw_message' && v != null && v !== '').map(([k, v]) => `<tr><td>${k}</td><td>${typeof v === 'object' ? JSON.stringify(v) : v}</td></tr>`).join('');
          body.innerHTML = rows || '<tr><td colspan="2" class="muted" style="text-align:center">No fields extracted</td></tr>';
        }
        c.querySelector('.log-output').textContent = JSON.stringify(r.normalized, null, 2);
        c.querySelector('.toggle-json').addEventListener('click', e => {
          const pre = e.target.closest('.normalized-section').querySelector('.log-output');
          pre.style.display = pre.style.display === 'none' ? 'block' : 'none';
        });
        frag.appendChild(c);
        tot.total++; tot.latSum += r.latency_ms || 0;
        if (r.mode === 'Cached') tot.cached++;
        if (r.mode === 'Discovery') tot.disc++;
      });

      els.results.prepend(frag);
      els.hint.textContent = `${data.processed_logs.length} log(s) • ${tot.cached} cached • ${tot.disc} discovery`;
      updStats(); refreshCache(); refreshTemplates(); refreshQuarantine();
    } catch (e) { alert('Error: ' + e.message); }
    finally { els.run.disabled = false; els.run.innerHTML = '<span class="btn-icon">▶</span> Analyze Logs'; }
  });
});
