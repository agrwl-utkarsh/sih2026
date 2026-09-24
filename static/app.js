document.addEventListener('DOMContentLoaded', () => {
    const sampleSelect = document.getElementById('sample-select');
    const logInput = document.getElementById('log-input');
    const processBtn = document.getElementById('process-btn');
    const resultsContainer = document.getElementById('results-container');
    const cacheOutput = document.getElementById('cache-output');
    const refreshCacheBtn = document.getElementById('refresh-cache-btn');
    const template = document.getElementById('result-card-template');

    sampleSelect.addEventListener('change', (e) => {
        if (e.target.value) {
            logInput.value = e.target.value;
            resultsContainer.textContent = '';
        }
    });

    const refreshCache = async () => {
        try {
            const res = await fetch('/api/logs/cache');
            if (!res.ok) {
                const data = await res.json();
                cacheOutput.textContent = `Error fetching cache: ${JSON.stringify(data.detail || data)}`;
                return;
            }
            const data = await res.json();
            if (data.cache && data.cache.length === 0) {
                cacheOutput.textContent = 'Cache is currently empty.';
            } else {
                cacheOutput.textContent = JSON.stringify(data.cache, null, 2);
            }
        } catch(e) {
            console.error('Failed to fetch cache', e);
            cacheOutput.textContent = 'Network error fetching cache.';
        }
    };
    
    refreshCacheBtn.addEventListener('click', refreshCache);

    // ---------- Drain3 template tier + novelty quarantine panels ----------
    const templatesBody = document.getElementById('templates-body');
    const quarantineOutput = document.getElementById('quarantine-output');
    const tierStats = document.getElementById('tier-stats');
    const gateStats = document.getElementById('gate-stats');

    const refreshTemplates = async () => {
        try {
            const res = await fetch('/api/logs/templates');
            if (!res.ok) return;
            const t = await res.json();
            templatesBody.textContent = '';
            tierStats.textContent = `${t.clusters} clusters · ${t.rules_learned} rules · backend: ${t.rule_backend}${t.enforce_mode ? ' · ENFORCE' : ''}`;
            if (!t.templates.length) {
                const tr = document.createElement('tr');
                const td = document.createElement('td'); td.setAttribute('colspan','4');
                td.style.textAlign = 'center'; td.style.color = '#94a3b8';
                td.textContent = 'No templates mined yet — run some logs.';
                tr.appendChild(td); templatesBody.appendChild(tr);
                return;
            }
            t.templates.forEach(tpl => {
                const tr = document.createElement('tr');
                const tdT = document.createElement('td');
                tdT.textContent = tpl.template;
                tdT.style.fontFamily = 'var(--font-code)'; tdT.style.fontSize = '0.75rem';
                tdT.title = `cluster #${tpl.cluster_id}`;
                const tdN = document.createElement('td'); tdN.textContent = tpl.size;
                const tdR = document.createElement('td');
                tdR.textContent = tpl.has_rule ? 'rule ✓' : '—';
                tdR.style.color = tpl.has_rule ? 'var(--accent-green)' : '#94a3b8';
                const tdM = document.createElement('td');
                tdM.textContent = t.enforce_mode ? 'enforce' : 'shadow';
                tdM.style.color = '#94a3b8';
                tr.appendChild(tdT); tr.appendChild(tdN); tr.appendChild(tdR); tr.appendChild(tdM);
                templatesBody.appendChild(tr);
            });
        } catch(e) { console.error('Failed to fetch templates', e); }
    };

    const refreshQuarantine = async () => {
        try {
            const res = await fetch('/api/logs/quarantine');
            if (!res.ok) return;
            const q = await res.json();
            quarantineOutput.textContent = '';
            if (!q.items || !q.items.length) {
                quarantineOutput.textContent = 'No novel templates seen.';
                return;
            }
            const list = document.createElement('div');
            q.items.slice(0, 10).forEach(item => {
                const row = document.createElement('div');
                row.style.marginBottom = '0.9rem';
                const head = document.createElement('div');
                head.style.fontFamily = 'var(--font-code)'; head.style.fontSize = '0.75rem';
                const g = item.gate || {};
                const burden = g.novel ? 'NOVEL' : 'watched';
                head.textContent = `[${burden}] ×${item.count}  d=${g.distance ?? '?'}  guess=${g.family_guess ?? '?'} — ${item.template}`;
                head.style.color = g.novel ? 'var(--accent-yellow)' : '#94a3b8';
                const samp = document.createElement('pre');
                samp.style.margin = '0.3rem 0 0 0'; samp.style.fontSize = '0.7rem';
                samp.style.whiteSpace = 'pre-wrap'; samp.style.color = '#94a3b8';
                samp.textContent = (item.samples || [])[0] || '';
                row.appendChild(head); row.appendChild(samp);
                list.appendChild(row);
            });
            quarantineOutput.appendChild(list);
        } catch(e) { console.error('Failed to fetch quarantine', e); }
    };

    const loadGateInfo = async () => {
        try {
            const res = await fetch('/api/health');
            if (!res.ok) return;
            const h = await res.json();
            const g = h.format_gate || {};
            gateStats.textContent = g.loaded
                ? `gate ready · thr ${g.threshold} · n=${g.n_train} lines`
                : `gate unavailable (${g.reason})`;
        } catch(e) { /* server without gate info */ }
    };

    document.getElementById('refresh-templates-btn').addEventListener('click', refreshTemplates);
    document.getElementById('refresh-quarantine-btn').addEventListener('click', refreshQuarantine);
    refreshTemplates(); refreshQuarantine(); loadGateInfo();

    processBtn.addEventListener('click', async () => {
        const rawText = logInput.value.trim();
        if (!rawText) {
            alert('Please enter a log to process.');
            return;
        }

        processBtn.textContent = 'Running Pipeline...';
        processBtn.disabled = true;
        
        resultsContainer.textContent = ''; 
        
        try {
            const logs = rawText.split('\n');

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
            
            const fragment = document.createDocumentFragment();
            data.processed_logs.forEach(result => {
                const clone = template.content.cloneNode(true);
                
                const valMode = clone.querySelector('.val-mode');
                const valFormat = clone.querySelector('.val-format');
                const valLatency = clone.querySelector('.val-latency');
                const modeCard = clone.querySelector('.mode-card');
                const fieldsBody = clone.querySelector('.fields-body');
                const logOutput = clone.querySelector('.log-output');

                valFormat.textContent = result.format;
                valLatency.textContent = `${result.latency_ms} ms`;
                
                if (result.mode === 'Cached') {
                    modeCard.classList.add('mode-cached');
                    valMode.textContent = 'Cached (Fast Path)';
                } else if (result.mode === 'Template-Rule') {
                    modeCard.classList.add('mode-template');
                    valMode.textContent = 'Template-Rule (Drain3)';
                    if (result.gate && result.gate.novel === false) {
                        const note = clone.querySelector('.llm-error-note');
                        note.textContent = `ML gate: known family (${result.gate.family_guess}), d=${result.gate.distance} — zero LLM calls`;
                        note.style.color = 'var(--accent-cyan)';
                        note.style.display = 'block';
                    }
                } else if (result.mode === 'Quarantined') {
                    modeCard.classList.add('mode-quarantine');
                    valMode.textContent = 'Quarantined (novel format)';
                    const note = clone.querySelector('.llm-error-note');
                    const g = result.gate || {};
                    const q = result.quarantine || {};
                    note.textContent = `ML gate: NOVEL (d=${g.distance} > thr) · seen ${q.count}/${q.graduate_after} before one LLM call · zero key spend so far`;
                    note.style.color = 'var(--accent-yellow)';
                    note.style.display = 'block';
                } else if (result.mode === 'Discovery') {
                    modeCard.classList.add('mode-discovery');
                    const by = result.inferred_by === 'llm' ? 'LLM' : 'Heuristic';
                    valMode.textContent = `Discovery (${by})`;
                    if (result.gate && result.gate.novel) {
                        const note2 = clone.querySelector('.llm-error-note');
                        note2.textContent = `ML gate: NOVEL family flagged (d=${result.gate.distance}) — visible in quarantine panel`;
                        note2.style.color = 'var(--accent-yellow)';
                        note2.style.display = 'block';
                    } else if (result.llm_error) {
                        const note = clone.querySelector('.llm-error-note');
                        note.textContent = `LLM fallback: ${result.llm_error}`;
                        note.title = result.llm_error;
                        note.style.display = 'block';
                    }
                } else if (result.mode === 'Error') {
                    modeCard.classList.add('mode-error');
                    valMode.textContent = 'Error';
                }

                // Populate Fields Table without innerHTML
                fieldsBody.textContent = '';
                
                if (result.mode === 'Error' && result.error) {
                    const tr = document.createElement('tr');
                    const tdKey = document.createElement('td');
                    tdKey.textContent = 'error';
                    const tdVal = document.createElement('td');
                    tdVal.textContent = result.error;
                    tr.appendChild(tdKey);
                    tr.appendChild(tdVal);
                    fieldsBody.appendChild(tr);
                } else {
                    const allFields = { ...result.extracted_fields, ...result.normalized.extra };
                    for (const [key, value] of Object.entries(allFields)) {
                        if (key === 'raw_message' || value == null || value === '') continue;
                        const tr = document.createElement('tr');
                        const tdKey = document.createElement('td');
                        tdKey.textContent = key;
                        const tdVal = document.createElement('td');
                        tdVal.textContent = typeof value === 'object' ? JSON.stringify(value) : value;
                        tr.appendChild(tdKey);
                        tr.appendChild(tdVal);
                        fieldsBody.appendChild(tr);
                    }
                }
                
                if (fieldsBody.children.length === 0) {
                    const tr = document.createElement('tr');
                    const td = document.createElement('td');
                    td.setAttribute('colspan', '2');
                    td.style.textAlign = 'center';
                    td.style.color = '#94a3b8';
                    td.textContent = 'No fields extracted (Unstructured fallback)';
                    tr.appendChild(td);
                    fieldsBody.appendChild(tr);
                }

                logOutput.textContent = JSON.stringify(result.normalized, null, 2);
                fragment.appendChild(clone);
            });
            resultsContainer.appendChild(fragment);
            
            await refreshCache();
            await refreshTemplates();
            await refreshQuarantine();

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            processBtn.textContent = 'Run Pipeline';
            processBtn.disabled = false;
        }
    });
});
