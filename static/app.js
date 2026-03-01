/**
 * ShipExtract — Frontend with Split-View Validation
 */

// ── DOM Elements ─────────────────────────────────────────────
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const fileSize = document.getElementById('file-size');
const btnExtract = document.getElementById('btn-extract');
const uploadSection = document.getElementById('upload-section');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const errorSection = document.getElementById('error-section');
const progressBar = document.getElementById('progress-bar');
const progressPages = document.getElementById('progress-pages');
const progressPct = document.getElementById('progress-percent');
const progressMsg = document.getElementById('progress-message');
const pageResultsList = document.getElementById('page-results-list');
const pageIndicator = document.getElementById('page-indicator');
const previewImg = document.getElementById('page-preview-img');
const zoomLevel = document.getElementById('zoom-level');

// ── State ────────────────────────────────────────────────────
let selectedFile = null;
let currentJobId = null;
let currentPage = 1;
let totalPages = 1;
let resultData = null;
let zoom = 100;

// ── File Drop & Select ──────────────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) handleFileSelect(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
});

function handleFileSelect(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showToast('Please select a PDF file', 'error');
        return;
    }
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatSize(file.size);
    fileInfo.style.display = 'inline-flex';
    btnExtract.disabled = false;
}

// ── Upload & Process ─────────────────────────────────────────
btnExtract.addEventListener('click', startExtraction);

async function startExtraction() {
    if (!selectedFile) return;
    btnExtract.disabled = true;
    showSection('progress');

    const formData = new FormData();
    formData.append('pdf', selectedFile);

    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!resp.ok) { showError(data.error || 'Upload failed'); return; }
        currentJobId = data.job_id;
        listenForProgress(currentJobId);
    } catch (err) {
        showError('Network error: ' + err.message);
    }
}

// ── SSE Progress ─────────────────────────────────────────────
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

    es.onerror = () => { es.close(); fetchResult(jobId); };
}

function updateProgress(data) {
    const pct = data.total > 0 ? Math.round((data.progress / data.total) * 100) : 0;
    progressBar.style.width = pct + '%';
    progressPages.textContent = `Page ${data.progress} / ${data.total}`;
    progressPct.textContent = pct + '%';
    if (data.message) progressMsg.textContent = data.message;
}

async function fetchResult(jobId) {
    try {
        const resp = await fetch(`/result/${jobId}`);
        const data = await resp.json();
        if (data.status === 'completed' && data.result) showResults(data.result);
        else if (data.status === 'error') showError(data.error || 'Processing failed');
    } catch (err) { showError('Failed to fetch results'); }
}

// ══════════════════════════════════════════════════════════════
// RESULTS — SPLIT VIEW
// ══════════════════════════════════════════════════════════════

function showResults(result) {
    resultData = result;
    const jobId = result.job_id;
    totalPages = result.total_pages || 1;
    currentPage = 1;

    showSection('results');

    // Stats
    const stats = result.stats || {};
    document.getElementById('stat-pages').textContent = stats.total_pages || 0;
    document.getElementById('stat-shipments').textContent = stats.total_shipments || 0;
    document.getElementById('stat-items').textContent = stats.total_items || 0;

    const reviewCount = (result.manual_review || []).length;
    if (reviewCount > 0) {
        document.getElementById('stat-review-card').style.display = '';
        document.getElementById('stat-review').textContent = reviewCount;
    }

    // Build page cards on the left
    buildPageCards(result);

    // Show first page
    selectPage(1);
}

function buildPageCards(result) {
    pageResultsList.innerHTML = '';
    const pageResults = result.page_results || [];
    const shipments = result.shipments || [];

    // Build a page → shipment map
    const pageShipmentMap = {};
    shipments.forEach(s => {
        (s.pages || []).forEach(p => {
            pageShipmentMap[p] = s;
        });
    });

    for (let i = 0; i < (result.total_pages || 0); i++) {
        const pageNum = i + 1;
        const pr = pageResults[i] || {};
        const shipment = pageShipmentMap[pageNum];

        const card = document.createElement('div');
        card.className = 'page-result-card';
        card.dataset.page = pageNum;
        card.addEventListener('click', () => selectPage(pageNum));

        // Header
        const header = document.createElement('div');
        header.className = 'page-card-header';

        const badge = document.createElement('div');
        badge.className = 'page-badge';
        badge.textContent = pageNum;

        const info = document.createElement('div');
        info.className = 'page-card-info';

        // Tracking number
        const tracking = document.createElement('div');
        const trackingNum = shipment ? shipment.tracking_number : (pr.tracking_number || '');
        if (trackingNum) {
            tracking.className = 'page-card-tracking';
            tracking.textContent = trackingNum;
        } else {
            tracking.className = 'page-card-tracking empty';
            tracking.textContent = pr.is_empty ? '(empty page)' : '(no tracking)';
        }

        // Meta info
        const meta = document.createElement('div');
        meta.className = 'page-card-meta';
        const items = shipment ? shipment.items : (pr.items || []);
        const itemCount = items.length;
        const totalQty = items.reduce((sum, it) => sum + (it.quantity || 1), 0);
        meta.textContent = itemCount > 0
            ? `${itemCount} item${itemCount > 1 ? 's' : ''} · Qty: ${totalQty}`
            : 'No items detected';

        info.appendChild(tracking);
        info.appendChild(meta);

        // Confidence badge
        const conf = document.createElement('div');
        const confVal = pr.confidence || 0;
        conf.className = 'page-card-confidence ' + (confVal >= 70 ? 'conf-high' : confVal >= 50 ? 'conf-med' : 'conf-low');
        conf.textContent = confVal + '%';

        header.appendChild(badge);
        header.appendChild(info);
        header.appendChild(conf);
        card.appendChild(header);

        // Items table (only if items exist)
        if (items.length > 0) {
            const itemsDiv = document.createElement('div');
            itemsDiv.className = 'page-card-items';

            let tableHtml = '<table><thead><tr><th>Product / SKU</th><th>Qty</th></tr></thead><tbody>';
            items.forEach(item => {
                tableHtml += `<tr><td>${escapeHtml(item.variant || item.name || '-')}</td><td>${item.quantity || 1}</td></tr>`;
            });
            tableHtml += '</tbody></table>';
            itemsDiv.innerHTML = tableHtml;
            card.appendChild(itemsDiv);
        } else if (pr.is_empty) {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'page-empty-badge';
            emptyDiv.textContent = 'Empty or unreadable page';
            card.appendChild(emptyDiv);
        }

        pageResultsList.appendChild(card);
    }
}

