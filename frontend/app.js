const queryForm = document.querySelector('#queryForm');
const processingScreen = document.querySelector('#processingScreen');
const deliveryScreen = document.querySelector('#deliveryScreen');
const errorScreen = document.querySelector('#errorScreen');
const liveConsole = document.querySelector('#liveConsole');
const resultsBody = document.querySelector('#resultsBody');
const extractionSummary = document.querySelector('#extractionSummary');
const metrics = document.querySelector('#metrics');
const emptyState = document.querySelector('#emptyState');
const downloadButton = document.querySelector('#downloadBtn');
const abortButton = document.querySelector('#cancelBtn');
const tableSearch = document.querySelector('#tableSearch');
const providerFilter = document.querySelector('#providerFilter');
const remoteFilter = document.querySelector('#remoteFilter');
const employmentFilter = document.querySelector('#employmentFilter');
const clearFiltersButton = document.querySelector('#clearFiltersBtn');
const filterSummary = document.querySelector('#filterSummary');
let activeRequest = null;
let currentResults = [];

/** Normalize provider fields and recover common metadata from snippet-only results. */
function normalizeJob(job) {
    const rawTitle = job.title || 'Untitled role';
    const labels = ['Location', 'Employment Type', 'Job Type', 'Location Type'];
    const labelPattern = new RegExp(`(?:${labels.join('|')})\\s*[.:]\\s*`, 'gi');
    const matches = [...rawTitle.matchAll(labelPattern)];
    const details = {};

    matches.forEach((match, index) => {
        const lowerLabel = match[0].toLowerCase();
        const label = lowerLabel.startsWith('employment') || lowerLabel.startsWith('job type') ? 'employmentType' : lowerLabel.startsWith('location type') ? 'locationType' : 'location';
        const nextStart = matches[index + 1]?.index ?? rawTitle.length;
        details[label] = rawTitle.slice(match.index + match[0].length, nextStart).replace(/\.{3,}$/, '').trim();
    });

    const title = matches.length ? rawTitle.slice(0, matches[0].index).replace(/[.\s]+$/, '').trim() : rawTitle;
    const location = job.location || details.location || 'Unknown';
    const rawWorkModel = job.work_model || details.locationType || '';
    const workModelText = `${rawWorkModel} ${location} ${rawTitle}`.toLowerCase();
    const workModel = job.is_remote === true || /remote|work from home/.test(workModelText) ? 'Remote' : /hybrid/.test(workModelText) ? 'Hybrid' : job.is_remote === false || /in.?person|on.?site|onsite|office/.test(workModelText) ? 'In-person' : 'Unknown';
    const rawJobType = job.employment_type || details.employmentType || '';
    const jobTypeText = rawJobType.toLowerCase().replace(/[- ]/g, '_');
    const jobType = /intern/.test(jobTypeText) ? 'Internship' : /part/.test(jobTypeText) ? 'Part time' : /contract/.test(jobTypeText) ? 'Contract' : /full/.test(jobTypeText) ? 'Full time' : 'Unknown';
    const postedDate = job.posted_at ? new Date(job.posted_at).toISOString().slice(0, 10) : 'Date unavailable';
    return { ...job, displayTitle: title || rawTitle, displayLocation: location, displayEmployment: jobType, displayLocationType: workModel, displayPostedDate: postedDate };
}

function normalizedResults() {
    return currentResults.map(normalizeJob);
}

function filteredResults() {
    const searchTerm = tableSearch.value.trim().toLowerCase();
    return normalizedResults().filter((job) => {
        const searchable = [job.displayTitle, job.company, job.displayLocation, job.displayEmployment, job.displayLocationType, job.displayPostedDate, job.provider].join(' ').toLowerCase();
        const matchesSearch = !searchTerm || searchable.includes(searchTerm);
        const matchesProvider = !providerFilter.value || job.provider === providerFilter.value;
        const matchesRemote = !remoteFilter.value || (remoteFilter.value === 'remote' ? job.displayLocationType.toLowerCase().includes('remote') : !job.displayLocationType.toLowerCase().includes('remote'));
        const matchesEmployment = !employmentFilter.value || job.displayEmployment === employmentFilter.value;
        return matchesSearch && matchesProvider && matchesRemote && matchesEmployment;
    });
}

function populateFilterOptions() {
    const providers = [...new Set(normalizedResults().map((job) => job.provider).filter(Boolean))].sort();
    const employmentTypes = [...new Set(normalizedResults().map((job) => job.displayEmployment).filter((value) => value && value !== 'Not specified'))].sort();
    providerFilter.replaceChildren(new Option('All providers', ''), ...providers.map((value) => new Option(value, value)));
    employmentFilter.replaceChildren(new Option('All types', ''), ...employmentTypes.map((value) => new Option(value, value)));
}

/** Convert a streamed JobListing into the columns used by the downloadable CSV. */
function csvValue(value) {
    const escaped = String(value ?? '').replaceAll('"', '""');
    return `"${escaped}"`;
}

