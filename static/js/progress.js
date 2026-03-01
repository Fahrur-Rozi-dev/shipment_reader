/**
 * PROGRESS — SSE streaming, progress bar, processing step indicators
 */

const progressBar = document.getElementById('progress-bar');
const progressPages = document.getElementById('progress-pages');
const progressPct = document.getElementById('progress-percent');
const progressMsg = document.getElementById('progress-message');

function listenForProgress(jobId) {
    const es = new EventSource(`/progress/${jobId}`);

    es.addEventListener('progress', (e) => {
        const d = JSON.parse(e.data);
        updateProgress(d);
    });

    es.addEventListener('complete', (e) => {
        es.close();
        const d = JSON.parse(e.data);
        showResults(d.result);
    });

    es.addEventListener('error', (e) => {
        if (e.data) {
            const d = JSON.parse(e.data);
            showError(d.message || 'Processing failed');
        }
        es.close();
    });

    es.onerror = () => {
        es.close();
        fetchResult(jobId);
    };
}

function updateProgress(data) {
    const pct = data.total > 0
        ? Math.round((data.progress / data.total) * 100)
        : 0;
    progressBar.style.width = pct + '%';
    progressPages.textContent = `Page ${data.progress} / ${data.total}`;
    progressPct.textContent = pct + '%';
    if (data.message) progressMsg.textContent = data.message;
}

async function fetchResult(jobId) {
    try {
        const resp = await fetch(`/result/${jobId}`);
        const data = await resp.json();
        if (data.status === 'completed' && data.result) {
            showResults(data.result);
        } else if (data.status === 'error') {
            showError(data.error || 'Processing failed');
        }
    } catch (err) {
        showError('Failed to fetch results');
    }
}
