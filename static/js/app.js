/**
 * APP — Main orchestration: ties upload, progress, results together.
 * Handles section visibility and the upload→process→results flow.
 */

const uploadSection = document.getElementById('upload-section');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const errorSection = document.getElementById('error-section');

let currentJobId = null;

// ── Start Extraction ─────────────────────────────────────────
btnExtract.addEventListener('click', startExtraction);

async function startExtraction() {
    if (!selectedFile) return;
    btnExtract.disabled = true;
    showSection('progress');

    const formData = new FormData();
    formData.append('pdf', selectedFile);
    formData.append('courier', selectedCourier);

    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.error || 'Upload failed');
            return;
        }

        currentJobId = data.job_id;
        listenForProgress(currentJobId);
    } catch (err) {
        showError('Network error: ' + err.message);
    }
}

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

// ── Download & New ───────────────────────────────────────────
document.getElementById('btn-download').addEventListener('click', () => {
    if (currentJobId) window.location.href = `/download-excel/${currentJobId}`;
});

document.getElementById('btn-new').addEventListener('click', resetUI);
document.getElementById('btn-retry')?.addEventListener('click', resetUI);

function resetUI() {
    selectedFile = null;
    currentJobId = null;
    selectedCourier = 'jnt';
    document.querySelectorAll('.courier-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-courier-jnt').classList.add('active');
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
