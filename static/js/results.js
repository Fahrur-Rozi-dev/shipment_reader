/**
 * RESULTS — Split-view: page cards (left) + PDF preview (right)
 * Only edit THIS file when changing results UI behavior.
 */

const pageResultsList = document.getElementById('page-results-list');
const pageIndicator = document.getElementById('page-indicator');
const previewImg = document.getElementById('page-preview-img');
const zoomLevelEl = document.getElementById('zoom-level');

let currentPage = 1;
let totalPages = 1;
let resultData = null;
let zoom = 75;  // default zoom for PDF preview

// ── Show Results ─────────────────────────────────────────────
function showResults(result) {
    resultData = result;
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

    // Build page cards
    buildPageCards(result);
    selectPage(1);
}

// ── Build Page Cards ─────────────────────────────────────────
function buildPageCards(result) {
    pageResultsList.innerHTML = '';
    const pageResults = result.page_results || [];
    const shipments = result.shipments || [];

    // Map page → shipment
    const pageShipmentMap = {};
    shipments.forEach(s => {
        (s.pages || []).forEach(p => { pageShipmentMap[p] = s; });
    });

    for (let i = 0; i < (result.total_pages || 0); i++) {
        const pageNum = i + 1;
        const pr = pageResults[i] || {};
        const shipment = pageShipmentMap[pageNum];

        const card = document.createElement('div');
        card.className = 'page-result-card';
        card.dataset.page = pageNum;
        card.addEventListener('click', () => selectPage(pageNum));

        // Header row
        const header = document.createElement('div');
        header.className = 'page-card-header';

        const badge = document.createElement('div');
        badge.className = 'page-badge';
        badge.textContent = pageNum;

        const info = document.createElement('div');
        info.className = 'page-card-info';

        // Tracking number
        const trackingDiv = document.createElement('div');
        const trackingNum = shipment ? shipment.tracking_number : (pr.tracking_number || '');
        if (trackingNum) {
            trackingDiv.className = 'page-card-tracking';
            trackingDiv.textContent = trackingNum;
        } else {
            trackingDiv.className = 'page-card-tracking empty';
            trackingDiv.textContent = pr.is_empty ? '(empty page)' : '(no tracking)';
        }

        // Meta line
        const meta = document.createElement('div');
        meta.className = 'page-card-meta';
        const items = shipment ? shipment.items : (pr.items || []);
        const totalQty = items.reduce((sum, it) => sum + (it.quantity || 1), 0);
        meta.textContent = items.length > 0
            ? `${items.length} item${items.length > 1 ? 's' : ''} · Qty: ${totalQty}`
            : 'No items detected';

        info.appendChild(trackingDiv);
        info.appendChild(meta);

        header.appendChild(badge);
        header.appendChild(info);
        card.appendChild(header);

        // Items table
        if (items.length > 0) {
            const itemsDiv = document.createElement('div');
            itemsDiv.className = 'page-card-items';
            let html = '<table><thead><tr><th>Product / SKU</th><th>Qty</th></tr></thead><tbody>';
            items.forEach(item => {
                html += `<tr><td>${escapeHtml(item.variant || item.name || '-')}</td><td>${item.quantity || 1}</td></tr>`;
            });
            html += '</tbody></table>';
            itemsDiv.innerHTML = html;
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

// ── Select Page ──────────────────────────────────────────────
function selectPage(pageNum) {
    currentPage = pageNum;
    pageIndicator.textContent = `Page ${pageNum} / ${totalPages}`;

    // Highlight active card
    document.querySelectorAll('.page-result-card').forEach(c => {
        c.classList.toggle('active', parseInt(c.dataset.page) === pageNum);
    });

    // Scroll into view
    const activeCard = document.querySelector('.page-result-card.active');
    if (activeCard) activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Load preview image
    if (currentJobId) {
        previewImg.src = `/page-image/${currentJobId}/${pageNum}`;
    }

    // Reset zoom to default
    zoom = 75;
    previewImg.style.transform = `scale(${zoom / 100})`;
    zoomLevelEl.textContent = zoom + '%';
}

// ── Page Navigation ──────────────────────────────────────────
document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (currentPage > 1) selectPage(currentPage - 1);
});
document.getElementById('btn-next-page').addEventListener('click', () => {
    if (currentPage < totalPages) selectPage(currentPage + 1);
});

// Keyboard navigation (arrow keys)
document.addEventListener('keydown', (e) => {
    const resultsSection = document.getElementById('results-section');
    if (resultsSection.classList.contains('hidden')) return;
    if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        if (currentPage > 1) selectPage(currentPage - 1);
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        if (currentPage < totalPages) selectPage(currentPage + 1);
    }
});

// ── Zoom Controls ────────────────────────────────────────────
document.getElementById('btn-zoom-in').addEventListener('click', () => {
    zoom = Math.min(zoom + 25, 300);
    previewImg.style.transform = `scale(${zoom / 100})`;
    zoomLevelEl.textContent = zoom + '%';
});
document.getElementById('btn-zoom-out').addEventListener('click', () => {
    zoom = Math.max(zoom - 25, 50);
    previewImg.style.transform = `scale(${zoom / 100})`;
    zoomLevelEl.textContent = zoom + '%';
});

// ── Resizable Divider ────────────────────────────────────────
const splitDivider = document.getElementById('split-divider');
const splitLeft = document.getElementById('split-left');
let isResizing = false;

splitDivider.addEventListener('mousedown', (e) => {
    isResizing = true; e.preventDefault();
});
document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const splitView = document.getElementById('split-view');
    const rect = splitView.getBoundingClientRect();
    const newWidth = Math.max(250, Math.min(e.clientX - rect.left, rect.width - 250));
    splitLeft.style.width = newWidth + 'px';
});
document.addEventListener('mouseup', () => { isResizing = false; });

// ── Utilities ────────────────────────────────────────────────
function escapeHtml(text) {
    const el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
}
