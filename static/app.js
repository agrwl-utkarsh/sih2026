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
            if (logInput.value.trim()) {
                logInput.value = logInput.value.trim() + '\n' + e.target.value;
            } else {
                logInput.value = e.target.value;
            }
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
    refreshCache();

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
                } else if (result.mode === 'Discovery') {
                    modeCard.classList.add('mode-discovery');
                    const by = result.inferred_by === 'llm' ? 'LLM' : 'Heuristic';
                    valMode.textContent = `Discovery (${by})`;
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
                resultsContainer.appendChild(clone);
            });
            
            await refreshCache();

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            processBtn.textContent = 'Run Pipeline';
            processBtn.disabled = false;
        }
    });
});
