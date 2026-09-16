document.addEventListener('DOMContentLoaded', () => {
    const sampleSelect = document.getElementById('sample-select');
    const logInput = document.getElementById('log-input');
    const processBtn = document.getElementById('process-btn');
    const resultsContainer = document.getElementById('results-container');
    const cacheOutput = document.getElementById('cache-output');
    const refreshCacheBtn = document.getElementById('refresh-cache-btn');
    const template = document.getElementById('result-card-template');

    // Handle dropdown selection
    sampleSelect.addEventListener('change', (e) => {
        if (e.target.value) {
            // Append if there's already text, otherwise replace
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
            const data = await res.json();
            if (data.cache.length === 0) {
                cacheOutput.textContent = 'Cache is currently empty.';
            } else {
                cacheOutput.textContent = JSON.stringify(data.cache, null, 2);
            }
        } catch(e) {
            console.error('Failed to fetch cache', e);
        }
    };
    
    refreshCacheBtn.addEventListener('click', refreshCache);
    refreshCache(); // initial load

    processBtn.addEventListener('click', async () => {
        const rawText = logInput.value.trim();
        if (!rawText) {
            alert('Please enter a log to process.');
            return;
        }

        processBtn.textContent = 'Running Pipeline...';
        processBtn.disabled = true;
        
        resultsContainer.innerHTML = ''; // Clear previous runs
        
        try {
            const logs = rawText.split('\n'); // Send all lines

            const response = await fetch('/api/logs/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ logs })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            
            data.processed_logs.forEach(result => {
                const clone = template.content.cloneNode(true);
                
                const valMode = clone.querySelector('.val-mode');
                const valFormat = clone.querySelector('.val-format');
                const valLatency = clone.querySelector('.val-latency');
                const modeCard = clone.querySelector('.mode-card');
                const fieldsBody = clone.querySelector('.fields-body');
                const logOutput = clone.querySelector('.log-output');

                valMode.textContent = result.mode;
                valFormat.textContent = result.format;
                valLatency.textContent = `${result.latency_ms} ms`;
                
                // Highlight caching difference
                if (result.mode === 'Cached') {
                    modeCard.classList.add('mode-cached');
                    valMode.textContent = 'Cached (Fast Path)';
                } else {
                    modeCard.classList.add('mode-discovery');
                    valMode.textContent = 'Discovery (Inference)';
                }

                // Populate Inferred Fields Table
                const allFields = { ...result.extracted_fields, ...result.normalized.extra };
                for (const [key, value] of Object.entries(allFields)) {
                    if (key === 'raw_message' || value == null || value === '') continue;
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${key}</td><td>${value}</td>`;
                    fieldsBody.appendChild(tr);
                }
                
                if (fieldsBody.innerHTML === '') {
                    fieldsBody.innerHTML = '<tr><td colspan="2" style="text-align:center; color:#94a3b8">No fields extracted (Unstructured fallback)</td></tr>';
                }

                // Populate Normalized JSON
                logOutput.textContent = JSON.stringify(result.normalized, null, 2);
                
                resultsContainer.appendChild(clone);
            });
            
            // Auto refresh cache inspector
            await refreshCache();

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            processBtn.textContent = 'Run Pipeline';
            processBtn.disabled = false;
        }
    });
});