function selectPage(pageNum) {
    currentPage = pageNum;

    // Update page indicator
    pageIndicator.textContent = `Page ${pageNum} / ${totalPages}`;

    // Highlight active card
    document.querySelectorAll('.page-result-card').forEach(c => {
        c.classList.toggle('active', parseInt(c.dataset.page) === pageNum);
    });

    // Scroll active card into view
    const activeCard = document.querySelector('.page-result-card.active');
    if (activeCard) activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Load page image
    if (currentJobId) {
        previewImg.src = `/page-image/${currentJobId}/${pageNum}`;
    }

    // Reset zoom
    zoom = 100;
    previewImg.style.transform = `scale(1)`;
    zoomLevel.textContent = '100%';
}

// ── Page Navigation ──────────────────────────────────────────
document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (currentPage > 1) selectPage(currentPage - 1);
});
document.getElementById('btn-next-page').addEventListener('click', () => {
    if (currentPage < totalPages) selectPage(currentPage + 1);
});

// Keyboard navigation
document.addEventListener('keydown', (e) => {
    if (resultsSection.classList.contains('hidden')) return;
    if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); if (currentPage > 1) selectPage(currentPage - 1); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); if (currentPage < totalPages) selectPage(currentPage + 1); }
});

// ── Zoom Controls ────────────────────────────────────────────
document.getElementById('btn-zoom-in').addEventListener('click', () => {
    zoom = Math.min(zoom + 25, 300);
    previewImg.style.transform = `scale(${zoom / 100})`;
    zoomLevel.textContent = zoom + '%';
});
document.getElementById('btn-zoom-out').addEventListener('click', () => {
    zoom = Math.max(zoom - 25, 50);
    previewImg.style.transform = `scale(${zoom / 100})`;
    zoomLevel.textContent = zoom + '%';
});

// ── Resizable Divider ────────────────────────────────────────
const splitDivider = document.getElementById('split-divider');
const splitLeft = document.getElementById('split-left');
let isResizing = false;

splitDivider.addEventListener('mousedown', (e) => { isResizing = true; e.preventDefault(); });
document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const splitView = document.getElementById('split-view');
    const rect = splitView.getBoundingClientRect();
    const newWidth = Math.max(250, Math.min(e.clientX - rect.left, rect.width - 250));
    splitLeft.style.width = newWidth + 'px';
});
document.addEventListener('mouseup', () => { isResizing = false; });

// ── Download & New ───────────────────────────────────────────
document.getElementById('btn-download').addEventListener('click', () => {
    if (currentJobId) window.location.href = `/download/${currentJobId}`;
});
document.getElementById('btn-new').addEventListener('click', resetUI);
document.getElementById('btn-retry')?.addEventListener('click', resetUI);

// ── Section Visibility ───────────────────────────────────────
function showSection(section) {
    uploadSection.classList.add('hidden');
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    errorSection.classList.add('hidden');

    if (section === 'upload') uploadSection.classList.remove('hidden');
    if (section === 'progress') progressSection.classList.remove('hidden');
    if (section === 'results') resultsSection.classList.remove('hidden');
    if (section === 'error') errorSection.classList.remove('hidden');
}

function showError(message) {
    document.getElementById('error-message').textContent = message;
    showSection('error');
}

function resetUI() {
    selectedFile = null;
    currentJobId = null;
    currentPage = 1;
    totalPages = 1;
    resultData = null;
    zoom = 100;
    fileInput.value = '';
    fileInfo.style.display = 'none';
    btnExtract.disabled = true;
    progressBar.style.width = '0%';
    progressPages.textContent = 'Page 0 / 0';
    progressPct.textContent = '0%';
    pageResultsList.innerHTML = '';
    previewImg.src = '';
    showSection('upload');
}

// ── Utilities ────────────────────────────────────────────────
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function escapeHtml(text) {
    const el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast' + (type === 'error' ? ' error' : '');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