function downloadCsv() {
    const header = ['Job title', 'Company', 'Location', 'Job type', 'Work model', 'Posted date', 'Provider', 'Apply URL'];
    const rows = filteredResults().map((job) => [job.displayTitle, job.company, job.displayLocation, job.displayEmployment, job.displayLocationType, job.displayPostedDate, job.provider, job.apply_url]);
    const csv = [header, ...rows].map((row) => row.map(csvValue).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${document.querySelector('#keywords').value.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'bottom-pot'}-results.csv`;
    link.click();
    URL.revokeObjectURL(url);
}

function renderResults() {
    resultsBody.replaceChildren();
    const visibleResults = filteredResults();
    emptyState.classList.toggle('hidden', visibleResults.length !== 0);
    filterSummary.textContent = currentResults.length === visibleResults.length ? `${currentResults.length} result${currentResults.length === 1 ? '' : 's'}` : `Showing ${visibleResults.length} of ${currentResults.length} results`;
    visibleResults.forEach((job) => {
        const row = document.createElement('tr');
        [job.displayTitle, job.company, job.displayLocation, job.displayEmployment, job.displayLocationType, job.displayPostedDate, job.provider].forEach((value) => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });
        const actionCell = document.createElement('td');
        const link = document.createElement('a');
        link.href = job.apply_url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Apply ->';
        actionCell.appendChild(link);
        row.appendChild(actionCell);
        resultsBody.appendChild(row);
    });
}

function renderMetrics(done) {
    const items = [['Results', done.total], ['Search time', `${done.search_time_ms} ms`], ['Providers', done.providers_searched.length], ['Serper queries', done.serper_queries_used]];
    metrics.replaceChildren(...items.map(([label, value]) => {
        const element = document.createElement('div');
        element.className = 'metric';
        const valueElement = document.createElement('strong');
        valueElement.textContent = value;
        const labelElement = document.createElement('span');
        labelElement.textContent = label;
        element.append(valueElement, labelElement);
        return element;
    }));
}

function showError(message) {
    processingScreen.classList.add('hidden');
    queryForm.classList.remove('hidden');
    errorScreen.classList.remove('hidden');
    document.querySelector('#errorMessage').textContent = message;
}

function resetView() {
    activeRequest?.abort();
    activeRequest = null;
    currentResults = [];
    tableSearch.value = '';
    providerFilter.replaceChildren(new Option('All providers', ''));
    employmentFilter.replaceChildren(new Option('All types', ''));
    remoteFilter.value = '';
    filterSummary.textContent = '';
    queryForm.reset();
    queryForm.classList.remove('hidden');
    processingScreen.classList.add('hidden');
    deliveryScreen.classList.add('hidden');
    errorScreen.classList.add('hidden');
}

/** Read FastAPI's named SSE events from a fetch response without buffering the search. */
async function streamSearch(url) {
    const response = await fetch(url, { signal: activeRequest.signal, headers: { Accept: 'text/event-stream' } });
    if (!response.ok || !response.body) throw new Error(`The search service returned HTTP ${response.status}.`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let eventName = '';
    let eventData = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
            if (line.startsWith('event:')) eventName = line.slice(6).trim();
            if (line.startsWith('data:')) eventData += line.slice(5).trim();
            if (line === '' && eventName && eventData) {
                const payload = JSON.parse(eventData);
                if (eventName === 'results') {
                    currentResults.push(...payload.batch);
                    liveConsole.textContent = `Received ${currentResults.length} result${currentResults.length === 1 ? '' : 's'}...`;
                    populateFilterOptions();
                    renderResults();
                } else if (eventName === 'done') {
                    renderMetrics(payload);
                    extractionSummary.textContent = payload.cached ? 'Loaded from the recent search cache.' : 'Fresh results compiled from the selected ATS platforms.';
                } else if (eventName === 'error') throw new Error(payload.message);
                eventName = '';
                eventData = '';
            }
        }
    }
}

queryForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    currentResults = [];
    queryForm.classList.add('hidden');
    errorScreen.classList.add('hidden');
    deliveryScreen.classList.add('hidden');
    processingScreen.classList.remove('hidden');
    activeRequest = new AbortController();
    const params = new URLSearchParams({ q: document.querySelector('#keywords').value.trim(), days_back: document.querySelector('#postAge').value, include_nigerian: document.querySelector('#includeNigerian').checked });
    const location = document.querySelector('#location').value.trim();
    const workModel = document.querySelector('#workModel').value;
    if (location) params.set('location', location);
    if (workModel !== 'any') params.set('remote', workModel === 'remote');
    try {
        await streamSearch(`/search?${params}`);
        populateFilterOptions();
        processingScreen.classList.add('hidden');
        deliveryScreen.classList.remove('hidden');
        renderResults();
    } catch (error) {
        if (error.name !== 'AbortError') showError(error.message);
    } finally {
        activeRequest = null;
    }
});

abortButton.addEventListener('click', resetView);
document.querySelector('#resetBtn').addEventListener('click', resetView);
document.querySelector('#errorResetBtn').addEventListener('click', resetView);
downloadButton.addEventListener('click', downloadCsv);
[tableSearch, providerFilter, remoteFilter, employmentFilter].forEach((control) => control.addEventListener('input', renderResults));
clearFiltersButton.addEventListener('click', () => {
    tableSearch.value = '';
    providerFilter.value = '';
    remoteFilter.value = '';
    employmentFilter.value = '';
    renderResults();
});