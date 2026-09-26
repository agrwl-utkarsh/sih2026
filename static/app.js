document.addEventListener('DOMContentLoaded', () => {
  const sampleSelect = document.getElementById('sample-select');
  const logInput = document.getElementById('log-input');
  const processBtn = document.getElementById('process-btn');
  const clearBtn = document.getElementById('clear-btn');
  const resultsContainer = document.getElementById('results-container');
  const resultsHint = document.getElementById('results-hint');
  const template = document.getElementById('result-card-template');

  // Stats
  const statTotal = document.getElementById('stat-total');
  const statCached = document.getElementById('stat-cached');
  const statDiscovery = document.getElementById('stat-discovery');
  const statFamilies = document.getElementById('stat-families');
  const statLatency = document.getElementById('stat-latency');
  const statSaved = document.getElementById('stat-saved');
  const healthBadge = document.getElementById('health-badge');

  let totals = { total: 0, cached: 0, discovery: 0, latencySum: 0 };

  sampleSelect.addEventListener('change', (e) => {
    if (e.target.value) {
      logInput.value = e.target.value;
      logInput.focus();
    }
  });

  clearBtn.addEventListener('click', () => {
    logInput.value = '';
    resultsContainer.innerHTML = '<div class="empty-state"><div class="empty-icon">◫</div><p>Results will appear here after analysis</p><small>Try CSV sample: first run = Discovery, second run = Cached (no LLM)</small></div>';
    resultsHint.textContent = 'No logs processed yet';
    totals = { total: 0, cached: 0, discovery: 0, latencySum: 0 };
    updateStats();
  });

  function updateStats() {
    statTotal.textContent = totals.total;
    statCached.textContent = totals.cached;
    statDiscovery.textContent = totals.discovery;
    const avg = totals.total ? (totals.latencySum / totals.total).toFixed(1) + ' ms' : '—';
    statLatency.textContent = avg;
    const saved = totals.total ? Math.round((totals.cached / totals.total) * 100) : 0;
    statSaved.textContent = saved + '%';
    // families from health
    fetchHealth();
  }

  async function fetchHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('health failed');
      const h = await res.json();
      const families = h.family_cache?.families_learned ?? 0;
      statFamilies.textContent = families;
      const llmOk = h.llm_configured;
      const provider = h.provider || 'heuristic';
      const model = h.model || 'heuristic';
      healthBadge.textContent = llmOk ? `LLM: ${provider} • ${model} • ${families} families` : `Heuristic mode • ${families} families`;
      healthBadge.className = 'health-badge ' + (llmOk ? 'ok' : 'warn');
      document.getElementById('health-output').textContent = JSON.stringify(h, null, 2);
    } catch (e) {
      healthBadge.textContent = 'System offline';
      healthBadge.className = 'health-badge warn';
    }
  }

  async function refreshFamily() {
    try {
      const res = await fetch('/api/logs/cache');
      if (!res.ok) return;
      const data = await res.json();
      document.getElementById('family-output').textContent = JSON.stringify(data.family_cache || {}, null, 2);
      document.getElementById('cache-output').textContent = JSON.stringify(data.cache || [], null, 2);
    } catch (e) {}
  }

  async function refreshTemplates() {
    try {
      const res = await fetch('/api/logs/templates');
      if (!res.ok) return;
      const t = await res.json();
      document.getElementById('tier-stats').textContent = `${t.clusters} clusters • ${t.rules_learned} rules • ${t.rule_backend}${t.enforce_mode ? ' • ENFORCE' : ''}`;
      const body = document.getElementById('templates-body');
      body.innerHTML = '';
      if (!t.templates || !t.templates.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td'); td.colSpan = 3; td.className = 'muted'; td.textContent = 'No templates mined yet — run some logs.';
        tr.appendChild(td); body.appendChild(tr); return;
      }
      t.templates.forEach(tpl => {
        const tr = document.createElement('tr');
        const tdT = document.createElement('td'); tdT.textContent = tpl.template; tdT.style.fontFamily = 'var(--mono)'; tdT.title = `cluster #${tpl.cluster_id}`;
        const tdN = document.createElement('td'); tdN.textContent = tpl.size;
        const tdR = document.createElement('td'); tdR.textContent = tpl.has_rule ? 'rule ✓' : '—'; tdR.style.color = tpl.has_rule ? 'var(--green)' : 'var(--muted)';
        tr.appendChild(tdT); tr.appendChild(tdN); tr.appendChild(tdR); body.appendChild(tr);
      });
    } catch (e) {}
  }

  async function refreshQuarantine() {
    try {
      const res = await fetch('/api/logs/quarantine');
      if (!res.ok) return;
      const q = await res.json();
      const out = document.getElementById('quarantine-output');
      out.innerHTML = '';
      if (!q.items || !q.items.length) { out.textContent = 'No novel templates seen.'; return; }
      const list = document.createElement('div');
      q.items.slice(0, 20).forEach(item => {
        const row = document.createElement('div'); row.style.marginBottom = '12px'; row.style.paddingBottom = '12px'; row.style.borderBottom = '1px solid var(--border)';
        const head = document.createElement('div'); head.style.fontFamily = 'var(--mono)'; head.style.fontSize = '11px';
        const g = item.gate || {}; head.textContent = `[${g.novel ? 'NOVEL' : 'watched'}] ×${item.count} d=${g.distance ?? '?'} guess=${g.family_guess ?? '?'} — ${item.template}`; head.style.color = g.novel ? 'var(--yellow)' : 'var(--muted)';
        const samp = document.createElement('pre'); samp.style.margin = '6px 0 0'; samp.style.fontSize = '10px'; samp.textContent = (item.samples || [])[0] || '';
        row.appendChild(head); row.appendChild(samp); list.appendChild(row);
      });
      out.appendChild(list);
      document.getElementById('gate-stats').textContent = `${q.novel_templates} novel`;
    } catch (e) {}
  }

  async function refreshHealth() { fetchHealth(); }

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
  });

  document.getElementById('refresh-family-btn').addEventListener('click', refreshFamily);
  document.getElementById('refresh-cache-btn').addEventListener('click', refreshFamily);
  document.getElementById('refresh-templates-btn').addEventListener('click', refreshTemplates);
  document.getElementById('refresh-quarantine-btn').addEventListener('click', refreshQuarantine);
  document.getElementById('refresh-health-btn').addEventListener('click', refreshHealth);

  // Initial load
  fetchHealth(); refreshFamily(); refreshTemplates(); refreshQuarantine();

  processBtn.addEventListener('click', async () => {
    const rawText = logInput.value.trim();
    if (!rawText) { alert('Paste some logs first'); return; }
    processBtn.disabled = true; processBtn.innerHTML = '<span class="btn-icon">⏳</span> Running...';
    try {
      const logs = rawText.split('\n').filter(l => l.trim().length > 0);
      const response = await fetch('/api/logs/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ logs })
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(JSON.stringify(data.detail || data));
      }
      const data = await response.json();
      if (resultsContainer.querySelector('.empty-state')) resultsContainer.innerHTML = '';
      const fragment = document.createDocumentFragment();
      data.processed_logs.forEach(result => {
        const clone = template.content.cloneNode(true);
        const badge = clone.querySelector('.mode-badge');
        const valFormat = clone.querySelector('.val-format');
        const valFamily = clone.querySelector('.val-family');
        const valLatency = clone.querySelector('.val-latency');
        const valBy = clone.querySelector('.val-by');
        const fieldsBody = clone.querySelector('.fields-body');
        const logOutput = clone.querySelector('.log-output');
        const llmNote = clone.querySelector('.llm-note');

        valFormat.textContent = result.format || 'Unknown';
        valFamily.textContent = result.family || 'generic';
        valLatency.textContent = `${result.latency_ms} ms`;
        valBy.textContent = result.inferred_by || '—';

        if (result.mode === 'Cached') {
          badge.classList.add('cached'); badge.textContent = 'Cached';
        } else if (result.mode === 'Discovery') {
          badge.classList.add('discovery'); badge.textContent = `Discovery (${result.inferred_by === 'llm' ? 'LLM' : 'Heuristic'})`;
        } else if (result.mode === 'Quarantined') {
          badge.classList.add('quarantined'); badge.textContent = 'Quarantined';
        } else {
          badge.classList.add('error'); badge.textContent = result.mode;
        }

        if (result.llm_error) {
          llmNote.textContent = result.llm_error; llmNote.style.display = 'block';
        }
        if (result.gate) {
          const g = result.gate;
          const note = document.createElement('div');
          note.style.fontSize = '11px'; note.style.color = g.novel ? 'var(--yellow)' : 'var(--cyan)';
          note.style.fontFamily = 'var(--mono)'; note.style.marginTop = '6px';
          note.textContent = `Gate: ${g.novel ? 'NOVEL' : 'known'} d=${g.distance} family_guess=${g.family_guess}`;
          llmNote.parentNode.insertBefore(note, llmNote.nextSibling);
        }

        // Fields
        fieldsBody.innerHTML = '';
        if (result.mode === 'Error' && result.error) {
          const tr = document.createElement('tr');
          const tdK = document.createElement('td'); tdK.textContent = 'error';
          const tdV = document.createElement('td'); tdV.textContent = result.error;
          tr.appendChild(tdK); tr.appendChild(tdV); fieldsBody.appendChild(tr);
        } else {
          const allFields = { ...result.extracted_fields, ...result.normalized.extra };
          let has = false;
          for (const [k,v] of Object.entries(allFields)) {
            if (k === 'raw_message' || v == null || v === '') continue;
            has = true;
            const tr = document.createElement('tr');
            const tdK = document.createElement('td'); tdK.textContent = k;
            const tdV = document.createElement('td'); tdV.textContent = typeof v === 'object' ? JSON.stringify(v) : String(v);
            tr.appendChild(tdK); tr.appendChild(tdV); fieldsBody.appendChild(tr);
          }
          if (!has) {
            const tr = document.createElement('tr');
            const td = document.createElement('td'); td.colSpan = 2; td.className = 'muted'; td.style.textAlign = 'center'; td.textContent = 'No fields extracted';
            tr.appendChild(td); fieldsBody.appendChild(tr);
          }
        }

        logOutput.textContent = JSON.stringify(result.normalized, null, 2);
        const toggle = clone.querySelector('.toggle-json');
        toggle.addEventListener('click', () => {
          logOutput.style.display = logOutput.style.display === 'none' ? 'block' : 'none';
        });

        fragment.appendChild(clone);

        // Stats
        totals.total++;
        totals.latencySum += result.latency_ms || 0;
        if (result.mode === 'Cached') totals.cached++;
        if (result.mode === 'Discovery') totals.discovery++;
      });

      resultsContainer.prepend(fragment);
      resultsHint.textContent = `${data.processed_logs.length} log(s) processed • ${totals.cached} cached • ${totals.discovery} discovery`;
      updateStats();
      refreshFamily(); refreshTemplates(); refreshQuarantine();
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      processBtn.disabled = false; processBtn.innerHTML = '<span class="btn-icon">▶</span> Analyze Logs';
    }
  });
});
