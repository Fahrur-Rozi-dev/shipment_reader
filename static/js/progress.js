/**
 * PROGRESS — SSE streaming with polling fallback for HF Spaces
 */

const progressBar = document.getElementById('progress-bar');
const progressPages = document.getElementById('progress-pages');
const progressPct = document.getElementById('progress-percent');
const progressMsg = document.getElementById('progress-message');

function listenForProgress(jobId) {
    let sseWorking = false;
    let pollTimer = null;

    // Start polling fallback after 5 seconds if SSE hasn't delivered
    pollTimer = setTimeout(() => {
        if (!sseWorking) {
            console.log('SSE not responding, switching to polling...');
            startPolling(jobId);
        }
    }, 5000);

    const es = new EventSource(`/progress/${jobId}`);

    es.addEventListener('progress', (e) => {
        sseWorking = true;
        if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
        const d = JSON.parse(e.data);
        updateProgress(d);
    });

    es.addEventListener('complete', (e) => {
        sseWorking = true;
        es.close();
        if (pollTimer) clearTimeout(pollTimer);
        const d = JSON.parse(e.data);
        showResults(d.result);
    });

    es.addEventListener('error', (e) => {
        if (e.data) {
            const d = JSON.parse(e.data);
            showError(d.message || 'Processing failed');
        }
        es.close();
        if (pollTimer) clearTimeout(pollTimer);
    });

    es.onerror = () => {
        es.close();
        if (pollTimer) clearTimeout(pollTimer);
        // Fallback: poll for result
        startPolling(jobId);
    };
}

function startPolling(jobId) {
    console.log('Polling for results...');
    const poll = setInterval(async () => {
        try {
            const resp = await fetch(`/result/${jobId}`);
            const data = await resp.json();

            if (data.status === 'completed' && data.result) {
                clearInterval(poll);
                showResults(data.result);
            } else if (data.status === 'error') {
                clearInterval(poll);
                showError(data.error || 'Processing failed');
            } else if (data.status === 'processing') {
                // Update progress from result endpoint
                updateProgress({
                    progress: data.progress || 0,
                    total: data.total || 0,
                    message: data.message || 'Processing...',
                });
            }
        } catch (err) {
            console.warn('Poll error:', err);
        }
    }, 2000); // Poll every 2 seconds

    // Safety timeout: stop polling after 10 minutes
    setTimeout(() => {
        clearInterval(poll);
        showError('Processing timeout. Please try again.');
    }, 600000);
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
