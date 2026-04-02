/**
 * SE ContentEdge Tools — Frontend Application
 * Three-tool UI: Create Archiving Policies, Load Files, Migrate.
 */

// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════
const state = {
    activeTool: 'mrc',

    // Tool 1: Create Policy
    cp: {
        currentStep: 1,
        selectedFile: null,
        isASA: false,
        fileData: null,
        currentPage: 0,
        fields: [],
        fieldIdCounter: 0,
        extractionResults: null,
        selectedFolder: null,
        sectionFields: [],
        versionField: null,
        activeFieldId: null,
    },

    // Tool 2: MobiusRemoteCLI
    mrc: {
        selectedRepo: null,       // 'source' or 'target'
        selectedWorker: null,
        selectedOp: null,         // 'adelete', 'acreate', 'vdrdbxml'
        reposStatus: {},
        workers: [],
        // adelete-specific
        adeleteCcList: [],
        adeletePlan: [],          // [{cc, command}]
        adeleteTemplate: '',
        adeleteRepoConfig: {},
        // acreate-specific
        acreateTemplate: '',
        acreateRepoConfig: {},
        acreateCcList: [],
        acreatePolicies: [],
        acreateSelectedCC: null,
        acreateSelectedPolicy: null,
        acreateSelectedFolder: null,
        acreateFolderFiles: [],
        acreatePlan: [],          // [{file, command}]
        acreateMode: 'policy',    // 'policy' or 'list'
        acreateListTemplate: '',
        acreateListSelectedFolder: null,
        acreateListFilter: '*.lst',
        acreateListFolderFiles: [],
        // vdrdbxml-specific
        vdrdbxmlTemplate: '',
        vdrdbxmlMode: 'all',
        vdrdbxmlDir: 'export-import',
        vdrdbxmlCcList: [],
        vdrdbxmlIdxList: [],
        vdrdbxmlIgList: [],
        vdrdbxmlPolList: [],
        vdrdbxmlPlanSteps: [],
        vdrdbxmlXmlPreview: '',
        vdrdbxmlImportFile: null,
        vdrdbxmlImportFolder: null,
    },

    // Tool 3: Migrate
    mig: {
        currentStep: 1,
        mode: 'all',              // 'all' or 'specific'
        selectedWorker: null,
        vdrdbxmlTemplate: '',
        ccItems: [],
        idxItems: [],
        igItems: [],
        polItems: [],
        planSteps: [],            // [{repo, operation, command}]
        xmlPreview: '',
    },

    // Tool 3b: Remove Definitions
    rd: {
        currentStep: 1,
        selectedWorker: null,
        selectedRepo: 'target',
        ccItems: [],
        idxItems: [],
        igItems: [],
        polItems: [],
        planSteps: [],
    },

    // Tool 4: Workers
    wk: {
        currentStep: 1,
        workers: [],
        selectedWorker: null,
        planSteps: [],
        liveLogTimer: null,
    },
};

// ═══════════════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════════════
const API = {
    async get(url) {
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },
    async post(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },
};

function buildAgentContextHint() {
    const toolNames = {
        cp: 'CreatePolicy',
        'create-policy': 'CreatePolicy',
        mrc: 'MobiusRemoteCLI',
        mobiusremotecli: 'MobiusRemoteCLI',
        mig: 'Migrate',
        migrate: 'Migrate',
        rd: 'RemoveDefinitions',
        'remove-defs': 'RemoveDefinitions',
        workers: 'Workers',
    };

    const resolveToolId = () => {
        const raw = (state.activeTool || '').toString().trim().toLowerCase();
        if (raw && toolNames[raw]) return raw;

        // If MRC context is populated, treat tool as MobiusRemoteCLI even if
        // activeTool contains an unexpected value from the UI state.
        if (state.mrc?.selectedOp || state.mrc?.selectedRepo || state.mrc?.selectedWorker) {
            return 'mrc';
        }
        return raw || 'unknown';
    };

    const getMrcCommandHint = () => {
        const operation = state.mrc?.selectedOp;
        if (!operation) return null;

        const fieldIds = {
            adelete: 'mrc-adelete-cmd-template',
            acreate: 'mrc-acreate-cmd-template',
            vdrdbxml: 'mrc-vdr-cmd-template',
        };

        const fieldId = fieldIds[operation];
        const raw = fieldId ? document.getElementById(fieldId)?.value : '';
        if (raw && raw.trim()) return raw.replace(/\s+/g, ' ').trim();

        const fallbackByOp = {
            adelete: state.mrc?.adeleteTemplate,
            acreate: state.mrc?.acreateTemplate,
            vdrdbxml: state.mrc?.vdrdbxmlTemplate,
        };
        const fallback = fallbackByOp[operation] || '';
        if (fallback && fallback.trim()) return fallback.replace(/\s+/g, ' ').trim();

        if (!raw) return null;

        return raw.replace(/\s+/g, ' ').trim();
    };

    const toolId = resolveToolId();
    const parts = [];
    parts.push(`tool=${toolNames[toolId] || state.activeTool || 'unknown'}`);
    if (state.mrc?.selectedRepo) parts.push(`repo=${state.mrc.selectedRepo.toUpperCase()}`);
    if (state.mrc?.selectedWorker) parts.push(`worker=${state.mrc.selectedWorker}`);
    if (state.mrc?.selectedOp) parts.push(`operation=${state.mrc.selectedOp}`);
    if (toolId === 'mrc') {
        const command = getMrcCommandHint();
        if (command) parts.push(`command=${command}`);
    }
    return parts.join(' | ');
}

async function initGlobalAgentShortcut() {
    const shortcuts = Array.from(document.querySelectorAll('[data-agent-shortcut="true"]'));
    if (!shortcuts.length) return;

    const setAgentShortcutVisibility = (visible) => {
        shortcuts.forEach((el) => {
            // Keep layout clean by fully removing inactive shortcut elements.
            el.style.display = visible ? '' : 'none';
        });
    };

    let chatUrl = `${window.location.protocol}//${window.location.hostname}:3001`;
    let agentApiUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
    try {
        const info = await API.get('/api/agent/info');
        const enabled = !!info?.enabled;
        if (!enabled) {
            setAgentShortcutVisibility(false);
            return;
        }
        setAgentShortcutVisibility(true);
        if (info?.enabled && info?.anythingllm_port) {
            chatUrl = `${window.location.protocol}//${window.location.hostname}:${info.anythingllm_port}`;
        }
        if (info?.enabled && info?.agent_api_port) {
            agentApiUrl = `${window.location.protocol}//${window.location.hostname}:${info.agent_api_port}`;
        }
    } catch (_) {
        // If status cannot be validated, hide shortcut to avoid broken UX.
        setAgentShortcutVisibility(false);
        return;
    }

    const openAgentChat = (ev) => {
        if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
        const hint = buildAgentContextHint();
        showToast(`Opening Agent Chat (${hint})`, 'info');
        const backPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        const bridgeUrl = `/agent_chat.html?chat=${encodeURIComponent(chatUrl)}&api=${encodeURIComponent(agentApiUrl)}&back=${encodeURIComponent(backPath)}&ctx=${encodeURIComponent(hint)}`;
        window.location.href = bridgeUrl;
    };

    shortcuts.forEach((el) => {
        el.addEventListener('click', openAgentChat);
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// TOAST
// ═══════════════════════════════════════════════════════════════════════════
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span class="material-icons-outlined" style="font-size:18px">
        ${type === 'error' ? 'error' : type === 'success' ? 'check_circle' : type === 'warning' ? 'warning' : 'info'}
    </span>${escapeHtml(message)}`;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 4000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONFIRMATION MODAL
// ═══════════════════════════════════════════════════════════════════════════
function confirmDialog(title, body) {
    return new Promise((resolve) => {
        document.getElementById('confirm-modal-title').textContent = title;
        document.getElementById('confirm-modal-body').innerHTML = body;
        const modal = document.getElementById('confirm-modal');
        modal.style.display = 'flex';

        const ok = document.getElementById('confirm-modal-ok');
        const cancel = document.getElementById('confirm-modal-cancel');

        function cleanup() {
            modal.style.display = 'none';
            ok.replaceWith(ok.cloneNode(true));
            cancel.replaceWith(cancel.cloneNode(true));
        }

        document.getElementById('confirm-modal-ok').addEventListener('click', () => { cleanup(); resolve(true); });
        document.getElementById('confirm-modal-cancel').addEventListener('click', () => { cleanup(); resolve(false); });
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// REPO INFO BAR
// ═══════════════════════════════════════════════════════════════════════════
async function loadRepoInfoBar() {
    try {
        const data = await API.get('/api/mrc/repos-status');
        const srcUrl = document.getElementById('repo-info-source-url');
        const srcName = document.getElementById('repo-info-source-name');
        const tgtUrl = document.getElementById('repo-info-target-url');
        const tgtName = document.getElementById('repo-info-target-name');
        if (data.source?.active) {
            srcUrl.textContent = data.source.url;
            srcName.textContent = data.source.name ? `(${data.source.name})` : '';
        } else {
            srcUrl.textContent = 'Not configured';
            srcName.textContent = '';
        }
        if (data.target?.active) {
            tgtUrl.textContent = data.target.url;
            tgtName.textContent = data.target.name ? `(${data.target.name})` : '';
        } else {
            tgtUrl.textContent = 'Not configured';
            tgtName.textContent = '';
        }
    } catch (e) {
        // silently ignore
    }
}

/**
 * Toggle .has-value class on select elements so CSS can highlight them.
 */
function bindSelectHighlight(selectId) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const update = () => el.classList.toggle('has-value', !!el.value);
    el.addEventListener('change', update);
    update(); // set initial state
}

// ═══════════════════════════════════════════════════════════════════════════
// TOOL SWITCHING
// ═══════════════════════════════════════════════════════════════════════════
function switchTool(toolId) {
    state.activeTool = toolId;
    document.querySelectorAll('.nav-link').forEach(el => {
        el.classList.toggle('active', el.dataset.tool === toolId);
    });
    document.querySelectorAll('.tool-container').forEach(el => {
        el.classList.toggle('active', el.id === `tool-${toolId}`);
    });

    // Stop live log when leaving workers tool
    if (toolId !== 'workers') {
        wkStopLiveLog();
    }

    // Initialize tool data on switch
    if (toolId === 'mrc') {
        mrcInit();
    }
    if (toolId === 'migrate') {
        migInit();
    }
    if (toolId === 'remove-defs') {
        rdLoadWorkers();
    }
    if (toolId === 'workers') {
        wkLoadWorkers();
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// GENERIC STEPPER (within a tool container)
// ═══════════════════════════════════════════════════════════════════════════
function goToToolStep(toolContainerId, prefix, step) {
    const container = document.getElementById(toolContainerId);
    if (!container) return;

    // Update step circles
    container.querySelectorAll('.step').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.classList.remove('active', 'completed');
        if (s === step) el.classList.add('active');
        else if (s < step) el.classList.add('completed');
    });
    container.querySelectorAll('.step-connector').forEach((el, i) => {
        el.classList.toggle('completed', i + 1 < step);
    });

    // Show/hide panels
    container.querySelectorAll('.step-panel').forEach(el => {
        el.classList.toggle('active', el.id === `${prefix}-step-${step}` || el.id === `step-${step}`);
    });
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  TOOL 1: CREATE ARCHIVING POLICIES                                      ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function cpGoToStep(step) {
    if (step < 1 || step > 5) return;
    if (step > state.cp.currentStep) {
        if (state.cp.currentStep === 1 && !cpValidateStep1()) return;
        if (state.cp.currentStep === 2 && !cpValidateStep2()) return;
        if (state.cp.currentStep === 3 && !cpValidateStep3()) return;
    }
    state.cp.currentStep = step;
    goToToolStep('tool-create-policy', '', step);
    if (step === 2) cpRenderExtractionTable();
    if (step === 3) cpRenderMappingStep();
    if (step === 4) cpRenderStep4();
    if (step === 5) cpRenderStep5();
}

// ── File operations ───────────────────────────────────────────────────────

async function cpLoadFolders() {
    try {
        const data = await API.get('/api/folders');
        const select = document.getElementById('cp-folder-select');
        const current = select.value;
        select.innerHTML = '<option value="">— Select a folder —</option>';
        for (const d of data.folders) {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = `${d.name} (${d.files_count} files)`;
            select.appendChild(opt);
        }
        if (current) select.value = current;
    } catch (e) {
        showToast('Failed to load folders: ' + e.message, 'error');
    }
}

async function cpLoadFileList(folder) {
    const select = document.getElementById('file-select');
    if (!folder) {
        select.innerHTML = '<option value="">— Select a folder first —</option>';
        state.cp.selectedFolder = null;
        return;
    }
    state.cp.selectedFolder = folder;
    try {
        const data = await API.get(`/api/folders/${encodeURIComponent(folder)}/files`);
        select.innerHTML = '<option value="">— Select a file —</option>';
        for (const f of data.files) {
            const opt = document.createElement('option');
            opt.value = f.name;
            opt.textContent = `${f.name} (${(f.size / 1024).toFixed(1)} KB)`;
            select.appendChild(opt);
        }
    } catch (e) {
        showToast('Failed to load files: ' + e.message, 'error');
    }
}

async function cpSelectFile(filename) {
    if (!filename) { state.cp.selectedFile = null; state.cp.fileData = null; cpRenderFileViewer(); return; }
    const folder = state.cp.selectedFolder || 'tmp';
    try {
        const data = await API.get(`/api/folders/${encodeURIComponent(folder)}/files/${encodeURIComponent(filename)}/content`);
        state.cp.selectedFile = filename;
        state.cp.fileData = data;
        state.cp.currentPage = 0;
        cpRenderFileViewer();
        document.getElementById('page-nav').style.display = data.total_pages > 1 ? 'flex' : 'none';
        cpUpdatePageIndicator();
    } catch (e) {
        showToast('Failed to load file: ' + e.message, 'error');
    }
}

function cpRenderFileViewer() {
    const viewer = document.getElementById('file-viewer');
    const ruler = document.getElementById('column-ruler');
    const status = document.getElementById('viewer-status');

    if (!state.cp.fileData || !state.cp.fileData.pages.length) {
        viewer.innerHTML = `<div class="placeholder-text">
            <span class="material-icons-outlined" style="font-size:48px;opacity:0.3">insert_drive_file</span>
            <p>Select a file to preview</p></div>`;
        ruler.textContent = '';
        status.textContent = '';
        return;
    }

    const page = state.cp.fileData.pages[state.cp.currentPage];
    const lines = page.lines;
    const asaSkip = state.cp.isASA ? 2 : 0;
    let maxCols = 0;
    for (const l of lines) maxCols = Math.max(maxCols, l.length - asaSkip);
    maxCols = Math.max(maxCols, 120);

    let rulerText = '';
    for (let c = 1; c <= maxCols; c++) {
        if (c % 10 === 0) rulerText += String(c / 10 % 10);
        else if (c % 5 === 0) rulerText += '·';
        else rulerText += ' ';
    }
    ruler.textContent = rulerText;

    let html = '';
    for (let i = 0; i < lines.length; i++) {
        const lineNum = i + 1;
        const displayLine = asaSkip ? lines[i].substring(asaSkip) : lines[i];
        html += `<div class="file-line" data-line="${lineNum}">` +
            `<span class="file-line-number">${lineNum}</span>` +
            `<span class="file-line-content">${escapeHtml(displayLine) || ' '}</span></div>`;
    }
    viewer.innerHTML = html;
    cpRenderFieldHighlights();
    status.textContent = `Page ${state.cp.currentPage + 1} of ${state.cp.fileData.total_pages} · ${lines.length} lines · ${state.cp.selectedFile}`;
}

function cpRenderFieldHighlights() {
    document.querySelectorAll('.field-highlight').forEach(el => el.remove());
    if (!state.cp.fileData) return;
    const viewer = document.getElementById('file-viewer');
    for (const field of state.cp.fields) {
        if (!field.name || !field.line || !field.column) continue;
        const lineEl = viewer.querySelector(`.file-line[data-line="${field.line}"]`);
        if (!lineEl) continue;
        const contentEl = lineEl.querySelector('.file-line-content');
        if (!contentEl) continue;
        const charWidth = cpGetCharWidth(contentEl);
        const left = (field.column - 1) * charWidth;
        const width = field.length > 0 ? field.length * charWidth : 60;
        const isActive = field.id === state.cp.activeFieldId;
        const hl = document.createElement('div');
        hl.className = 'field-highlight' + (isActive ? ' active-highlight' : '');
        hl.style.left = (contentEl.offsetLeft + left) + 'px';
        hl.style.top = lineEl.offsetTop + 'px';
        hl.style.width = width + 'px';
        hl.style.height = lineEl.offsetHeight + 'px';
        hl.title = `${field.name}: line ${field.line}, col ${field.column}, len ${field.length || 'auto'}`;
        const label = document.createElement('span');
        label.className = 'field-highlight-label';
        label.textContent = field.name;
        hl.appendChild(label);
        viewer.appendChild(hl);
    }
}

let _charWidth = null;
function cpGetCharWidth(mono) {
    if (_charWidth) return _charWidth;
    const span = document.createElement('span');
    span.textContent = 'X';
    span.style.visibility = 'hidden';
    span.style.position = 'absolute';
    mono.appendChild(span);
    _charWidth = span.getBoundingClientRect().width;
    span.remove();
    return _charWidth;
}

function cpUpdatePageIndicator() {
    if (!state.cp.fileData) return;
    document.getElementById('page-indicator').textContent =
        `Page ${state.cp.currentPage + 1} / ${state.cp.fileData.total_pages}`;
}

// ── Field management ─────────────────────────────────────────────────────

function cpAddField(defaults = {}) {
    state.cp.fieldIdCounter++;
    state.cp.fields.push({
        id: state.cp.fieldIdCounter,
        name: defaults.name || '',
        type: defaults.type || 'Character',
        line: defaults.line || 1,
        column: defaults.column || 1,
        length: defaults.length || 0,
        format: defaults.format || '',
    });
    cpRenderFieldList();
}

function cpRemoveField(id) {
    state.cp.fields = state.cp.fields.filter(f => f.id !== id);
    cpRenderFieldList();
    cpRenderFieldHighlights();
}

function cpUpdateField(id, prop, value) {
    const field = state.cp.fields.find(f => f.id === id);
    if (!field) return;
    if (['line', 'column', 'length'].includes(prop)) field[prop] = parseInt(value) || 0;
    else field[prop] = value;
    if (prop === 'type') {
        field.format = '';
        field.length = 0;
        cpRenderFieldList();
    }
    if (prop === 'format' && field.type === 'Date') {
        field.length = cpDateFormatLen(value);
        cpRenderFieldList();
    }
    cpRenderFieldHighlights();
}

function cpDateFormatLen(fmt) {
    if (!fmt) return 0;
    return fmt.length;
}

const DATE_FORMATS = [
    'MM/DD/YY','MM/DD/YYYY','YY/MM/DD','YYYY/MM/DD','DD/MM/YY','DD/MM/YYYY',
    'MM-DD-YY','MM-DD-YYYY','YY-MM-DD','YYYY-MM-DD','DD-MM-YY','DD-MM-YYYY',
    'MMDDYY','MMDDYYYY','YYMMDD','YYYYMMDD','DDMMYY','DDMMYYYY',
    'MM.DD.YY','MM.DD.YYYY','YY.MM.DD','YYYY.MM.DD','DD.MM.YY','DD.MM.YYYY',
    'MMM/DD/YY','MMM/DD/YYYY','DD/MMM/YY','DD/MMM/YYYY',
    'MMM-DD-YY','MMM-DD-YYYY','DD-MMM-YY','DD-MMM-YYYY',
    'MMM DD,YY','MMM DD,YYYY','DD MMM,YY','DD MMM,YYYY',
    'MMMM DD,YY','MMMM DD,YYYY','DD MMMM,YY','DD MMMM,YYYY',
    'DD.MMM.YY','DD.MMM.YYYY','DDMMMYY','DDMMMYYYY',
    'DD MMM YY','DD MMM YYYY','DD MM YY','DD MM YYYY',
    'MM DD YY','MM DD YYYY','YY MM DD','YYYY MM DD',
    'MMM DD YY','MMM DD YYYY','MMMM DD YY','MMMM DD YYYY',
    'DD-MMM,YY','DD-MMM,YYYY','DD-MMMM,YY','DD-MMMM,YYYY',
];

const NUMERIC_FORMATS = [
    '-$#,###.##','-#,###.##$','$-#,###.##','$#,###.##-','#,###.##-$','#,###.##$-','#,###.##-','-#,###.##',
    '-$#.###,##','-#.###,##$','$-#.###,##','$#.###,##-','#.###,##-$','#.###,##$-','#.###,##-','-#.###,##',
    'CR$#,###.##','CR#,###.##$','$CR#,###.##','$#,###.##CR','#,###.##CR$','#,###.##$CR','#,###.##CR','CR#,###.##',
    'CR$#.###,##','CR#.###,##$','$CR#.###,##','$#.###,##CR','#.###,##CR$','#.###,##$CR','#.###,##CR','CR#.###,##',
    '($#,###.##)','(#,###.##$)','$(#,###.##)','(#,###.##)$','(#,###.##)',
    '($#.###,##)','(#.###,##$)','$(#.###,##)','(#.###,##)$','(#.###,##)',
    '-$####.##','-####.##$','$-####.##','$####.##-','####.##-$','####.##$-','####.##-','-####.##',
    '-$####,##','-####,##$','$-####,##','$####,##-','####,##-$','####,##$-','####,##-','-####,##',
    'CR$####.##','CR####.##$','$CR####.##','$####.##CR','####.##CR$','####.##$CR','####.##CR','CR####.##',
    'CR$####,##','CR####,##$','$CR####,##','$####,##CR','####,##CR$','####,##$CR','####,##CR','CR####,##',
    '($####.##)','(####.##$)','$(####.##)','(####.##)$','(####.##)',
    '($####,##)','(####,##$)','$(####,##)','(####,##)$','(####,##)',
    '-$#,###','-#,###$','$-#,###','$#,###-','#,###-$','#,###$-','#,###-','-#,###',
    '-$#.###','-#.###$','$-#.###','$#.###-','#.###-$','#.###$-','#.###-','-#.###',
    'CR$#,###','CR#,###$','$CR#,###','$#,###CR','#,###CR$','#,###$CR','#,###CR','CR#,###',
    'CR$#.###','CR#.###$','$CR#.###','$#.###CR','#.###CR$','#.###$CR','#.###CR','CR#.###',
    '($#,###)','(#,###$)','$(#,###)','(#,###)$','(#,###)',
    '($#.###)','(#.###$)','$(#.###)','(#.###)$','(#.###)',
    '-$####','-####$','$-####','$####-','####-$','####$-','####-','-####',
    '($####)','(####$)','$(####)','(####)$','(####)',
    'CR$####','CR####$','$CR####','$####CR','####CR$','####$CR','####CR','CR####',
];

function cpGetFormatOptions(type, currentFormat) {
    if (type === 'Character') return '<option value="">N/A</option>';
    const formats = type === 'Date' ? DATE_FORMATS : NUMERIC_FORMATS;
    let html = `<option value="" ${!currentFormat ? 'selected' : ''}>None</option>`;
    for (const fmt of formats) {
        const esc = escapeHtml(fmt);
        html += `<option value="${esc}" ${currentFormat === fmt ? 'selected' : ''}>${esc}</option>`;
    }
    return html;
}

function cpRenderFieldList() {
    const container = document.getElementById('field-list');
    if (state.cp.fields.length === 0) {
        container.innerHTML = `<div class="muted text-center" style="padding:20px">No fields defined. Click "Add Field" to start.</div>`;
        return;
    }
    container.innerHTML = state.cp.fields.map(f => {
        const isActive = state.cp.activeFieldId === f.id;
        const summary = f.name
            ? `${escapeHtml(f.type)} · Ln ${f.line}, Col ${f.column}, Len ${f.length || 'auto'}${f.format ? ' · ' + escapeHtml(f.format) : ''}`
            : 'Not configured';
        return `
        <div class="field-row${isActive ? ' active' : ''}" data-field-id="${f.id}">
            <div class="field-row-summary">
                <span class="field-summary-name">${escapeHtml(f.name) || '<em class="muted">unnamed</em>'}</span>
                <span class="field-summary-type">${escapeHtml(f.type)}</span>
                <span class="field-summary-detail">${summary}</span>
                <button class="btn btn-danger" title="Remove" data-remove-field="${f.id}">
                    <span class="material-icons-outlined" style="font-size:16px">close</span></button>
            </div>
            <div class="field-row-form">
                <div class="field-row-top">
                    <div class="field-input-group"><label>Name</label>
                        <input type="text" value="${escapeHtml(f.name)}" placeholder="FIELD_NAME"
                               data-field="${f.id}" data-prop="name" style="text-transform:uppercase"></div>
                    <button class="btn btn-danger field-remove" title="Remove" data-remove-field="${f.id}">
                        <span class="material-icons-outlined" style="font-size:18px">close</span></button>
                </div>
                <div class="field-row-mid">
                    <div class="field-input-group"><label>Type</label>
                        <select data-field="${f.id}" data-prop="type">
                            <option value="Character" ${f.type === 'Character' ? 'selected' : ''}>Character</option>
                            <option value="Numeric" ${f.type === 'Numeric' ? 'selected' : ''}>Numeric</option>
                            <option value="Date" ${f.type === 'Date' ? 'selected' : ''}>Date</option>
                        </select></div>
                </div>
                <div class="field-row-bottom">
                    <div class="field-input-group"><label>Line</label>
                        <input type="number" value="${f.line}" min="1" max="999" data-field="${f.id}" data-prop="line"></div>
                    <div class="field-input-group"><label>Col</label>
                        <input type="number" value="${f.column}" min="1" max="999" data-field="${f.id}" data-prop="column"></div>
                    <div class="field-input-group"><label>Len</label>
                        <input type="number" value="${f.length}" min="0" max="999" data-field="${f.id}" data-prop="length" placeholder="0=auto" ${f.type === 'Date' ? 'disabled style="background:var(--gray-100)"' : ''}></div>
                    <div class="field-input-group"><label>Format</label>
                        <select data-field="${f.id}" data-prop="format" ${f.type === 'Character' ? 'disabled' : ''}>
                            ${cpGetFormatOptions(f.type, f.format)}
                        </select></div>
                </div>
            </div>
        </div>`;
    }).join('');

    container.querySelectorAll('input, select').forEach(el => {
        const fieldId = parseInt(el.dataset.field);
        const prop = el.dataset.prop;
        if (!prop) return;
        el.addEventListener('change', () => {
            let val = el.value;
            if (prop === 'name') { val = val.toUpperCase().replace(/[^A-Z0-9_]/g, ''); el.value = val; }
            cpUpdateField(fieldId, prop, val);
        });
        el.addEventListener('input', () => {
            if (['line', 'column', 'length'].includes(prop)) cpUpdateField(fieldId, prop, el.value);
        });
    });
    container.querySelectorAll('[data-remove-field]').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); cpRemoveField(parseInt(btn.dataset.removeField)); });
    });

    // Click on field-row to expand/collapse (accordion style)
    container.querySelectorAll('.field-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('[data-remove-field]') || e.target.closest('input') || e.target.closest('select')) return;
            const id = parseInt(row.dataset.fieldId);
            state.cp.activeFieldId = (state.cp.activeFieldId === id) ? null : id;
            cpRenderFieldList();
            cpRenderFieldHighlights();
        });
    });
}

function cpValidateStep1() {
    if (!state.cp.selectedFile) { showToast('Please select a source file', 'error'); return false; }
    if (state.cp.fields.length === 0) { showToast('Please define at least one field', 'error'); return false; }
    for (const f of state.cp.fields) {
        if (!f.name) { showToast('All fields must have a name', 'error'); return false; }
        if (f.line < 1 || f.column < 1) { showToast(`Field "${f.name}": line and column must be >= 1`, 'error'); return false; }
    }
    const names = state.cp.fields.map(f => f.name);
    const dupes = names.filter((n, i) => names.indexOf(n) !== i);
    if (dupes.length) { showToast(`Duplicate field name: ${dupes[0]}`, 'error'); return false; }
    return true;
}

// ── Extract (Step 1 → 2) ─────────────────────────────────────────────────

async function cpExtractFields() {
    if (!cpValidateStep1()) return;
    const btn = document.getElementById('btn-step1-next');
    btn.classList.add('loading'); btn.disabled = true;
    try {
        const result = await API.post('/api/extract', {
            filename: state.cp.selectedFile,
            folder: state.cp.selectedFolder || 'tmp',
            fields: state.cp.fields.map(f => ({ name: f.name, line: f.line, column: f.column, length: f.length, format: f.format })),
        });
        state.cp.extractionResults = result;
        cpGoToStep(2);
    } catch (e) { showToast('Extraction failed: ' + e.message, 'error'); }
    finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ── Step 2: Verify ────────────────────────────────────────────────────────

function cpRenderExtractionTable() {
    if (!state.cp.extractionResults) return;
    const tbody = document.querySelector('#extraction-table tbody');
    tbody.innerHTML = '';
    for (const field of state.cp.extractionResults.fields) {
        const vals = field.values || [];
        const p1 = vals[0]?.value || '', p2 = vals[1]?.value || '', p3 = vals[2]?.value || '';
        const hasValues = p1 || p2 || p3;
        const allSame = p1 && p2 && p3 && p1 === p2 && p2 === p3;
        let statusHtml;
        if (!hasValues) statusHtml = '<span class="status-error"><span class="material-icons-outlined" style="font-size:16px">warning</span> Empty</span>';
        else if (allSame && !field.format) statusHtml = '<span class="status-warn"><span class="material-icons-outlined" style="font-size:16px">info</span> Same</span>';
        else statusHtml = '<span class="status-ok"><span class="material-icons-outlined" style="font-size:16px">check_circle</span> OK</span>';
        const posText = `line ${field.line}, col ${field.column}` + (field.length > 0 ? `, len ${field.length}` : '');
        const row = document.createElement('tr');
        row.innerHTML = `<td><strong>${escapeHtml(field.name)}</strong></td>
            <td style="font-size:0.8rem">${escapeHtml(posText)}</td>
            <td style="font-size:0.8rem">${escapeHtml(field.format || '—')}</td>
            <td><span class="value-cell">${escapeHtml(p1) || '—'}</span></td>
            <td><span class="value-cell">${escapeHtml(p2) || '—'}</span></td>
            <td><span class="value-cell">${escapeHtml(p3) || '—'}</span></td>
            <td>${statusHtml}</td>`;
        tbody.appendChild(row);
    }
}

function cpValidateStep2() {
    if (!state.cp.extractionResults) { showToast('No extraction results', 'error'); return false; }
    return true;
}

// ── Step 3: Mapping ───────────────────────────────────────────────────────

function cpRenderMappingStep() {
    if (!state.cp.extractionResults) return;
    const fields = state.cp.extractionResults.fields;
    const dateFieldNames = state.cp.fields.filter(f => f.type === 'Date').map(f => f.name);
    if (state.cp.versionField && !dateFieldNames.includes(state.cp.versionField)) {
        state.cp.versionField = null;
    }

    const sectionList = document.getElementById('section-field-list');
    sectionList.innerHTML = fields.map(f => {
        const p1 = f.values?.[0]?.value || '';
        const sel = state.cp.sectionFields.includes(f.name);
        return `<div class="mapping-item ${sel ? 'selected' : ''}" data-section-field="${escapeHtml(f.name)}">
            <span class="material-icons-outlined">${sel ? 'check_box' : 'check_box_outline_blank'}</span>
            <span class="mapping-item-name">${escapeHtml(f.name)}</span>
            <span class="mapping-item-value">${escapeHtml(p1)}</span></div>`;
    }).join('');

    const versionList = document.getElementById('version-field-list');
    const dateFields = fields.filter(f => dateFieldNames.includes(f.name));
    if (dateFields.length === 0) {
        versionList.innerHTML = '<div class="muted" style="padding:12px">No Date fields defined. Only Date fields can be used for VERSION.</div>';
    } else {
        versionList.innerHTML = dateFields.map(f => {
            const p1 = f.values?.[0]?.value || '';
            const sel = state.cp.versionField === f.name;
            return `<div class="mapping-item ${sel ? 'selected' : ''}" data-version-field="${escapeHtml(f.name)}">
                <span class="material-icons-outlined">${sel ? 'radio_button_checked' : 'radio_button_unchecked'}</span>
                <span class="mapping-item-name">${escapeHtml(f.name)}</span>
                <span class="mapping-item-value">${escapeHtml(p1)}</span></div>`;
        }).join('');
    }

    sectionList.querySelectorAll('.mapping-item').forEach(el => {
        el.addEventListener('click', () => {
            const name = el.dataset.sectionField;
            const idx = state.cp.sectionFields.indexOf(name);
            if (idx >= 0) state.cp.sectionFields.splice(idx, 1); else state.cp.sectionFields.push(name);
            cpRenderMappingStep();
        });
    });
    versionList.querySelectorAll('.mapping-item').forEach(el => {
        el.addEventListener('click', () => { state.cp.versionField = el.dataset.versionField; cpRenderMappingStep(); });
    });
    cpUpdateMappingPreviews();
}

function cpUpdateMappingPreviews() {
    const fields = state.cp.extractionResults?.fields || [];
    const sp = document.getElementById('section-preview');
    const vp = document.getElementById('version-preview');
    if (state.cp.sectionFields.length) {
        const parts = state.cp.sectionFields.map(n => fields.find(x => x.name === n)?.values?.[0]?.value || '?');
        sp.innerHTML = `<strong>SECTION</strong> = ${escapeHtml(state.cp.sectionFields.join(' + '))} &rarr; <code>${escapeHtml(parts.join(''))}</code>`;
    } else sp.innerHTML = '<span class="muted">Select at least one field for SECTION</span>';
    if (state.cp.versionField) {
        const val = fields.find(x => x.name === state.cp.versionField)?.values?.[0]?.value || '?';
        vp.innerHTML = `<strong>VERSION</strong> = ${escapeHtml(state.cp.versionField)} &rarr; <code>${escapeHtml(val)}</code>`;
    } else vp.innerHTML = '<span class="muted">Select a field for VERSION</span>';
}

function cpValidateStep3() {
    if (state.cp.sectionFields.length === 0) { showToast('Select at least one field for SECTION', 'error'); return false; }
    if (!state.cp.versionField) { showToast('Select a field for VERSION', 'error'); return false; }
    return true;
}

// ── Step 4: Name & Generate ───────────────────────────────────────────────

function cpRenderStep4() { cpUpdatePolicySummary(); }

function cpUpdatePolicySummary() {
    const box = document.getElementById('policy-summary');
    if (!state.cp.extractionResults) return;
    const fields = state.cp.extractionResults.fields;
    const sectionParts = state.cp.sectionFields.map(n => fields.find(x => x.name === n)?.values?.[0]?.value || '?');
    const vVal = fields.find(x => x.name === state.cp.versionField)?.values?.[0]?.value || '?';
    box.innerHTML = `
        <div class="summary-row"><span class="summary-label">Source File</span><span class="summary-value">${escapeHtml(state.cp.selectedFile || '—')}</span></div>
        <div class="summary-row"><span class="summary-label">Fields</span><span class="summary-value">${state.cp.fields.length} defined</span></div>
        <div class="summary-row"><span class="summary-label">SECTION</span><span class="summary-value">${escapeHtml(state.cp.sectionFields.join(' + '))} &rarr; ${escapeHtml(sectionParts.join(''))}</span></div>
        <div class="summary-row"><span class="summary-label">VERSION</span><span class="summary-value">${escapeHtml(state.cp.versionField || '—')} &rarr; ${escapeHtml(vVal)}</span></div>`;
}

async function cpGeneratePolicy() {
    const policyName = document.getElementById('policy-name').value.trim();
    const contentClass = document.getElementById('content-class').value.trim();
    if (!policyName) { showToast('Please enter a policy name', 'error'); return; }
    if (!/^[A-Za-z0-9_\-]+$/.test(policyName)) { showToast('Policy name: only letters, numbers, _ and -', 'error'); return; }

    const btn = document.getElementById('btn-generate');
    btn.classList.add('loading'); btn.disabled = true;
    try {
        const result = await API.post('/api/policies/generate', {
            policy_name: policyName,
            source_file: state.cp.selectedFile,
            source_folder: state.cp.selectedFolder || 'tmp',
            content_class: contentClass || 'UNKNOWN',
            replace_existing: false,
            fields: state.cp.fields.map(f => ({ name: f.name, line: f.line, column: f.column, length: f.length, format: f.format })),
            mapping: { section_fields: state.cp.sectionFields, version_field: state.cp.versionField },
        });
        const banner = document.getElementById('result-banner');
        banner.style.display = 'block'; banner.className = 'result-banner success';
        document.getElementById('result-icon').textContent = 'check_circle';
        document.getElementById('result-title').textContent = 'Policy Generated Successfully';
        document.getElementById('result-message').textContent =
            `Policy "${result.policy_name}" saved to ${result.output_file}. ${result.field_count} fields.`;
        showToast('Policy generated!', 'success');
        // Auto-advance to Publish step after short delay
        setTimeout(() => cpGoToStep(5), 1200);
    } catch (e) {
        const banner = document.getElementById('result-banner');
        banner.style.display = 'block'; banner.className = 'result-banner error';
        document.getElementById('result-icon').textContent = 'error';
        document.getElementById('result-title').textContent = 'Generation Failed';
        document.getElementById('result-message').textContent = e.message;
        showToast('Policy generation failed: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ── Step 5: Publish ───────────────────────────────────────────────────────

async function cpRenderStep5() {
    // Load repos
    try {
        const repoData = await API.get('/api/repos');
        const repoSel = document.getElementById('pub-repo-select');
        repoSel.innerHTML = repoData.repos.map(r =>
            `<option value="${r}">${r.toUpperCase()}</option>`
        ).join('');
    } catch (e) { /* keep default SOURCE */ }

    // Load generated policies
    await cpLoadGeneratedPolicies();
}

async function cpLoadGeneratedPolicies() {
    const select = document.getElementById('pub-policy-select');
    try {
        const data = await API.get('/api/policies/generated');
        if (data.policies.length === 0) {
            select.innerHTML = '<option value="">No generated policies found</option>';
        } else {
            select.innerHTML = data.policies.map(p =>
                `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} (${(p.size / 1024).toFixed(1)} KB)</option>`
            ).join('');
        }
    } catch (e) {
        select.innerHTML = '<option value="">Error loading policies</option>';
    }
}

async function cpPublishPolicy() {
    const policyName = document.getElementById('pub-policy-select').value;
    const repo = document.getElementById('pub-repo-select').value;
    if (!policyName) { showToast('Select a policy to publish', 'error'); return; }

    const statusDiv = document.getElementById('pub-status');
    const btn = document.getElementById('btn-publish');
    btn.classList.add('loading'); btn.disabled = true;
    statusDiv.innerHTML = '';

    try {
        // Check if policy already exists
        const check = await API.get(`/api/policies/exists?name=${encodeURIComponent(policyName)}&repo=${encodeURIComponent(repo)}`);
        if (check.exists) {
            const proceed = await confirmDialog(
                'Policy Already Exists',
                `<p>A policy named <strong>${escapeHtml(policyName)}</strong> already exists in <strong>${repo.toUpperCase()}</strong>.</p><p>You can go back to Step 4 and change the name, or cancel.</p>`
            );
            if (!proceed) {
                btn.classList.remove('loading'); btn.disabled = false;
                return;
            }
        }

        // Register the policy
        const result = await API.post('/api/policies/register', { policy_name: policyName, repo });
        const banner = document.getElementById('pub-result-banner');
        if (result.status === 'exists') {
            banner.style.display = 'block'; banner.className = 'result-banner error';
            document.getElementById('pub-result-icon').textContent = 'warning';
            document.getElementById('pub-result-title').textContent = 'Already Exists';
            document.getElementById('pub-result-message').textContent = result.message + ' Go back to Step 4 to change the name.';
        } else {
            banner.style.display = 'block'; banner.className = 'result-banner success';
            document.getElementById('pub-result-icon').textContent = 'check_circle';
            document.getElementById('pub-result-title').textContent = 'Published Successfully';
            document.getElementById('pub-result-message').textContent =
                `Policy "${policyName}" has been published to ${repo.toUpperCase()}.`;
            showToast(`Published to ${repo.toUpperCase()}!`, 'success');
        }
    } catch (e) {
        const banner = document.getElementById('pub-result-banner');
        banner.style.display = 'block'; banner.className = 'result-banner error';
        document.getElementById('pub-result-icon').textContent = 'error';
        document.getElementById('pub-result-title').textContent = 'Publish Failed';
        document.getElementById('pub-result-message').textContent = e.message;
        showToast('Publish failed: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  TOOL 2: MobiusRemoteCLI                                                ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

async function mrcInit() {
    await Promise.all([mrcLoadReposStatus(), mrcLoadWorkers(), mrcLoadAdeleteTemplate(), mrcLoadAcreateTemplate(), mrcLoadAcreateListTemplate(), mrcLoadVdrdbxmlTemplate()]);
}

async function mrcLoadReposStatus() {
    try {
        const data = await API.get('/api/mrc/repos-status');
        state.mrc.reposStatus = data;
        const srcBtn = document.getElementById('mrc-btn-source');
        const tgtBtn = document.getElementById('mrc-btn-target');
        srcBtn.disabled = !data.source?.active;
        tgtBtn.disabled = !data.target?.active;
        if (data.source?.active) srcBtn.title = data.source.url;
        else srcBtn.title = 'Not configured';
        if (data.target?.active) tgtBtn.title = data.target.url;
        else tgtBtn.title = 'Not configured';
        // If current selected repo became inactive, deselect
        if (state.mrc.selectedRepo === 'source' && !data.source?.active) mrcSelectRepo(null);
        if (state.mrc.selectedRepo === 'target' && !data.target?.active) mrcSelectRepo(null);
    } catch (e) { showToast('Failed to load repo status: ' + e.message, 'error'); }
}

async function mrcLoadWorkers() {
    try {
        const workers = await API.get('/api/workers');
        state.mrc.workers = workers;
        const select = document.getElementById('mrc-worker-select');
        const current = select.value;
        select.innerHTML = '<option value="">— Select worker —</option>';
        for (const w of workers) {
            if (!w.alive) continue;
            const opt = document.createElement('option');
            opt.value = w.worker;
            opt.textContent = `${w.worker} (${w.debug ? 'DEBUG' : 'LIVE'})`;
            select.appendChild(opt);
        }
        if (current) select.value = current;
        state.mrc.selectedWorker = select.value || null;
    } catch (e) { showToast('Failed to load workers: ' + e.message, 'error'); }
}

async function mrcLoadAdeleteTemplate() {
    try {
        const data = await API.get('/api/mrc/adelete-template');
        state.mrc.adeleteTemplate = data.template;
    } catch (e) {
        state.mrc.adeleteTemplate = 'adelete -s {REPO_NAME} -u {SERVER_USER} -r {CONTENT_CLASS} -c -n -y ALL -o';
    }
}

function mrcSelectRepo(repo) {
    state.mrc.selectedRepo = repo;
    document.getElementById('mrc-btn-source').classList.toggle('active', repo === 'source');
    document.getElementById('mrc-btn-target').classList.toggle('active', repo === 'target');
    // Load repo config for command template
    if (repo) mrcLoadRepoConfig(repo);
    // Reload content classes if adelete or acreate is active
    if (state.mrc.selectedOp === 'adelete' && repo) mrcAdeleteLoadCC();
    if (state.mrc.selectedOp === 'acreate' && repo) mrcAcreateLoadCC();
    if (state.mrc.selectedOp === 'vdrdbxml' && repo) mrcVdrLoadAllCategories();
    mrcUpdateAdeleteTemplate();
    mrcUpdateAcreateTemplate();
    mrcVdrUpdateTemplate();
    if (state.mrc.acreateMode === 'list') mrcUpdateAcreateListTemplate();
}

async function mrcLoadRepoConfig(repo) {
    try {
        const data = await API.get(`/api/mrc/repo-config?repo=${encodeURIComponent(repo)}`);
        state.mrc.adeleteRepoConfig = data;
        state.mrc.acreateRepoConfig = data;
        mrcUpdateAdeleteTemplate();
        mrcUpdateAcreateTemplate();
        mrcVdrUpdateTemplate();
    } catch (e) { showToast('Failed to load repo config: ' + e.message, 'error'); }
}

function mrcSelectOp(op) {
    state.mrc.selectedOp = op;
    document.querySelectorAll('.mrc-op-btn').forEach(b => b.classList.toggle('active', b.dataset.op === op));
    // Show/hide panels
    document.getElementById('mrc-placeholder').style.display = op ? 'none' : '';
    document.querySelectorAll('.mrc-op-panel').forEach(p => p.style.display = 'none');
    if (op) document.getElementById(`mrc-${op}-panel`).style.display = '';
    // Initialize op-specific data
    if (op === 'adelete') {
        mrcUpdateAdeleteTemplate();
        if (state.mrc.selectedRepo) mrcAdeleteLoadCC();
    }
    if (op === 'acreate') {
        mrcAcreateSetMode(state.mrc.acreateMode || 'policy');
        if (state.mrc.selectedRepo) mrcAcreateLoadCC();
    }
    if (op === 'vdrdbxml') {
        mrcVdrUpdateTemplate();
        if (state.mrc.selectedRepo) mrcVdrLoadAllCategories();
    }
}

function mrcUpdateAdeleteTemplate() {
    const tpl = document.getElementById('mrc-adelete-cmd-template');
    if (!tpl) return;
    const cfg = state.mrc.adeleteRepoConfig || {};
    let resolved = state.mrc.adeleteTemplate
        .replace(/\{REPO_NAME\}/g, cfg.repo_name || '{REPO_NAME}')
        .replace(/\{SERVER_USER\}/g, cfg.server_user || '{SERVER_USER}');
    tpl.value = resolved;
    // Also update existing plan rows
    mrcAdeleteRenderPlan();
}

async function mrcAdeleteLoadCC() {
    const tbody = document.querySelector('#mrc-adelete-cc-table tbody');
    const repo = state.mrc.selectedRepo;
    if (!repo) {
        tbody.innerHTML = '<tr><td colspan="2" class="muted">Select a repository first</td></tr>';
        document.getElementById('btn-mrc-adelete-add-selected').disabled = true;
        return;
    }
    tbody.innerHTML = '<tr><td colspan="2" class="muted">Loading…</td></tr>';
    const selectAll = document.querySelector('#mrc-adelete-cc-table .mrc-adelete-select-all');
    if (selectAll) selectAll.checked = false;
    try {
        const data = await API.get(`/api/migrate/content_classes?repo=${encodeURIComponent(repo)}`);
        state.mrc.adeleteCcList = data.items;
        document.getElementById('mrc-adelete-cc-count').textContent = data.count;
        mrcAdeleteRenderCC();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="2" class="status-error">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function mrcAdeleteRenderCC() {
    const tbody = document.querySelector('#mrc-adelete-cc-table tbody');
    const items = state.mrc.adeleteCcList;
    const selectAll = document.querySelector('#mrc-adelete-cc-table .mrc-adelete-select-all');
    if (selectAll) selectAll.checked = false;
    
    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="2" class="muted">No content classes found</td></tr>';
        document.getElementById('btn-mrc-adelete-add-selected').disabled = true;
        return;
    }
    
    tbody.innerHTML = items.map(it => {
        const label = it.description ? `${it.name} - ${it.description}` : it.name;
        return `<tr>
            <td><input type="checkbox" class="mrc-adelete-item-check" value="${escapeHtml(it.name)}"></td>
            <td><strong>${escapeHtml(label)}</strong></td>
        </tr>`;
    }).join('');
    
    // Update button state
    mrcAdeleteUpdateAddButton();
}

function mrcAdeleteResolveCommand(contentClass) {
    const tpl = document.getElementById('mrc-adelete-cmd-template')?.value || state.mrc.adeleteTemplate;
    return tpl.replace(/\{CONTENT_CLASS\}/g, contentClass);
}

function mrcAdeleteUpdateAddButton() {
    const selected = document.querySelectorAll('#mrc-adelete-cc-table .mrc-adelete-item-check:checked').length;
    document.getElementById('btn-mrc-adelete-add-selected').disabled = selected === 0;
}

function mrcAdeleteGetSelected() {
    const selected = [];
    document.querySelectorAll('#mrc-adelete-cc-table .mrc-adelete-item-check:checked').forEach(cb => {
        selected.push(cb.value);
    });
    return selected;
}

function mrcAdeleteAddSelectedToPlan() {
    const selected = mrcAdeleteGetSelected();
    if (selected.length === 0) { showToast('Select at least one content class', 'warning'); return; }
    
    selected.forEach(cc => {
        if (!state.mrc.adeletePlan.some(p => p.cc === cc)) {
            const cmd = mrcAdeleteResolveCommand(cc);
            state.mrc.adeletePlan.push({ cc, command: cmd });
        }
    });
    
    // Deselect checkboxes after adding to plan
    document.querySelectorAll('#mrc-adelete-cc-table .mrc-adelete-item-check:checked').forEach(cb => {
        cb.checked = false;
    });
    document.querySelector('#mrc-adelete-cc-table .mrc-adelete-select-all').checked = false;
    mrcAdeleteUpdateAddButton();
    mrcAdeleteRenderPlan();
}

function mrcAdeleteRenderPlan() {
    const tbody = document.querySelector('#mrc-adelete-plan-table tbody');
    const plan = state.mrc.adeletePlan;
    document.getElementById('mrc-adelete-plan-count').textContent = `${plan.length} item(s) in plan`;
    document.getElementById('btn-mrc-adelete-submit').disabled = plan.length === 0 || !state.mrc.selectedWorker;
    if (!plan.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Select Content Classes on the left and click "Add Selected" to add them to the plan</td></tr>';
        return;
    }
    tbody.innerHTML = plan.map((p, i) => `<tr>
        <td>${i + 1}</td>
        <td><strong>${escapeHtml(p.cc)}</strong></td>
        <td class="mrc-plan-cmd" data-idx="${i}" style="font-family:var(--font-mono);font-size:12px;word-break:break-all;cursor:pointer" title="Click to edit">${escapeHtml(p.command)}</td>
        <td><button class="btn btn-outline btn-sm mrc-del-remove" data-idx="${i}" title="Remove">
            <span class="material-icons-outlined" style="font-size:16px;color:var(--rocket-red)">close</span></button></td>
    </tr>`).join('');
    tbody.querySelectorAll('.mrc-del-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            state.mrc.adeletePlan.splice(parseInt(btn.dataset.idx), 1);
            mrcAdeleteRenderPlan();
            mrcAdeleteRenderCC();
        });
    });
    tbody.querySelectorAll('.mrc-plan-cmd').forEach(td => {
        td.addEventListener('click', () => {
            const idx = parseInt(td.dataset.idx);
            const input = document.createElement('input');
            input.type = 'text'; input.value = state.mrc.adeletePlan[idx].command;
            input.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:12px;padding:2px 4px;box-sizing:border-box';
            td.textContent = ''; td.appendChild(input); input.focus();
            const save = () => { state.mrc.adeletePlan[idx].command = input.value; mrcAdeleteRenderPlan(); };
            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') mrcAdeleteRenderPlan(); });
        });
    });
}

async function mrcAdeleteSubmitPlan() {
    const worker = state.mrc.selectedWorker;
    const repo = state.mrc.selectedRepo;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }
    if (!repo) { showToast('Select a repository first', 'warning'); return; }
    if (!state.mrc.adeletePlan.length) { showToast('Add at least one content class', 'warning'); return; }

    // FIRST CONFIRMATION: Specify repository
    const repoUpper = repo.toUpperCase();
    const listHtml = `<div style="max-height:300px;overflow-y:auto;border:1px solid #ddd;padding:10px;border-radius:4px;margin:12px 0;background:#f9f9f9">
        <ul style="margin:0;padding-left:20px">${state.mrc.adeletePlan.map(p => `<li>${escapeHtml(p.cc)}</li>`).join('')}</ul>
    </div>`;
    const ok1 = await confirmDialog(
        '⚠️ ADELETE Execution',
        `<strong style="color:#d9534f">This operation will DELETE documents from <u>${repoUpper}</u> repository.</strong><br><br>` +
        `<strong>${state.mrc.adeletePlan.length} Content Classes will be deleted:</strong><br>` +
        `${listHtml}` +
        `<strong>Repository: ${repoUpper}</strong><br><br>` +
        `Continue?`
    );
    if (!ok1) return;

    // SECOND CONFIRMATION: Double-check repository name
    const ok2 = await confirmDialog(
        '⚠️ FINAL CONFIRMATION - Type repository name',
        `<strong style="color:#d9534f">THIS CANNOT BE UNDONE!</strong><br><br>` +
        `To confirm deletion from <strong>${repoUpper}</strong>, click OK one more time.<br><br>` +
        `<strong style="color:#d9534f">Repository: ${repoUpper}</strong>`
    );
    if (!ok2) return;

    const btn = document.getElementById('btn-mrc-adelete-submit');
    btn.disabled = true; btn.classList.add('loading');

    const planName = `adelete_${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;
    const steps = state.mrc.adeletePlan.map(p => ({
        repo: repoUpper,
        operation: 'adelete',
        command: p.command,
    }));

    try {
        const result = await API.post('/api/workers/plan', { worker, plan_name: planName, steps });
        const banner = document.getElementById('mrc-adelete-result-banner');
        banner.style.display = '';
        banner.className = 'result-banner success';
        document.getElementById('mrc-adelete-result-icon').textContent = 'check_circle';
        document.getElementById('mrc-adelete-result-title').textContent = 'Plan Submitted';
        document.getElementById('mrc-adelete-result-message').textContent =
            `${result.steps} step(s) sent to ${worker}. File: ${result.file}`;
        showToast(`Plan submitted to ${worker}`, 'success');
        state.mrc.adeletePlan = [];
        mrcAdeleteRenderPlan();
        mrcAdeleteRenderCC();
        mrcSelectOp(null);
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ─── acreate helpers ───────────────────────────────────────────────────────

function encodePathSegments(p) {
    return p.split('/').map(encodeURIComponent).join('/');
}

function mrcAcreateSetMode(mode) {
    state.mrc.acreateMode = mode;
    document.querySelectorAll('.mrc-ac-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    document.getElementById('mrc-ac-policy-mode-selectors').style.display = mode === 'policy' ? '' : 'none';
    document.getElementById('mrc-ac-list-mode-selectors').style.display = mode === 'list' ? '' : 'none';
    const label = document.getElementById('mrc-acreate-template-label');
    if (label) {
        label.innerHTML = mode === 'list'
            ? 'Command Template <span class="muted" style="font-weight:normal">({FILE_PATH} replaced per row)</span>'
            : 'Command Template <span class="muted" style="font-weight:normal">({FILE_PATH}, {CONTENT_CLASS}, {POLICY_NAME} replaced per row)</span>';
    }
    if (mode === 'policy') {
        mrcUpdateAcreateTemplate();
    } else {
        mrcUpdateAcreateListTemplate();
        mrcAcreateListLoadFolders();
    }
}

async function mrcLoadAcreateTemplate() {
    try {
        const data = await API.get('/api/mrc/acreate-template');
        state.mrc.acreateTemplate = data.template;
    } catch (e) {
        state.mrc.acreateTemplate = 'acreate -f {FILE_PATH} -s {REPO_NAME} -u {SERVER_USER} -r {CONTENT_CLASS} -c {POLICY_NAME} -v 2';
    }
}

function mrcUpdateAcreateTemplate() {
    const tpl = document.getElementById('mrc-acreate-cmd-template');
    if (!tpl) return;
    const cfg = state.mrc.acreateRepoConfig || {};
    let resolved = state.mrc.acreateTemplate
        .replace(/\{REPO_NAME\}/g, cfg.repo_name || '{REPO_NAME}')
        .replace(/\{SERVER_USER\}/g, cfg.server_user || '{SERVER_USER}');
    tpl.value = resolved;
    // Re-resolve plan if exists
    mrcAcreateRenderPlan();
}

async function mrcLoadAcreateListTemplate() {
    try {
        const data = await API.get('/api/mrc/acreate-list-template');
        state.mrc.acreateListTemplate = data.template;
    } catch (e) {
        state.mrc.acreateListTemplate = 'acreate -f {FILE_PATH} -s {REPO_NAME} -u {SERVER_USER} -v 2';
    }
}

function mrcUpdateAcreateListTemplate() {
    const tpl = document.getElementById('mrc-acreate-cmd-template');
    if (!tpl) return;
    const cfg = state.mrc.acreateRepoConfig || {};
    let resolved = state.mrc.acreateListTemplate
        .replace(/\{REPO_NAME\}/g, cfg.repo_name || '{REPO_NAME}')
        .replace(/\{SERVER_USER\}/g, cfg.server_user || '{SERVER_USER}');
    tpl.value = resolved;
    mrcAcreateRenderPlan();
}

function mrcAcreateResolveCommand(filePath) {
    const mode = state.mrc.acreateMode;
    if (mode === 'list') {
        const tpl = document.getElementById('mrc-acreate-cmd-template')?.value || state.mrc.acreateListTemplate;
        return tpl.replace(/\{FILE_PATH\}/g, filePath);
    }
    const tpl = document.getElementById('mrc-acreate-cmd-template')?.value || state.mrc.acreateTemplate;
    return tpl
        .replace(/\{FILE_PATH\}/g, filePath)
        .replace(/\{CONTENT_CLASS\}/g, state.mrc.acreateSelectedCC || '{CONTENT_CLASS}')
        .replace(/\{POLICY_NAME\}/g, state.mrc.acreateSelectedPolicy || '{POLICY_NAME}');
}

function mrcAcreateToggleSection(sectionId) {
    const body = document.getElementById(sectionId + '-body');
    const arrow = document.querySelector(`#${sectionId}-header .mrc-collapsible-arrow`);
    const isOpen = body.classList.toggle('open');
    if (arrow) arrow.textContent = isOpen ? 'expand_less' : 'expand_more';
}

function mrcAcreateCollapseAll() {
    ['mrc-ac-cc', 'mrc-ac-policy', 'mrc-ac-folder'].forEach(id => {
        document.getElementById(id + '-body').classList.remove('open');
        const arrow = document.querySelector(`#${id}-header .mrc-collapsible-arrow`);
        if (arrow) arrow.textContent = 'expand_more';
    });
}

function mrcAcreateExpandSection(sectionId) {
    mrcAcreateCollapseAll();
    const body = document.getElementById(sectionId + '-body');
    body.classList.add('open');
    const arrow = document.querySelector(`#${sectionId}-header .mrc-collapsible-arrow`);
    if (arrow) arrow.textContent = 'expand_less';
}

async function mrcAcreateLoadCC() {
    const container = document.getElementById('mrc-ac-cc-list');
    const repo = state.mrc.selectedRepo;
    if (!repo) {
        container.innerHTML = '<div class="muted text-center" style="padding:16px">Select a repository first</div>';
        return;
    }
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    try {
        const data = await API.get(`/api/migrate/content_classes?repo=${encodeURIComponent(repo)}`);
        state.mrc.acreateCcList = data.items;
        mrcAcreateRenderCC();
        // Reset downstream selections
        state.mrc.acreateSelectedCC = null;
        state.mrc.acreateSelectedPolicy = null;
        state.mrc.acreateSelectedFolder = null;
        state.mrc.acreateFolderFiles = [];
        document.getElementById('mrc-ac-cc-value').textContent = '';
        document.getElementById('mrc-ac-policy-value').textContent = '';
        document.getElementById('mrc-ac-folder-value').textContent = '';
        document.getElementById('mrc-ac-policy-list').innerHTML = '<div class="muted text-center" style="padding:16px">Select a content class first</div>';
        document.getElementById('mrc-ac-folder-list').innerHTML = '<div class="muted text-center" style="padding:16px">Select a policy first</div>';
        document.getElementById('btn-mrc-ac-generate').disabled = true;
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function mrcAcreateRenderCC() {
    const container = document.getElementById('mrc-ac-cc-list');
    const items = state.mrc.acreateCcList;
    if (!items.length) {
        container.innerHTML = '<div class="muted text-center" style="padding:16px">No content classes found</div>';
        return;
    }
    container.innerHTML = items.map(it => {
        const selected = state.mrc.acreateSelectedCC === it.name;
        const label = it.description ? `${it.name} - ${it.description}` : it.name;
        return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-cc="${escapeHtml(it.name)}">
            <span class="material-icons-outlined" style="font-size:18px">${selected ? 'radio_button_checked' : 'radio_button_unchecked'}</span>
            <span class="mrc-cc-name">${escapeHtml(label)}</span>
        </div>`;
    }).join('');
    container.querySelectorAll('.mrc-cc-item').forEach(el => {
        el.addEventListener('click', () => {
            state.mrc.acreateSelectedCC = el.dataset.cc;
            document.getElementById('mrc-ac-cc-value').textContent = el.dataset.cc;
            mrcAcreateRenderCC();
            // Collapse CC, expand Policy, load policies
            mrcAcreateExpandSection('mrc-ac-policy');
            mrcAcreateLoadPolicies();
        });
    });
}

async function mrcAcreateLoadPolicies() {
    const container = document.getElementById('mrc-ac-policy-list');
    const repo = state.mrc.selectedRepo;
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    try {
        const data = await API.get(`/api/policies?repo=${encodeURIComponent(repo)}`);
        state.mrc.acreatePolicies = data.policies;
        mrcAcreateRenderPolicies();
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function mrcAcreateRenderPolicies() {
    const container = document.getElementById('mrc-ac-policy-list');
    const items = state.mrc.acreatePolicies;
    if (!items.length) {
        container.innerHTML = '<div class="muted text-center" style="padding:16px">No archiving policies found</div>';
        return;
    }
    container.innerHTML = items.map(it => {
        const selected = state.mrc.acreateSelectedPolicy === it.name;
        const label = it.description ? `${it.name} - ${it.description}` : it.name;
        return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-policy="${escapeHtml(it.name)}">
            <span class="material-icons-outlined" style="font-size:18px">${selected ? 'radio_button_checked' : 'radio_button_unchecked'}</span>
            <span class="mrc-cc-name">${escapeHtml(label)}</span>
        </div>`;
    }).join('');
    container.querySelectorAll('.mrc-cc-item').forEach(el => {
        el.addEventListener('click', () => {
            state.mrc.acreateSelectedPolicy = el.dataset.policy;
            document.getElementById('mrc-ac-policy-value').textContent = el.dataset.policy;
            mrcAcreateRenderPolicies();
            // Collapse Policy, expand Folder, load folders
            mrcAcreateExpandSection('mrc-ac-folder');
            mrcAcreateLoadFolders();
        });
    });
}

async function mrcAcreateLoadFolders() {
    const container = document.getElementById('mrc-ac-folder-list');
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    try {
        const [wsData, dataData] = await Promise.all([
            API.get('/api/folders'),
            API.get('/api/data/folders').catch(() => ({ folders: [] })),
        ]);
        let html = '';

        // ── Workspace folders ──
        if (wsData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Workspace</div>';
            html += wsData.folders.map(f => {
                const key = `workspace:${f.name}`;
                const selected = state.mrc.acreateSelectedFolder === key;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="workspace">
                    <span class="material-icons-outlined" style="font-size:18px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>`;
            }).join('');
        }

        // ── Data folders ──
        if (dataData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-top:8px">Data (/data)</div>';
            html += dataData.folders.map(f => {
                const key = `data:${f.name}`;
                const selected = state.mrc.acreateSelectedFolder === key;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(f.name)}">
                    <span class="material-icons-outlined" style="font-size:18px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-data-expand" data-subpath="${escapeHtml(f.name)}" style="font-size:16px;cursor:pointer;margin-left:4px" title="Expand subdirectories">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-data-children" id="mrc-data-children-${escapeHtml(f.name)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
        }

        if (!html) {
            container.innerHTML = '<div class="muted text-center" style="padding:16px">No folders found</div>';
            return;
        }
        container.innerHTML = html;

        // Click handlers for folder selection
        container.querySelectorAll('.mrc-cc-item').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('mrc-data-expand')) return;
                mrcAcreateSelectFolder(el.dataset.folder);
            });
        });
        // Click handlers for expanding data subdirectories
        container.querySelectorAll('.mrc-data-expand').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                mrcAcreateToggleDataChildren(el.dataset.subpath);
            });
        });
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function mrcAcreateToggleDataChildren(subpath) {
    const childContainer = document.getElementById(`mrc-data-children-${CSS.escape(subpath)}`);
    if (!childContainer) return;
    const arrow = document.querySelector(`.mrc-data-expand[data-subpath="${CSS.escape(subpath)}"]`);

    if (childContainer.style.display !== 'none') {
        childContainer.style.display = 'none';
        if (arrow) arrow.textContent = 'expand_more';
        return;
    }
    childContainer.style.display = '';
    if (arrow) arrow.textContent = 'expand_less';

    if (childContainer.dataset.loaded) return;
    childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">Loading…</div>';

    try {
        const data = await API.get(`/api/data/folders/${encodePathSegments(subpath)}/children`);
        if (!data.folders.length) {
            childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">No subdirectories</div>';
        } else {
            childContainer.innerHTML = data.folders.map(f => {
                const childPath = `${subpath}/${f.name}`;
                const key = `data:${childPath}`;
                const selected = state.mrc.acreateSelectedFolder === key;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(childPath)}">
                    <span class="material-icons-outlined" style="font-size:16px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name" style="font-size:13px">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-data-expand" data-subpath="${escapeHtml(childPath)}" style="font-size:14px;cursor:pointer;margin-left:4px" title="Expand">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:11px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-data-children" id="mrc-data-children-${escapeHtml(childPath)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
            childContainer.querySelectorAll('.mrc-cc-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('mrc-data-expand')) return;
                    mrcAcreateSelectFolder(el.dataset.folder);
                });
            });
            childContainer.querySelectorAll('.mrc-data-expand').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.stopPropagation();
                    mrcAcreateToggleDataChildren(el.dataset.subpath);
                });
            });
        }
        childContainer.dataset.loaded = 'true';
    } catch (e) {
        childContainer.innerHTML = `<div class="muted status-error" style="padding:4px 8px;font-size:12px">Error: ${e.message}</div>`;
    }
}

async function mrcAcreateSelectFolder(folderKey) {
    state.mrc.acreateSelectedFolder = folderKey;
    const [source, ...rest] = folderKey.split(':');
    const folderPath = rest.join(':');
    document.getElementById('mrc-ac-folder-value').textContent = folderKey;

    // Update selection styling (without full reload to preserve expanded data tree)
    document.querySelectorAll('#mrc-ac-folder-list .mrc-cc-item').forEach(el => {
        const isSelected = el.dataset.folder === folderKey;
        el.classList.toggle('selected', isSelected);
        const icon = el.querySelector('.material-icons-outlined');
        if (icon && !icon.classList.contains('mrc-data-expand')) {
            icon.textContent = isSelected ? 'folder' : 'folder_open';
        }
    });

    // Load files from the correct source
    try {
        let data;
        if (source === 'data') {
            data = await API.get(`/api/data/folders/${encodePathSegments(folderPath)}/files`);
        } else {
            data = await API.get(`/api/folders/${encodeURIComponent(folderPath)}/files`);
        }
        state.mrc.acreateFolderFiles = data.files;
        document.getElementById('btn-mrc-ac-generate').disabled = !data.files.length;
    } catch (e) {
        state.mrc.acreateFolderFiles = [];
        document.getElementById('btn-mrc-ac-generate').disabled = true;
        showToast('Failed to load files: ' + e.message, 'error');
    }
}

function mrcAcreateGenerate() {
    if (state.mrc.acreateMode === 'list') return mrcAcreateListGenerate();

    const folderKey = state.mrc.acreateSelectedFolder;
    const files = state.mrc.acreateFolderFiles;
    if (!folderKey || !files.length) return;

    const [source, ...rest] = folderKey.split(':');
    const folderPath = rest.join(':');

    let added = 0;
    for (const f of files) {
        // For /data: use absolute path; for workspace: use relative path
        const filePath = source === 'data' ? `/data/${folderPath}/${f.name}` : `${folderPath}/${f.name}`;
        // Avoid duplicates
        if (state.mrc.acreatePlan.some(p => p.file === filePath)) continue;
        const cmd = mrcAcreateResolveCommand(filePath);
        state.mrc.acreatePlan.push({ file: filePath, command: cmd });
        added++;
    }
    mrcAcreateRenderPlan();
    showToast(`Added ${added} file(s) from ${folderPath}`, 'success');
}

// ─── acreate LIST mode ─────────────────────────────────────────────────────

function mrcAcreateListMatchFilter(filename) {
    const filter = (document.getElementById('mrc-ac-list-filter')?.value || state.mrc.acreateListFilter || '*').trim();
    // Convert glob to regex: *.lst → ^.*\.lst$
    const regex = new RegExp('^' + filter.replace(/\./g, '\\.').replace(/\*/g, '.*').replace(/\?/g, '.') + '$', 'i');
    return regex.test(filename);
}

async function mrcAcreateListLoadFolders() {
    const container = document.getElementById('mrc-ac-list-folder-list');
    if (!container) return;
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    try {
        const [wsData, dataData] = await Promise.all([
            API.get('/api/folders'),
            API.get('/api/data/folders').catch(() => ({ folders: [] })),
        ]);
        let html = '';

        if (wsData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Workspace</div>';
            html += wsData.folders.map(f => {
                const key = `workspace:${f.name}`;
                const selected = state.mrc.acreateListSelectedFolder === key;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="workspace">
                    <span class="material-icons-outlined" style="font-size:18px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>`;
            }).join('');
        }

        if (dataData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-top:8px">Data (/data)</div>';
            html += dataData.folders.map(f => {
                const key = `data:${f.name}`;
                const selected = state.mrc.acreateListSelectedFolder === key;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(f.name)}">
                    <span class="material-icons-outlined" style="font-size:18px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-data-expand-list" data-subpath="${escapeHtml(f.name)}" style="font-size:16px;cursor:pointer;margin-left:4px" title="Expand subdirectories">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-data-children-list" id="mrc-data-children-list-${escapeHtml(f.name)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
        }

        if (!html) {
            container.innerHTML = '<div class="muted text-center" style="padding:16px">No folders found</div>';
            return;
        }
        container.innerHTML = html;

        container.querySelectorAll('.mrc-cc-item').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('mrc-data-expand-list')) return;
                mrcAcreateListSelectFolder(el.dataset.folder);
            });
        });
        container.querySelectorAll('.mrc-data-expand-list').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                mrcAcreateListToggleDataChildren(el.dataset.subpath);
            });
        });
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function mrcAcreateListToggleDataChildren(subpath) {
    const childContainer = document.getElementById(`mrc-data-children-list-${CSS.escape(subpath)}`);
    if (!childContainer) return;
    const arrow = document.querySelector(`.mrc-data-expand-list[data-subpath="${CSS.escape(subpath)}"]`);

    if (childContainer.style.display !== 'none') {
        childContainer.style.display = 'none';
        if (arrow) arrow.textContent = 'expand_more';
        return;
    }
    childContainer.style.display = '';
    if (arrow) arrow.textContent = 'expand_less';

    if (childContainer.dataset.loaded) return;
    childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">Loading…</div>';

    try {
        const data = await API.get(`/api/data/folders/${encodePathSegments(subpath)}/children`);
        if (!data.folders.length) {
            childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">No subdirectories</div>';
        } else {
            childContainer.innerHTML = data.folders.map(f => {
                const childPath = `${subpath}/${f.name}`;
                const key = `data:${childPath}`;
                const selected = state.mrc.acreateListSelectedFolder === key;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item${selected ? ' selected' : ''}" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(childPath)}">
                    <span class="material-icons-outlined" style="font-size:16px">${selected ? 'folder' : 'folder_open'}</span>
                    <span class="mrc-cc-name" style="font-size:13px">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-data-expand-list" data-subpath="${escapeHtml(childPath)}" style="font-size:14px;cursor:pointer;margin-left:4px" title="Expand">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:11px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-data-children-list" id="mrc-data-children-list-${escapeHtml(childPath)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
            childContainer.querySelectorAll('.mrc-cc-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('mrc-data-expand-list')) return;
                    mrcAcreateListSelectFolder(el.dataset.folder);
                });
            });
            childContainer.querySelectorAll('.mrc-data-expand-list').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.stopPropagation();
                    mrcAcreateListToggleDataChildren(el.dataset.subpath);
                });
            });
        }
        childContainer.dataset.loaded = 'true';
    } catch (e) {
        childContainer.innerHTML = `<div class="muted status-error" style="padding:4px 8px;font-size:12px">Error: ${e.message}</div>`;
    }
}

async function mrcAcreateListSelectFolder(folderKey) {
    state.mrc.acreateListSelectedFolder = folderKey;
    const [source, ...rest] = folderKey.split(':');
    const folderPath = rest.join(':');
    document.getElementById('mrc-ac-list-folder-value').textContent = folderKey;

    // Update selection styling
    document.querySelectorAll('#mrc-ac-list-folder-list .mrc-cc-item').forEach(el => {
        const isSelected = el.dataset.folder === folderKey;
        el.classList.toggle('selected', isSelected);
        const icon = el.querySelector('.material-icons-outlined');
        if (icon && !icon.classList.contains('mrc-data-expand-list')) {
            icon.textContent = isSelected ? 'folder' : 'folder_open';
        }
    });

    // Load files from the correct source
    try {
        let data;
        if (source === 'data') {
            data = await API.get(`/api/data/folders/${encodePathSegments(folderPath)}/files`);
        } else {
            data = await API.get(`/api/folders/${encodeURIComponent(folderPath)}/files`);
        }
        // Apply filter
        const filtered = data.files.filter(f => mrcAcreateListMatchFilter(f.name));
        state.mrc.acreateListFolderFiles = filtered;
        document.getElementById('btn-mrc-ac-generate').disabled = !filtered.length;
    } catch (e) {
        state.mrc.acreateListFolderFiles = [];
        document.getElementById('btn-mrc-ac-generate').disabled = true;
        showToast('Failed to load files: ' + e.message, 'error');
    }
}

async function mrcAcreateListGenerate() {
    const folderKey = state.mrc.acreateListSelectedFolder;
    const files = state.mrc.acreateListFolderFiles;
    if (!folderKey || !files.length) return;

    const [source, ...rest] = folderKey.split(':');
    const folderPath = rest.join(':');

    // Build file paths
    const filePaths = files.map(f => source === 'data' ? `/data/${folderPath}/${f.name}` : `${folderPath}/${f.name}`);

    // Check if any files look like LST/list files — validate them
    const lstFiles = filePaths.filter(fp => /\.(lst|txt|list)$/i.test(fp));
    const nonLstFiles = filePaths.filter(fp => !/\.(lst|txt|list)$/i.test(fp));

    const validationContainer = document.getElementById('mrc-ac-lst-validation');

    if (lstFiles.length > 0) {
        // Show validation in progress
        validationContainer.style.display = '';
        validationContainer.innerHTML = '<div class="muted" style="padding:8px;text-align:center"><span class="material-icons-outlined" style="font-size:16px;vertical-align:middle;animation:spin 1s linear infinite">sync</span> Validating LST files…</div>';

        try {
            const repo = state.mrc.selectedRepo || 'source';
            const data = await API.post('/api/mrc/validate-lst', {
                files: lstFiles,
                source: source,
                folder_path: folderPath,
                repo: repo,
            });

            const validFiles = [];
            const invalidFiles = [];
            let reportHtml = '';

            for (const r of data.results) {
                const fileName = r.file.split('/').pop();
                const hasErrors = r.errors.length > 0;
                const hasWarnings = r.warnings.length > 0;
                const hasFixes = r.fixes.length > 0;

                if (!hasErrors) {
                    validFiles.push(r.file);
                } else {
                    invalidFiles.push(r.file);
                }

                // Build report card
                const statusIcon = hasErrors ? 'error' : (hasWarnings ? 'warning' : 'check_circle');
                const statusColor = hasErrors ? 'var(--rocket-red)' : (hasWarnings ? '#f59e0b' : 'var(--success-color, #22c55e)');
                const statusLabel = hasErrors ? 'INVALID' : (hasWarnings ? 'VALID (with warnings)' : 'VALID');

                reportHtml += `<div style="border:1px solid ${hasErrors ? 'var(--rocket-red)' : 'var(--border-color)'};border-radius:6px;padding:8px 10px;margin-bottom:6px;background:${hasErrors ? 'rgba(239,68,68,0.05)' : 'transparent'}">`;
                reportHtml += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">`;
                reportHtml += `<span class="material-icons-outlined" style="font-size:18px;color:${statusColor}">${statusIcon}</span>`;
                reportHtml += `<strong style="font-size:13px">${escapeHtml(fileName)}</strong>`;
                reportHtml += `<span class="muted" style="font-size:11px;margin-left:auto">${statusLabel}</span>`;
                reportHtml += `</div>`;

                if (r.entries && r.entries.length) {
                    reportHtml += `<div style="font-size:12px;color:var(--text-muted);margin-bottom:2px">${r.entries.length} document(s), ${r.entries.reduce((s, e) => s + e.topic_count, 0)} topic(s)</div>`;
                }
                if (hasFixes) {
                    for (const fix of r.fixes) {
                        reportHtml += `<div style="font-size:11px;color:#3b82f6;padding:1px 0"><span class="material-icons-outlined" style="font-size:13px;vertical-align:middle">build</span> ${escapeHtml(fix)}</div>`;
                    }
                }
                if (hasWarnings) {
                    const uniqueWarnings = [...new Set(r.warnings)];
                    for (const w of uniqueWarnings) {
                        reportHtml += `<div style="font-size:11px;color:#f59e0b;padding:1px 0"><span class="material-icons-outlined" style="font-size:13px;vertical-align:middle">warning</span> ${escapeHtml(w)}</div>`;
                    }
                }
                if (hasErrors) {
                    for (const e of r.errors) {
                        reportHtml += `<div style="font-size:11px;color:var(--rocket-red);padding:1px 0"><span class="material-icons-outlined" style="font-size:13px;vertical-align:middle">error</span> ${escapeHtml(e)}</div>`;
                    }
                }
                reportHtml += `</div>`;
            }

            // Summary header
            const totalTopics = data.index_count + (data.ig_member_count || 0);
            const summaryHtml = `<div style="padding:6px 0;margin-bottom:6px;border-bottom:1px solid var(--border-color);font-size:12px">
                <strong>LST Validation</strong> — ${validFiles.length} valid, ${invalidFiles.length} invalid of ${data.results.length} file(s)
                ${totalTopics + data.index_group_count > 0 ? ` · Checked against ${data.index_count} index(es) + ${data.index_group_count} group(s) (${totalTopics} total topic IDs)` : ''}
            </div>`;

            validationContainer.innerHTML = summaryHtml + reportHtml;

            // Add valid LST files to plan
            let added = 0;
            for (const fp of validFiles) {
                if (state.mrc.acreatePlan.some(p => p.file === fp)) continue;
                const cmd = mrcAcreateResolveCommand(fp);
                state.mrc.acreatePlan.push({ file: fp, command: cmd });
                added++;
            }

            if (invalidFiles.length > 0) {
                showToast(`${added} valid file(s) added to plan. ${invalidFiles.length} file(s) need fixes — see validation report.`, 'warning');
            } else {
                showToast(`All ${added} LST file(s) validated and added to plan.`, 'success');
            }

        } catch (e) {
            validationContainer.innerHTML = `<div style="padding:8px;color:var(--rocket-red);font-size:12px"><span class="material-icons-outlined" style="font-size:16px;vertical-align:middle">error</span> Validation failed: ${escapeHtml(e.message)}</div>`;
            showToast('LST validation failed: ' + e.message, 'error');
        }
    }

    // Add any non-LST files directly (no validation needed)
    let addedNonLst = 0;
    for (const fp of nonLstFiles) {
        if (state.mrc.acreatePlan.some(p => p.file === fp)) continue;
        const cmd = mrcAcreateResolveCommand(fp);
        state.mrc.acreatePlan.push({ file: fp, command: cmd });
        addedNonLst++;
    }
    if (addedNonLst > 0 && lstFiles.length === 0) {
        const validationContainer2 = document.getElementById('mrc-ac-lst-validation');
        if (validationContainer2) validationContainer2.style.display = 'none';
        showToast(`Added ${addedNonLst} file(s) matching filter from ${folderPath}`, 'success');
    }

    mrcAcreateRenderPlan();
}

function mrcAcreateRenderPlan() {
    const tbody = document.querySelector('#mrc-acreate-plan-table tbody');
    if (!tbody) return;
    const plan = state.mrc.acreatePlan;
    document.getElementById('mrc-acreate-plan-count').textContent = `${plan.length} item(s) in plan`;
    document.getElementById('btn-mrc-acreate-submit').disabled = plan.length === 0 || !state.mrc.selectedWorker;
    if (!plan.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Select Content Class, Policy, and Folder to generate plan</td></tr>';
        return;
    }
    tbody.innerHTML = plan.map((p, i) => `<tr>
        <td>${i + 1}</td>
        <td><strong>${escapeHtml(p.file)}</strong></td>
        <td class="mrc-plan-cmd" data-idx="${i}" style="font-family:var(--font-mono);font-size:12px;word-break:break-all;cursor:pointer" title="Click to edit">${escapeHtml(p.command)}</td>
        <td><button class="btn btn-outline btn-sm mrc-ac-remove" data-idx="${i}" title="Remove">
            <span class="material-icons-outlined" style="font-size:16px;color:var(--rocket-red)">close</span></button></td>
    </tr>`).join('');
    tbody.querySelectorAll('.mrc-ac-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            state.mrc.acreatePlan.splice(parseInt(btn.dataset.idx), 1);
            mrcAcreateRenderPlan();
        });
    });
    tbody.querySelectorAll('.mrc-plan-cmd').forEach(td => {
        td.addEventListener('click', () => {
            const idx = parseInt(td.dataset.idx);
            const input = document.createElement('input');
            input.type = 'text'; input.value = state.mrc.acreatePlan[idx].command;
            input.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:12px;padding:2px 4px;box-sizing:border-box';
            td.textContent = ''; td.appendChild(input); input.focus();
            const save = () => { state.mrc.acreatePlan[idx].command = input.value; mrcAcreateRenderPlan(); };
            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') mrcAcreateRenderPlan(); });
        });
    });
}

async function mrcAcreateSubmitPlan() {
    const worker = state.mrc.selectedWorker;
    const repo = state.mrc.selectedRepo;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }
    if (!repo) { showToast('Select a repository first', 'warning'); return; }
    if (!state.mrc.acreatePlan.length) { showToast('Add at least one file', 'warning'); return; }

    const btn = document.getElementById('btn-mrc-acreate-submit');
    btn.disabled = true; btn.classList.add('loading');

    const planName = `acreate_${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;
    const steps = state.mrc.acreatePlan.map(p => ({
        repo: repo.toUpperCase(),
        operation: 'acreate',
        command: p.command,
    }));

    try {
        const result = await API.post('/api/workers/plan', { worker, plan_name: planName, steps });
        const banner = document.getElementById('mrc-acreate-result-banner');
        banner.style.display = '';
        banner.className = 'result-banner success';
        document.getElementById('mrc-acreate-result-icon').textContent = 'check_circle';
        document.getElementById('mrc-acreate-result-title').textContent = 'Plan Submitted';
        document.getElementById('mrc-acreate-result-message').textContent =
            `${result.steps} step(s) sent to ${worker}. File: ${result.file}`;
        showToast(`Plan submitted to ${worker}`, 'success');
        state.mrc.acreatePlan = [];
        mrcAcreateRenderPlan();
        mrcSelectOp(null);
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  MRC — VDRDBXML OPERATION                                               ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

async function mrcLoadVdrdbxmlTemplate() {
    try {
        const data = await API.get('/api/mrc/vdrdbxml-template');
        state.mrc.vdrdbxmlTemplate = data.template;
    } catch (e) {
        state.mrc.vdrdbxmlTemplate = 'vdrdbxml -s {REPO_NAME} -u {SERVER_USER} -f {XML_INPUT_FILE_PATH} -out {XML_OUTPUT_FILE_PATH} -v 2';
    }
}

function mrcVdrUpdateTemplate() {
    const tpl = document.getElementById('mrc-vdr-cmd-template');
    if (!tpl) return;
    const cfg = state.mrc.acreateRepoConfig || {};
    let resolved = state.mrc.vdrdbxmlTemplate
        .replace(/\{REPO_NAME\}/g, cfg.repo_name || '{REPO_NAME}')
        .replace(/\{SERVER_USER\}/g, cfg.server_user || '{SERVER_USER}');
    tpl.value = resolved;
}

function mrcVdrSelectMode(mode) {
    state.mrc.vdrdbxmlMode = mode;
    document.querySelectorAll('.mrc-vdr-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    document.getElementById('mrc-vdr-specific-panel').style.display = mode === 'specific' ? '' : 'none';
    if (mode === 'specific' && state.mrc.selectedRepo) mrcVdrLoadAllCategories();
}

function mrcVdrSelectDir(dir) {
    state.mrc.vdrdbxmlDir = dir;
    document.querySelectorAll('.mrc-vdr-dir-btn').forEach(b => b.classList.toggle('active', b.dataset.dir === dir));
    // Show/hide import-only file browser
    const importPanel = document.getElementById('mrc-vdr-import-panel');
    if (importPanel) {
        importPanel.style.display = dir === 'import' ? '' : 'none';
        if (dir === 'import') {
            mrcVdrLoadImportFolders();
        }
    }
    // Hide mode/specific panels when import-only (user picks their own XML)
    const modeDiv = document.querySelector('#mrc-vdrdbxml-panel .mrc-cc-list-card > div:nth-child(2)');
    const specificPanel = document.getElementById('mrc-vdr-specific-panel');
    if (dir === 'import') {
        if (specificPanel) specificPanel.style.display = 'none';
    }
}

// ── vdrdbxml Import Only: folder + file browser ──

function mrcVdrToggleImportSection(section) {
    const bodyId = section === 'folder' ? 'mrc-vdr-import-folder-body' : 'mrc-vdr-import-file-body';
    const body = document.getElementById(bodyId);
    if (!body) return;
    const isOpen = body.classList.toggle('open');
    const header = body.previousElementSibling;
    const arrow = header?.querySelector('.mrc-collapsible-arrow');
    if (arrow) arrow.textContent = isOpen ? 'expand_less' : 'expand_more';
}

async function mrcVdrLoadImportFolders() {
    const container = document.getElementById('mrc-vdr-import-folder-list');
    if (!container) return;
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    state.mrc.vdrdbxmlImportFile = null;
    state.mrc.vdrdbxmlImportFolder = null;
    document.getElementById('mrc-vdr-import-folder-value').textContent = '';
    document.getElementById('mrc-vdr-import-file-value').textContent = '';
    document.getElementById('mrc-vdr-import-file-list').innerHTML = '<div class="muted text-center" style="padding:16px">Select a folder first</div>';

    try {
        const [wsData, dataData] = await Promise.all([
            API.get('/api/folders'),
            API.get('/api/data/folders').catch(() => ({ folders: [] })),
        ]);
        let html = '';

        // Workspace folders
        if (wsData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Workspace</div>';
            html += wsData.folders.map(f => {
                const key = `workspace:${f.name}`;
                return `<div class="mrc-cc-item mrc-vdr-folder-item" data-folder="${escapeHtml(key)}" data-source="workspace">
                    <span class="material-icons-outlined" style="font-size:18px">folder_open</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>`;
            }).join('');
        }

        // Data folders
        if (dataData.folders.length) {
            html += '<div class="muted" style="padding:6px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-top:8px">Data (/data)</div>';
            html += dataData.folders.map(f => {
                const key = `data:${f.name}`;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item mrc-vdr-folder-item" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(f.name)}">
                    <span class="material-icons-outlined" style="font-size:18px">folder_open</span>
                    <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-vdr-data-expand" data-subpath="${escapeHtml(f.name)}" style="font-size:16px;cursor:pointer;margin-left:4px" title="Expand subdirectories">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:12px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-vdr-data-children" id="mrc-vdr-data-children-${escapeHtml(f.name)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
        }

        if (!html) {
            container.innerHTML = '<div class="muted text-center" style="padding:16px">No folders found</div>';
            return;
        }
        container.innerHTML = html;

        // Bind folder click
        container.querySelectorAll('.mrc-vdr-folder-item').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('mrc-vdr-data-expand')) return;
                mrcVdrImportSelectFolder(el.dataset.folder);
            });
        });
        // Bind expand arrows
        container.querySelectorAll('.mrc-vdr-data-expand').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                mrcVdrImportToggleDataChildren(el.dataset.subpath);
            });
        });
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function mrcVdrImportToggleDataChildren(subpath) {
    const childContainer = document.getElementById(`mrc-vdr-data-children-${CSS.escape(subpath)}`);
    if (!childContainer) return;
    const arrow = document.querySelector(`.mrc-vdr-data-expand[data-subpath="${CSS.escape(subpath)}"]`);

    if (childContainer.style.display !== 'none') {
        childContainer.style.display = 'none';
        if (arrow) arrow.textContent = 'expand_more';
        return;
    }
    childContainer.style.display = '';
    if (arrow) arrow.textContent = 'expand_less';

    if (childContainer.dataset.loaded) return;
    childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">Loading…</div>';

    try {
        const data = await API.get(`/api/data/folders/${encodePathSegments(subpath)}/children`);
        if (!data.folders.length) {
            childContainer.innerHTML = '<div class="muted" style="padding:4px 8px;font-size:12px">No subdirectories</div>';
        } else {
            childContainer.innerHTML = data.folders.map(f => {
                const childPath = `${subpath}/${f.name}`;
                const key = `data:${childPath}`;
                const hasSubdirs = f.subdirs_count > 0;
                return `<div class="mrc-cc-item mrc-vdr-folder-item" data-folder="${escapeHtml(key)}" data-source="data" data-subpath="${escapeHtml(childPath)}">
                    <span class="material-icons-outlined" style="font-size:16px">folder_open</span>
                    <span class="mrc-cc-name" style="font-size:13px">${escapeHtml(f.name)}</span>
                    ${hasSubdirs ? `<span class="material-icons-outlined mrc-vdr-data-expand" data-subpath="${escapeHtml(childPath)}" style="font-size:14px;cursor:pointer;margin-left:4px" title="Expand">expand_more</span>` : ''}
                    <span class="muted" style="margin-left:auto;font-size:11px">${f.files_count} file(s)</span>
                </div>
                <div class="mrc-vdr-data-children" id="mrc-vdr-data-children-${escapeHtml(childPath)}" style="display:none;padding-left:20px"></div>`;
            }).join('');
            childContainer.querySelectorAll('.mrc-vdr-folder-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('mrc-vdr-data-expand')) return;
                    mrcVdrImportSelectFolder(el.dataset.folder);
                });
            });
            childContainer.querySelectorAll('.mrc-vdr-data-expand').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.stopPropagation();
                    mrcVdrImportToggleDataChildren(el.dataset.subpath);
                });
            });
        }
        childContainer.dataset.loaded = 'true';
    } catch (e) {
        childContainer.innerHTML = `<div class="muted status-error" style="padding:4px 8px;font-size:12px">Error: ${e.message}</div>`;
    }
}

async function mrcVdrImportSelectFolder(folderKey) {
    state.mrc.vdrdbxmlImportFolder = folderKey;
    state.mrc.vdrdbxmlImportFile = null;
    const [source, ...rest] = folderKey.split(':');
    const folderPath = rest.join(':');

    document.getElementById('mrc-vdr-import-folder-value').textContent = folderKey;
    document.getElementById('mrc-vdr-import-file-value').textContent = '';

    // Update folder selection styling
    document.querySelectorAll('#mrc-vdr-import-folder-list .mrc-vdr-folder-item').forEach(el => {
        const isSel = el.dataset.folder === folderKey;
        el.classList.toggle('selected', isSel);
        const icon = el.querySelector('.material-icons-outlined:first-child');
        if (icon && !icon.classList.contains('mrc-vdr-data-expand')) {
            icon.textContent = isSel ? 'folder' : 'folder_open';
        }
    });

    // Load files from selected folder and filter for XML
    const fileContainer = document.getElementById('mrc-vdr-import-file-list');
    fileContainer.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';

    try {
        let data;
        if (source === 'data') {
            data = await API.get(`/api/data/folders/${encodePathSegments(folderPath)}/files`);
        } else {
            data = await API.get(`/api/folders/${encodeURIComponent(folderPath)}/files`);
        }
        const xmlFiles = (data.files || []).filter(f => /\.xml$/i.test(f.name));
        if (!xmlFiles.length) {
            fileContainer.innerHTML = '<div class="muted text-center" style="padding:16px">No XML files in this folder</div>';
            return;
        }
        fileContainer.innerHTML = xmlFiles.map(f => {
            const fullPath = source === 'data' ? `/data/${folderPath}/${f.name}` : `/workspace/${folderPath}/${f.name}`;
            return `<div class="mrc-cc-item mrc-vdr-import-item" data-path="${escapeHtml(fullPath)}" data-name="${escapeHtml(f.name)}" style="cursor:pointer">
                <span class="material-icons-outlined" style="font-size:16px;color:var(--muted)">description</span>
                <span class="mrc-cc-name">${escapeHtml(f.name)}</span>
                <span class="muted" style="font-size:11px;margin-left:auto">${(f.size / 1024).toFixed(1)} KB</span>
            </div>`;
        }).join('');

        fileContainer.querySelectorAll('.mrc-vdr-import-item').forEach(el => {
            el.addEventListener('click', () => {
                fileContainer.querySelectorAll('.mrc-vdr-import-item').forEach(r => r.classList.remove('row-selected'));
                el.classList.add('row-selected');
                state.mrc.vdrdbxmlImportFile = el.dataset.path;
                document.getElementById('mrc-vdr-import-file-value').textContent = el.dataset.name;
            });
        });
    } catch (e) {
        fileContainer.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function mrcVdrLoadAllCategories() {
    const repo = state.mrc.selectedRepo;
    if (!repo) return;
    await Promise.all([
        mrcVdrLoadCategory('content_classes', 'mrc-vdr-cc-list', 'mrc-vdr-cc-count', 'vdrdbxmlCcList'),
        mrcVdrLoadCategory('indexes', 'mrc-vdr-idx-list', 'mrc-vdr-idx-count', 'vdrdbxmlIdxList'),
        mrcVdrLoadCategory('index_groups', 'mrc-vdr-ig-list', 'mrc-vdr-ig-count', 'vdrdbxmlIgList'),
        mrcVdrLoadCategory('archiving_policies', 'mrc-vdr-pol-list', 'mrc-vdr-pol-count', 'vdrdbxmlPolList'),
    ]);
}

async function mrcVdrLoadCategory(objectType, containerId, countId, stateKey) {
    const container = document.getElementById(containerId);
    container.innerHTML = '<div class="muted text-center" style="padding:16px">Loading…</div>';
    try {
        const repo = state.mrc.selectedRepo;
        const data = await API.get(`/api/migrate/${objectType}?repo=${encodeURIComponent(repo)}`);
        state.mrc[stateKey] = data.items;
        document.getElementById(countId).textContent = data.count;
        if (!data.items.length) {
            container.innerHTML = '<div class="muted text-center" style="padding:16px">No items found</div>';
            return;
        }
        container.innerHTML = data.items.map(it => {
            const label = it.description ? `${it.name} - ${it.description}` : it.name;
            return `<div class="mrc-cc-item mrc-vdr-item" data-cat="${escapeHtml(stateKey)}" data-name="${escapeHtml(it.name)}">
                <input type="checkbox" class="mrc-vdr-check" data-cat="${escapeHtml(stateKey)}" value="${escapeHtml(it.name)}" style="margin:0">
                <span class="mrc-cc-name">${escapeHtml(label)}</span>
            </div>`;
        }).join('');
        container.querySelectorAll('.mrc-vdr-item').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox') return;
                const cb = el.querySelector('.mrc-vdr-check');
                cb.checked = !cb.checked;
            });
        });
    } catch (e) {
        container.innerHTML = `<div class="muted text-center status-error" style="padding:16px">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function mrcVdrToggleSection(sectionId) {
    const body = document.getElementById(sectionId + '-body');
    const arrow = document.querySelector(`#${sectionId}-header .mrc-collapsible-arrow`);
    const isOpen = body.classList.toggle('open');
    if (arrow) arrow.textContent = isOpen ? 'expand_less' : 'expand_more';
}

function mrcVdrGetSelected() {
    const result = { content_classes: [], indexes: [], index_groups: [], archiving_policies: [] };
    const mapping = {
        vdrdbxmlCcList: 'content_classes',
        vdrdbxmlIdxList: 'indexes',
        vdrdbxmlIgList: 'index_groups',
        vdrdbxmlPolList: 'archiving_policies',
    };
    document.querySelectorAll('.mrc-vdr-check:checked').forEach(cb => {
        const cat = cb.dataset.cat;
        const key = mapping[cat];
        if (key) result[key].push(cb.value);
    });
    return result;
}

async function mrcVdrGeneratePlan() {
    const worker = state.mrc.selectedWorker;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }
    const repo = state.mrc.selectedRepo;
    if (!repo) { showToast('Select a repository first', 'warning'); return; }

    const template = document.getElementById('mrc-vdr-cmd-template')?.value || state.mrc.vdrdbxmlTemplate;
    const mode = state.mrc.vdrdbxmlMode;
    const dir = state.mrc.vdrdbxmlDir;

    // Import Only: build a single TARGET import step from the selected XML file
    if (dir === 'import') {
        const xmlPath = state.mrc.vdrdbxmlImportFile;
        if (!xmlPath) { showToast('Select an XML input file first', 'warning'); return; }
        // Build output path: same dir, same base name + _out_<timestamp>.xml
        const parts = xmlPath.replace(/\\/g, '/').split('/');
        const fileName = parts.pop();
        const dirPath = parts.join('/');
        const baseName = fileName.replace(/\.xml$/i, '');
        const now = new Date();
        const ts = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}.${String(now.getMinutes()).padStart(2,'0')}.${String(now.getSeconds()).padStart(2,'0')}`;
        const outPath = `${dirPath}/${baseName}_out_${ts}.xml`;

        const cfg = state.mrc.acreateRepoConfig || {};
        const cmd = template
            .replace(/\{REPO_NAME\}/g, cfg.repo_name || '{REPO_NAME}')
            .replace(/\{SERVER_USER\}/g, cfg.server_user || '{SERVER_USER}')
            .replace(/\{SERVER_PASS\}/g, cfg.server_pass || '{SERVER_PASS}')
            .replace(/\{XML_INPUT_FILE_PATH\}/g, xmlPath)
            .replace(/\{XML_OUTPUT_FILE_PATH\}/g, outPath);

        state.mrc.vdrdbxmlPlanSteps = [
            { repo: 'TARGET', operation: 'vdrdbxml', command: cmd },
        ];
        state.mrc.vdrdbxmlXmlPreview = '';
        mrcVdrRenderPlan();
        document.getElementById('btn-mrc-vdr-submit').disabled = false;
        showToast('Plan generated: 1 step (Import Only)', 'success');
        return;
    }

    let body = { worker, mode, template };
    if (mode === 'specific') {
        const sel = mrcVdrGetSelected();
        const total = sel.content_classes.length + sel.indexes.length + sel.index_groups.length + sel.archiving_policies.length;
        if (total === 0) { showToast('Select at least one item', 'warning'); return; }
        Object.assign(body, sel);
    }

    try {
        const result = await API.post('/api/migrate/prepare-xml', body);
        let steps = result.steps;
        // If export-only, only keep the first step (SOURCE export)
        if (dir === 'export') {
            steps = steps.filter(s => s.repo === 'SOURCE');
        }
        state.mrc.vdrdbxmlPlanSteps = steps;

        // XML preview for specific mode
        if (mode === 'specific') {
            const sel = mrcVdrGetSelected();
            state.mrc.vdrdbxmlXmlPreview = mrcVdrBuildXmlPreview(sel);
        } else {
            state.mrc.vdrdbxmlXmlPreview = '';
        }

        mrcVdrRenderPlan();
        document.getElementById('btn-mrc-vdr-submit').disabled = false;
        showToast(`Plan generated: ${steps.length} step(s)`, 'success');
    } catch (e) {
        showToast('Failed to generate plan: ' + e.message, 'error');
    }
}

function mrcVdrBuildXmlPreview(sel) {
    let lines = ['<?xml version="1.0" ?>', '<VDRNET_DB_MASS_UPDATE VDRNET_VERSION="4.1">', ''];
    for (const cc of sel.content_classes) {
        lines.push(`<REPORT action="get" outAction="add/modify">`);
        lines.push(` <REPORT_ID>${cc}</REPORT_ID>`);
        lines.push(`</REPORT>`);
        lines.push('');
    }
    for (const idx of sel.indexes) {
        lines.push(`<TOPIC action="get" outAction="add/modify">`);
        lines.push(` <TOPIC_ID>${idx}</TOPIC_ID>`);
        lines.push(`</TOPIC>`);
        lines.push('');
    }
    for (const ig of sel.index_groups) {
        lines.push(`<TOPIC_GROUP action="get" outAction="add/modify">`);
        lines.push(` <TOPIC_GROUP_ID>${ig}</TOPIC_GROUP_ID>`);
        lines.push(`</TOPIC_GROUP>`);
        lines.push('');
    }
    for (const pol of sel.archiving_policies) {
        lines.push(`<POLICY action="get" outAction="add/modify">`);
        lines.push(` <POLICY_NAME>${pol}</POLICY_NAME>`);
        lines.push(`</POLICY>`);
        lines.push('');
    }
    lines.push('</VDRNET_DB_MASS_UPDATE>');
    return lines.join('\n');
}

function mrcVdrRenderPlan() {
    const steps = state.mrc.vdrdbxmlPlanSteps;
    const tbody = document.querySelector('#mrc-vdr-plan-table tbody');
    if (!steps.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Click "Generate Plan" to preview the vdrdbxml steps</td></tr>';
        return;
    }
    tbody.innerHTML = steps.map((s, i) => `<tr>
        <td>${i + 1}</td>
        <td><strong>${escapeHtml(s.repo)}</strong></td>
        <td class="mrc-plan-cmd" data-idx="${i}" style="font-family:var(--font-mono);font-size:12px;word-break:break-all;cursor:pointer" title="Click to edit">${escapeHtml(s.command)}</td>
        <td><button class="btn btn-outline btn-sm mrc-vdr-remove" data-idx="${i}" title="Remove">
            <span class="material-icons-outlined" style="font-size:16px;color:var(--rocket-red)">close</span></button></td>
    </tr>`).join('');
    tbody.querySelectorAll('.mrc-vdr-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            state.mrc.vdrdbxmlPlanSteps.splice(parseInt(btn.dataset.idx), 1);
            mrcVdrRenderPlan();
            document.getElementById('btn-mrc-vdr-submit').disabled = state.mrc.vdrdbxmlPlanSteps.length === 0;
        });
    });
    tbody.querySelectorAll('.mrc-plan-cmd').forEach(td => {
        td.addEventListener('click', () => {
            const idx = parseInt(td.dataset.idx);
            const input = document.createElement('input');
            input.type = 'text'; input.value = state.mrc.vdrdbxmlPlanSteps[idx].command;
            input.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:12px;padding:2px 4px;box-sizing:border-box';
            td.textContent = ''; td.appendChild(input); input.focus();
            const save = () => { state.mrc.vdrdbxmlPlanSteps[idx].command = input.value; mrcVdrRenderPlan(); };
            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') mrcVdrRenderPlan(); });
        });
    });

    // XML preview
    const xmlDiv = document.getElementById('mrc-vdr-xml-preview');
    if (state.mrc.vdrdbxmlXmlPreview) {
        xmlDiv.style.display = '';
        document.getElementById('mrc-vdr-xml-content').textContent = state.mrc.vdrdbxmlXmlPreview;
    } else {
        xmlDiv.style.display = 'none';
    }
}

async function mrcVdrSubmitPlan() {
    const steps = state.mrc.vdrdbxmlPlanSteps;
    const worker = state.mrc.selectedWorker;
    if (!steps.length || !worker) return;

    const btn = document.getElementById('btn-mrc-vdr-submit');
    btn.disabled = true;
    btn.classList.add('loading');
    let success = false;

    try {
        const planName = `vdrdbxml_${Date.now()}`;
        await API.post('/api/workers/plan', {
            worker,
            plan_name: planName,
            steps: steps.map(s => ({ repo: s.repo, operation: s.operation, command: s.command })),
        });
        const banner = document.getElementById('mrc-vdr-result-banner');
        banner.style.display = '';
        document.getElementById('mrc-vdr-result-icon').textContent = 'check_circle';
        document.getElementById('mrc-vdr-result-icon').style.color = 'var(--rocket-green)';
        document.getElementById('mrc-vdr-result-title').textContent = 'Plan submitted successfully';
        document.getElementById('mrc-vdr-result-message').textContent = `${steps.length} step(s) sent to ${worker} as "${planName}"`;
        state.mrc.vdrdbxmlPlanSteps = [];
        mrcVdrRenderPlan();
        success = true;
        mrcSelectOp(null);
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = success; }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  TOOL 3: MIGRATE (vdrdbxml)                                             ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function migGoToStep(step) {
    state.mig.currentStep = step;
    goToToolStep('tool-migrate', 'mig', step);
    if (step === 2) migLoadAllCategories();
    if (step === 3) migRenderPlanPreview();
}

function migSelectMode(mode) {
    state.mig.mode = mode;
    document.querySelectorAll('.mig-mode-card').forEach(el => {
        el.classList.toggle('selected', el.dataset.mode === mode);
    });
}

async function migLoadWorkers() {
    try {
        const workers = await API.get('/api/workers');
        const select = document.getElementById('mig-worker-select');
        const current = select.value;
        select.innerHTML = '<option value="">— Select worker —</option>';
        for (const w of workers) {
            if (!w.alive) continue;
            const opt = document.createElement('option');
            opt.value = w.worker;
            opt.textContent = `${w.worker} (${w.debug ? 'DEBUG' : 'LIVE'})`;
            select.appendChild(opt);
        }
        if (current) select.value = current;
        state.mig.selectedWorker = select.value || null;
    } catch (e) { showToast('Failed to load workers: ' + e.message, 'error'); }
}

async function migLoadVdrdbxmlTemplate() {
    try {
        const data = await API.get('/api/mrc/vdrdbxml-template');
        state.mig.vdrdbxmlTemplate = data.template;
        const tpl = document.getElementById('mig-vdrdbxml-template');
        if (tpl) tpl.value = data.template;
    } catch (e) {
        state.mig.vdrdbxmlTemplate = 'vdrdbxml -s {REPO_NAME} -u {SERVER_USER} -f {XML_INPUT_FILE_PATH} -out {XML_OUTPUT_FILE_PATH} -v 2';
    }
}

async function migInit() {
    await Promise.all([migLoadWorkers(), migLoadVdrdbxmlTemplate()]);
}

function migStep1Next() {
    const worker = document.getElementById('mig-worker-select').value;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }
    state.mig.selectedWorker = worker;

    if (state.mig.mode === 'all') {
        // Skip step 2, go directly to step 3
        migPrepareAndPreview();
    } else {
        migGoToStep(2);
    }
}

async function migLoadAllCategories() {
    await Promise.all([
        migLoadCategory('content_classes', 'mig-cc-table', 'mig-cc-count', 'ccItems'),
        migLoadCategory('indexes', 'mig-idx-table', 'mig-idx-count', 'idxItems'),
        migLoadCategory('index_groups', 'mig-ig-table', 'mig-ig-count', 'igItems'),
        migLoadCategory('archiving_policies', 'mig-pol-table', 'mig-pol-count', 'polItems'),
    ]);
}

async function migLoadCategory(objectType, tableId, countId, stateKey) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    tbody.innerHTML = '<tr><td colspan="2" class="muted">Loading…</td></tr>';
    const selectAll = document.querySelector(`#${tableId} .mig-select-all`);
    if (selectAll) selectAll.checked = false;
    try {
        const data = await API.get(`/api/migrate/${objectType}?repo=source`);
        state.mig[stateKey] = data.items;
        document.getElementById(countId).textContent = data.count;
        if (data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" class="muted">No items found</td></tr>';
        } else {
            tbody.innerHTML = data.items.map(it => {
                const label = it.description ? `${it.name} - ${it.description}` : it.name;
                return `<tr>
                <td><input type="checkbox" class="mig-item-check" data-cat="${stateKey}" value="${escapeHtml(it.name)}"></td>
                <td><strong>${escapeHtml(label)}</strong></td></tr>`;
            }).join('');
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="2" class="status-error">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function migGetSelectedByCategory() {
    const result = { content_classes: [], indexes: [], index_groups: [], archiving_policies: [] };
    const mapping = {
        ccItems: 'content_classes',
        idxItems: 'indexes',
        igItems: 'index_groups',
        polItems: 'archiving_policies',
    };
    document.querySelectorAll('.mig-item-check:checked').forEach(cb => {
        const cat = cb.dataset.cat;
        const key = mapping[cat];
        if (key) result[key].push(cb.value);
    });
    return result;
}

async function migPrepareAndPreview() {
    const worker = state.mig.selectedWorker;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }

    const template = document.getElementById('mig-vdrdbxml-template')?.value || state.mig.vdrdbxmlTemplate;
    let body = { worker, mode: state.mig.mode, template };
    if (state.mig.mode === 'specific') {
        const sel = migGetSelectedByCategory();
        const total = sel.content_classes.length + sel.indexes.length + sel.index_groups.length + sel.archiving_policies.length;
        if (total === 0) { showToast('Select at least one item to migrate', 'warning'); return; }
        Object.assign(body, sel);
    }

    try {
        const result = await API.post('/api/migrate/prepare-xml', body);
        state.mig.planSteps = result.steps;
        state.mig.xmlPreview = '';
        // For specific mode, show a local XML preview
        if (state.mig.mode === 'specific') {
            const sel = migGetSelectedByCategory();
            state.mig.xmlPreview = migBuildXmlPreview(sel);
        }
        migGoToStep(3);
    } catch (e) {
        showToast('Failed to prepare migration: ' + e.message, 'error');
    }
}

function migBuildXmlPreview(sel) {
    let lines = ['<?xml version="1.0" ?>', '<VDRNET_DB_MASS_UPDATE VDRNET_VERSION="4.1">', ''];
    for (const cc of sel.content_classes) {
        lines.push(`<REPORT action="get" outAction="add/modify">`);
        lines.push(`<REPORT_ID>${cc}</REPORT_ID>`);
        lines.push(`</REPORT>`);
        lines.push('');
    }
    for (const idx of sel.indexes) {
        lines.push(`<TOPIC action="get" outAction="add/modify">`);
        lines.push(` <TOPIC_ID>${idx}</TOPIC_ID>`);
        lines.push(`</TOPIC>`);
        lines.push('');
    }
    for (const ig of sel.index_groups) {
        lines.push(`<TOPIC_GROUP action="get" outAction="add/modify">`);
        lines.push(` <TOPIC_GROUP_ID>${ig}</TOPIC_GROUP_ID>`);
        lines.push(`</TOPIC_GROUP>`);
        lines.push('');
    }
    for (const pol of sel.archiving_policies) {
        lines.push(`<POLICY action="get" outAction="add/modify">`);
        lines.push(` <POLICY_NAME>${pol}</POLICY_NAME>`);
        lines.push(`</POLICY>`);
        lines.push('');
    }
    lines.push('</VDRNET_DB_MASS_UPDATE>');
    return lines.join('\n');
}

function migRenderPlanPreview() {
    const steps = state.mig.planSteps;
    const mode = state.mig.mode;
    const worker = state.mig.selectedWorker;

    document.getElementById('mig-plan-summary').textContent =
        `Mode: ${mode === 'all' ? 'All Definitions' : 'Specific Items'} · Worker: ${worker} · ${steps.length} step(s)`;

    const tbody = document.querySelector('#mig-plan-table tbody');
    tbody.innerHTML = steps.map((s, i) => `<tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(s.repo)}</td>
        <td>${escapeHtml(s.operation)}</td>
        <td style="font-family:var(--font-mono);font-size:12px;word-break:break-all">${escapeHtml(s.command)}</td>
    </tr>`).join('');

    // XML preview
    const xmlDiv = document.getElementById('mig-xml-preview');
    if (state.mig.xmlPreview) {
        xmlDiv.style.display = '';
        document.getElementById('mig-xml-content').textContent = state.mig.xmlPreview;
    } else {
        xmlDiv.style.display = 'none';
    }

    document.getElementById('mig-result-banner').style.display = 'none';
}

async function migSubmitPlan() {
    const worker = state.mig.selectedWorker;
    const steps = state.mig.planSteps;
    if (!worker || !steps.length) { showToast('No plan to submit', 'warning'); return; }

    const btn = document.getElementById('btn-mig-submit');
    btn.disabled = true; btn.classList.add('loading');

    const planName = `migrate_${state.mig.mode}_${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;

    try {
        const result = await API.post('/api/workers/plan', {
            worker,
            plan_name: planName,
            steps,
        });

        const banner = document.getElementById('mig-result-banner');
        banner.style.display = '';
        banner.className = 'result-banner success';
        document.getElementById('mig-result-icon').textContent = 'check_circle';
        document.getElementById('mig-result-title').textContent = 'Migration Plan Submitted';
        document.getElementById('mig-result-message').textContent =
            `${result.steps} step(s) sent to ${worker}. File: ${result.file}`;
        showToast(`Migration plan submitted to ${worker}`, 'success');
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  TOOL 3b: REMOVE DEFINITIONS                                            ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function rdGoToStep(step) {
    state.rd.currentStep = step;
    goToToolStep('tool-remove-defs', 'rd', step);
    if (step === 2) rdRenderPlanPreview();
}

async function rdLoadWorkers() {
    try {
        const workers = await API.get('/api/workers');
        const select = document.getElementById('rd-worker-select');
        const current = select.value;
        select.innerHTML = '<option value="">— Select worker —</option>';
        for (const w of workers) {
            if (!w.alive) continue;
            const opt = document.createElement('option');
            opt.value = w.worker;
            opt.textContent = `${w.worker} (${w.debug ? 'DEBUG' : 'LIVE'})`;
            select.appendChild(opt);
        }
        if (current) select.value = current;
        state.rd.selectedWorker = select.value || null;
    } catch (e) { showToast('Failed to load workers: ' + e.message, 'error'); }
}

function rdSelectRepo(repo) {
    state.rd.selectedRepo = repo;
    document.querySelectorAll('.rd-repo-btn').forEach(b => b.classList.toggle('active', b.dataset.repo === repo));
    rdLoadAllCategories();
}

async function rdLoadAllCategories() {
    const repo = state.rd.selectedRepo;
    await Promise.all([
        rdLoadCategory('content_classes', 'rd-cc-table', 'rd-cc-count', 'ccItems', repo),
        rdLoadCategory('indexes', 'rd-idx-table', 'rd-idx-count', 'idxItems', repo),
        rdLoadCategory('index_groups', 'rd-ig-table', 'rd-ig-count', 'igItems', repo),
        rdLoadCategory('archiving_policies', 'rd-pol-table', 'rd-pol-count', 'polItems', repo),
    ]);
}

async function rdLoadCategory(objectType, tableId, countId, stateKey, repo) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    tbody.innerHTML = '<tr><td colspan="2" class="muted">Loading…</td></tr>';
    const selectAll = document.querySelector(`#${tableId} .rd-select-all`);
    if (selectAll) selectAll.checked = false;
    try {
        const data = await API.get(`/api/migrate/${objectType}?repo=${encodeURIComponent(repo)}`);
        state.rd[stateKey] = data.items;
        document.getElementById(countId).textContent = data.count;
        if (data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" class="muted">No items found</td></tr>';
        } else {
            tbody.innerHTML = data.items.map(it => {
                const label = it.description ? `${it.name} - ${it.description}` : it.name;
                return `<tr>
                <td><input type="checkbox" class="rd-item-check" data-cat="${stateKey}" value="${escapeHtml(it.name)}"></td>
                <td><strong>${escapeHtml(label)}</strong></td></tr>`;
            }).join('');
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="2" class="status-error">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function rdGetSelected() {
    const result = { content_classes: [], indexes: [], index_groups: [], archiving_policies: [] };
    const mapping = {
        ccItems: 'content_classes',
        idxItems: 'indexes',
        igItems: 'index_groups',
        polItems: 'archiving_policies',
    };
    document.querySelectorAll('.rd-item-check:checked').forEach(cb => {
        const cat = cb.dataset.cat;
        const key = mapping[cat];
        if (key) result[key].push(cb.value);
    });
    return result;
}

async function rdPrepareAndPreview() {
    const worker = document.getElementById('rd-worker-select').value;
    if (!worker) { showToast('Select a worker first', 'warning'); return; }
    state.rd.selectedWorker = worker;

    const sel = rdGetSelected();
    const total = sel.content_classes.length + sel.indexes.length + sel.index_groups.length + sel.archiving_policies.length;
    if (total === 0) { showToast('Select at least one item to remove', 'warning'); return; }

    try {
        const result = await API.post('/api/remove-definitions/prepare', {
            worker,
            repo: state.rd.selectedRepo,
            ...sel,
        });
        state.rd.planSteps = result.steps;
        rdGoToStep(2);
    } catch (e) {
        showToast('Failed to prepare removal plan: ' + e.message, 'error');
    }
}

function rdRenderPlanPreview() {
    const steps = state.rd.planSteps;
    const worker = state.rd.selectedWorker;
    const repo = state.rd.selectedRepo;

    document.getElementById('rd-plan-summary').textContent =
        `Repository: ${repo.toUpperCase()} · Worker: ${worker} · ${steps.length} step(s)`;

    const tbody = document.querySelector('#rd-plan-table tbody');
    tbody.innerHTML = steps.map((s, i) => `<tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(s.repo)}</td>
        <td>${escapeHtml(s.operation)}</td>
        <td style="font-family:var(--font-mono);font-size:12px;word-break:break-all">${escapeHtml(s.command)}</td>
    </tr>`).join('');

    // Show items summary
    const sel = rdGetSelected();
    const lines = [];
    if (sel.archiving_policies.length) lines.push(`Archiving Policies (${sel.archiving_policies.length}):\n  ${sel.archiving_policies.join('\n  ')}`);
    if (sel.content_classes.length) lines.push(`Content Classes (${sel.content_classes.length}):\n  ${sel.content_classes.join('\n  ')}`);
    if (sel.index_groups.length) lines.push(`Index Groups (${sel.index_groups.length}):\n  ${sel.index_groups.join('\n  ')}`);
    if (sel.indexes.length) lines.push(`Indexes (${sel.indexes.length}):\n  ${sel.indexes.join('\n  ')}`);
    document.getElementById('rd-items-content').textContent = lines.join('\n\n');

    document.getElementById('rd-result-banner').style.display = 'none';
}

async function rdSubmitPlan() {
    const worker = state.rd.selectedWorker;
    const steps = state.rd.planSteps;
    if (!worker || !steps.length) { showToast('No plan to submit', 'warning'); return; }

    const repoUpper = state.rd.selectedRepo.toUpperCase();
    
    // FIRST CONFIRMATION: Specify repository and items to remove
    const sel = rdGetSelected();
    const itemsText = [
        sel.archiving_policies.length ? `Archiving Policies: ${sel.archiving_policies.length}` : null,
        sel.content_classes.length ? `Content Classes: ${sel.content_classes.length}` : null,
        sel.index_groups.length ? `Index Groups: ${sel.index_groups.length}` : null,
        sel.indexes.length ? `Indexes: ${sel.indexes.length}` : null,
    ].filter(Boolean).join('<br>');
    
    const ok1 = await confirmDialog(
        '⚠️ REMOVE DEFINITIONS - Step 1',
        `<strong style="color:#d9534f">This operation will PERMANENTLY DELETE definitions from <u>${repoUpper}</u> repository.</strong><br><br>` +
        `Items to remove:<br>` +
        `${itemsText}<br><br>` +
        `<strong>Target Repository: ${repoUpper}</strong><br><br>` +
        `Continue?`
    );
    if (!ok1) return;

    // SECOND CONFIRMATION: Final double-check
    const ok2 = await confirmDialog(
        '⚠️ FINAL CONFIRMATION - REMOVE DEFINITIONS',
        `<strong style="color:#d9534f">⚠️  THIS ACTION CANNOT BE UNDONE! ⚠️</strong><br><br>` +
        `You are about to permanently remove:<br>` +
        `${itemsText}<br><br>` +
        `From Repository: <strong style="color:#d9534f">${repoUpper}</strong><br><br>` +
        `Click OK to permanently execute this removal.`
    );
    if (!ok2) return;

    const btn = document.getElementById('btn-rd-submit');
    btn.disabled = true; btn.classList.add('loading');

    const planName = `rm_defs_${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;

    try {
        const result = await API.post('/api/workers/plan', {
            worker,
            plan_name: planName,
            steps,
        });

        const banner = document.getElementById('rd-result-banner');
        banner.style.display = '';
        banner.className = 'result-banner success';
        document.getElementById('rd-result-icon').textContent = 'check_circle';
        document.getElementById('rd-result-title').textContent = 'Removal Plan Submitted';
        document.getElementById('rd-result-message').textContent =
            `${result.steps} step(s) sent to ${worker}. File: ${result.file}`;
        showToast(`Removal plan submitted to ${worker}`, 'success');
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  TOOL 4: WORKERS                                                        ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function wkGoToStep(step) {
    state.wk.currentStep = step;
    goToToolStep('tool-workers', 'wk', step);
}

async function wkLoadWorkers() {
    try {
        const workers = await API.get('/api/workers');
        state.wk.workers = workers;
        const tbody = document.querySelector('#wk-workers-table tbody');
        document.getElementById('wk-worker-count').textContent = `${workers.length} worker(s)`;
        if (!workers.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="muted">No workers found. Ensure workers are running and have generated a heartbeat.</td></tr>';
            return;
        }
        tbody.innerHTML = workers.map(w => {
            const alive = w.alive;
            const busy = w.busy;
            const statusBadge = alive
                ? (busy
                    ? '<span style="color:#f59e0b;font-weight:600">● Busy</span>'
                    : '<span style="color:#22c55e;font-weight:600">● Active</span>')
                : '<span style="color:#ef4444;font-weight:600">● Offline</span>';
            const modeBadge = w.debug
                ? '<span class="pos-badge" style="background:#f59e0b;color:#000">DEBUG</span>'
                : '<span class="pos-badge" style="background:#22c55e;color:#000">LIVE</span>';
            const checked = state.wk.selectedWorker === w.worker ? 'checked' : '';
            const age = w.age_seconds < 60 ? `${Math.round(w.age_seconds)}s ago` : `${Math.round(w.age_seconds / 60)}m ago`;
            return `<tr class="${!alive ? 'muted' : ''}" style="cursor:pointer" data-worker="${escapeHtml(w.worker)}">
                <td><input type="radio" name="wk-select" class="wk-radio" value="${escapeHtml(w.worker)}" ${checked} ${!alive ? 'disabled' : ''}></td>
                <td><strong>${escapeHtml(w.worker)}</strong></td>
                <td>${statusBadge}</td>
                <td>${modeBadge}</td>
                <td>${w.pending_plans || 0}</td>
                <td>${w.pending_tasks || 0}</td>
                <td>${w.done_tasks || 0}</td>
                <td>${w.error_tasks || 0}</td>
                <td>${age}</td>
            </tr>`;
        }).join('');

        // Click row to select radio
        tbody.querySelectorAll('tr[data-worker]').forEach(row => {
            row.addEventListener('click', () => {
                const radio = row.querySelector('.wk-radio');
                if (radio && !radio.disabled) {
                    radio.checked = true;
                    state.wk.selectedWorker = radio.value;
                    // Highlight selected row
                    tbody.querySelectorAll('tr[data-worker]').forEach(r => r.classList.remove('row-selected'));
                    row.classList.add('row-selected');
                    wkStartLiveLog(radio.value);
                }
            });
        });
    } catch (e) {
        showToast('Failed to load workers: ' + e.message, 'error');
    }
}

function wkRenderPlanTable() {
    const tbody = document.querySelector('#wk-plan-table tbody');
    const steps = state.wk.planSteps;
    document.getElementById('btn-wk-submit-plan').disabled = steps.length === 0;
    if (!steps.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted">No steps added yet</td></tr>';
        return;
    }
    tbody.innerHTML = steps.map((s, i) => `<tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(s.repo)}</td>
        <td>${escapeHtml(s.operation)}</td>
        <td style="font-family:monospace;font-size:13px">${escapeHtml(s.command)}</td>
        <td><button class="btn btn-outline btn-sm wk-remove-step" data-idx="${i}" title="Remove">
            <span class="material-icons-outlined" style="font-size:16px">close</span></button></td>
    </tr>`).join('');
    tbody.querySelectorAll('.wk-remove-step').forEach(btn => {
        btn.addEventListener('click', () => {
            state.wk.planSteps.splice(parseInt(btn.dataset.idx), 1);
            wkRenderPlanTable();
        });
    });
}

function wkAddStep() {
    const repo = document.getElementById('wk-step-repo').value;
    const operation = document.getElementById('wk-step-operation').value;
    const command = document.getElementById('wk-step-command').value.trim();
    if (!command) { showToast('Command is required', 'warning'); return; }
    state.wk.planSteps.push({ repo, operation, command });
    document.getElementById('wk-step-command').value = '';
    wkRenderPlanTable();
}

async function wkSubmitPlan() {
    const worker = state.wk.selectedWorker;
    if (!worker) { showToast('No worker selected', 'warning'); return; }
    if (!state.wk.planSteps.length) { showToast('Add at least one step', 'warning'); return; }

    const planName = document.getElementById('wk-plan-name').value.trim()
        || `plan_${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;

    const btn = document.getElementById('btn-wk-submit-plan');
    btn.disabled = true; btn.classList.add('loading');
    try {
        const result = await API.post('/api/workers/plan', {
            worker,
            plan_name: planName,
            steps: state.wk.planSteps,
        });
        const banner = document.getElementById('wk-plan-result-banner');
        banner.style.display = '';
        banner.className = 'result-banner success';
        document.getElementById('wk-plan-result-icon').textContent = 'check_circle';
        document.getElementById('wk-plan-result-title').textContent = 'Plan Submitted';
        document.getElementById('wk-plan-result-message').textContent =
            `${result.steps} step(s) sent to ${worker}. File: ${result.file}`;
        showToast(`Plan submitted to ${worker}`, 'success');
        state.wk.planSteps = [];
        wkRenderPlanTable();
        // Allow quick jump to tasks/logs
        setTimeout(() => {
            wkLoadTasks();
            wkLoadLogs();
            wkGoToStep(3);
        }, 1500);
    } catch (e) {
        showToast('Failed to submit plan: ' + e.message, 'error');
    } finally { btn.classList.remove('loading'); btn.disabled = false; }
}

// ─── Live Log ──────────────────────────────────────────────────────────

function wkStartLiveLog(worker) {
    wkStopLiveLog();
    const panel = document.getElementById('wk-live-log-panel');
    panel.style.display = '';
    document.getElementById('wk-live-log-worker').textContent = worker;
    document.getElementById('wk-live-log-content').textContent = 'Loading…';
    wkFetchLiveLog(worker);
    state.wk.liveLogTimer = setInterval(() => {
        if (document.getElementById('wk-live-log-auto')?.checked) {
            wkFetchLiveLog(worker);
        }
    }, 3000);
}

function wkStopLiveLog() {
    if (state.wk.liveLogTimer) {
        clearInterval(state.wk.liveLogTimer);
        state.wk.liveLogTimer = null;
    }
}

async function wkFetchLiveLog(worker) {
    try {
        const data = await API.get(`/api/workers/${encodeURIComponent(worker)}/log-tail?lines=80`);
        const pre = document.getElementById('wk-live-log-content');
        const wasAtBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 30;
        pre.textContent = data.lines.join('\n');
        document.getElementById('wk-live-log-status').textContent =
            `${data.total_lines} total lines`;
        if (wasAtBottom) pre.scrollTop = pre.scrollHeight;
    } catch (e) {
        document.getElementById('wk-live-log-content').textContent = 'Failed to load log: ' + e.message;
    }
}


async function wkLoadTasks() {
    const worker = state.wk.selectedWorker;
    if (!worker) return;
    document.getElementById('wk-tasks-worker-name').textContent = worker;
    try {
        const tasks = await API.get(`/api/workers/${encodeURIComponent(worker)}/tasks`);
        document.getElementById('wk-tasks-count').textContent = `${tasks.length} task(s)`;
        const tbody = document.querySelector('#wk-tasks-table tbody');
        if (!tasks.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="muted">No tasks</td></tr>';
            return;
        }
        tbody.innerHTML = tasks.map(t => {
            let statusBadge;
            if (t.suffix === '.done') statusBadge = '<span style="color:#22c55e">✓ Done</span>';
            else if (t.suffix === '.error') statusBadge = '<span style="color:#ef4444">✗ Error</span>';
            else if (t.suffix === '.debug') statusBadge = '<span style="color:#f59e0b">⊘ Debug</span>';
            else statusBadge = '<span style="color:#3b82f6">⏳ Pending</span>';
            const date = new Date(t.modified).toLocaleString();
            return `<tr><td style="font-family:monospace;font-size:13px">${escapeHtml(t.name)}</td><td>${statusBadge}</td><td>${date}</td></tr>`;
        }).join('');
    } catch (e) {
        showToast('Failed to load tasks: ' + e.message, 'error');
    }
}

async function wkLoadLogs() {
    const worker = state.wk.selectedWorker;
    if (!worker) return;
    document.getElementById('wk-logs-worker-name').textContent = worker;
    try {
        const logs = await API.get(`/api/workers/${encodeURIComponent(worker)}/logs`);
        document.getElementById('wk-logs-count').textContent = `${logs.length} log(s)`;
        const tbody = document.querySelector('#wk-logs-table tbody');
        if (!logs.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="muted">No logs</td></tr>';
            return;
        }
        tbody.innerHTML = logs.map(l => {
            const date = new Date(l.modified).toLocaleString();
            return `<tr>
                <td style="font-family:monospace;font-size:13px">${escapeHtml(l.name)}</td>
                <td>${date}</td>
                <td><button class="btn btn-outline btn-sm wk-view-log" data-name="${escapeHtml(l.name)}" title="View">
                    <span class="material-icons-outlined" style="font-size:16px">visibility</span></button></td>
            </tr>`;
        }).join('');
        tbody.querySelectorAll('.wk-view-log').forEach(btn => {
            btn.addEventListener('click', () => wkViewLog(btn.dataset.name));
        });
    } catch (e) {
        showToast('Failed to load logs: ' + e.message, 'error');
    }
}

async function wkViewLog(filename) {
    const worker = state.wk.selectedWorker;
    if (!worker) return;
    try {
        const data = await API.get(`/api/workers/${encodeURIComponent(worker)}/logs/${encodeURIComponent(filename)}`);
        document.getElementById('log-modal-title').textContent = filename;
        document.getElementById('log-modal-body').textContent = data.content;
        document.getElementById('log-modal').style.display = '';
    } catch (e) {
        showToast('Failed to load log: ' + e.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    // ── Tool navigation ──
    document.querySelectorAll('.nav-link').forEach(el => {
        el.addEventListener('click', (e) => { e.preventDefault(); switchTool(el.dataset.tool); });
    });

    // ── Tool 1: Create Policy ──
    cpLoadFolders();
    document.getElementById('cp-folder-select').addEventListener('change', e => cpLoadFileList(e.target.value));
    document.getElementById('file-select').addEventListener('change', e => cpSelectFile(e.target.value));
    document.getElementById('btn-refresh-files').addEventListener('click', () => {
        cpLoadFolders();
        const folder = document.getElementById('cp-folder-select').value;
        if (folder) cpLoadFileList(folder);
    });
    document.getElementById('cp-asa-check').addEventListener('change', e => {
        state.cp.isASA = e.target.checked;
        cpRenderFileViewer();
    });
    document.getElementById('btn-add-field').addEventListener('click', () => cpAddField());
    document.getElementById('btn-prev-page').addEventListener('click', () => {
        if (state.cp.currentPage > 0) { state.cp.currentPage--; cpRenderFileViewer(); cpUpdatePageIndicator(); }
    });
    document.getElementById('btn-next-page').addEventListener('click', () => {
        if (state.cp.fileData && state.cp.currentPage < state.cp.fileData.total_pages - 1) {
            state.cp.currentPage++; cpRenderFileViewer(); cpUpdatePageIndicator();
        }
    });
    document.getElementById('btn-step1-next').addEventListener('click', cpExtractFields);
    document.getElementById('btn-step2-back').addEventListener('click', () => cpGoToStep(1));
    document.getElementById('btn-step2-next').addEventListener('click', () => cpGoToStep(3));
    document.getElementById('btn-step3-back').addEventListener('click', () => cpGoToStep(2));
    document.getElementById('btn-step3-next').addEventListener('click', () => cpGoToStep(4));
    document.getElementById('btn-step4-back').addEventListener('click', () => cpGoToStep(3));
    document.getElementById('btn-generate').addEventListener('click', cpGeneratePolicy);
    document.getElementById('policy-name').addEventListener('input', cpUpdatePolicySummary);
    document.getElementById('content-class').addEventListener('input', cpUpdatePolicySummary);
    document.getElementById('btn-step5-back').addEventListener('click', () => cpGoToStep(4));
    document.getElementById('btn-pub-refresh').addEventListener('click', cpLoadGeneratedPolicies);
    document.getElementById('btn-publish').addEventListener('click', cpPublishPolicy);

    // Stepper clicks (Tool 1)
    document.querySelectorAll('#tool-create-policy .step').forEach(el => {
        el.addEventListener('click', () => {
            const step = parseInt(el.dataset.step);
            if (step < state.cp.currentStep) cpGoToStep(step);
        });
    });

    // File viewer click handler — auto-fill LINE and COL into active field
    document.getElementById('file-viewer').addEventListener('click', e => {
        const lineEl = e.target.closest('.file-line');
        if (!lineEl) return;
        const lineNum = parseInt(lineEl.dataset.line);
        const contentEl = lineEl.querySelector('.file-line-content');
        if (!contentEl) return;
        const rect = contentEl.getBoundingClientRect();
        const charW = cpGetCharWidth(contentEl);
        const padding = parseFloat(getComputedStyle(contentEl).paddingLeft) || 0;
        const col = Math.max(1, Math.floor((e.clientX - rect.left - padding) / charW) + 1);

        // Show position badge in status bar
        document.getElementById('viewer-status').innerHTML =
            `<span class="pos-badge">Ln ${lineNum}, Col ${col}</span> ` +
            (state.cp.isASA ? '<span class="pos-badge" style="background:var(--rocket-orange)">ASA</span> ' : '') +
            `Page ${state.cp.currentPage + 1} of ${state.cp.fileData?.total_pages || 1} · ${state.cp.selectedFile || ''}`;

        // Visual cursor: highlight row + column marker
        const viewer = document.getElementById('file-viewer');
        viewer.querySelectorAll('.cursor-line-highlight, .cursor-col-marker').forEach(el => el.remove());
        const rowHL = document.createElement('div');
        rowHL.className = 'cursor-line-highlight';
        rowHL.style.top = lineEl.offsetTop + 'px';
        rowHL.style.height = lineEl.offsetHeight + 'px';
        viewer.appendChild(rowHL);
        const colMark = document.createElement('div');
        colMark.className = 'cursor-col-marker';
        colMark.style.left = (contentEl.offsetLeft + (col - 1) * charW) + 'px';
        colMark.style.top = lineEl.offsetTop + 'px';
        colMark.style.height = lineEl.offsetHeight + 'px';
        viewer.appendChild(colMark);

        // Auto-fill the active field's LINE and COL
        if (state.cp.activeFieldId) {
            const field = state.cp.fields.find(f => f.id === state.cp.activeFieldId);
            if (field) {
                field.line = lineNum;
                field.column = col;
                cpRenderFieldList();
                cpRenderFieldHighlights();
            }
        }
    });

    cpAddField();
    cpRenderFieldList();

    // ── Load repo info bar ──
    loadRepoInfoBar();
    initGlobalAgentShortcut();

    // ── Bind select highlight for all worker/repo selects ──
    bindSelectHighlight('mrc-worker-select');
    bindSelectHighlight('mig-worker-select');
    bindSelectHighlight('rd-worker-select');
    bindSelectHighlight('pub-repo-select');

    // ── Tool 2: MobiusRemoteCLI ──
    document.getElementById('mrc-btn-source').addEventListener('click', () => mrcSelectRepo('source'));
    document.getElementById('mrc-btn-target').addEventListener('click', () => mrcSelectRepo('target'));
    document.getElementById('mrc-worker-select').addEventListener('change', e => {
        state.mrc.selectedWorker = e.target.value || null;
        mrcAdeleteRenderPlan();
        mrcAcreateRenderPlan();
        if (state.mrc.vdrdbxmlDir === 'import') mrcVdrLoadImportFolders();
    });
    document.querySelectorAll('.mrc-op-btn').forEach(btn => {
        btn.addEventListener('click', () => mrcSelectOp(btn.dataset.op));
    });
    document.getElementById('btn-mrc-refresh').addEventListener('click', mrcInit);
    document.getElementById('btn-mrc-adelete-submit').addEventListener('click', mrcAdeleteSubmitPlan);
    // Adelete checkbox interactions
    document.getElementById('btn-mrc-adelete-add-selected').addEventListener('click', mrcAdeleteAddSelectedToPlan);
    // Select-all checkbox for adelete
    document.addEventListener('change', e => {
        if (e.target.classList.contains('mrc-adelete-select-all')) {
            const table = e.target.closest('table');
            table.querySelectorAll('.mrc-adelete-item-check').forEach(c => { c.checked = e.target.checked; });
            mrcAdeleteUpdateAddButton();
        }
        if (e.target.classList.contains('mrc-adelete-item-check')) {
            mrcAdeleteUpdateAddButton();
        }
    });
    // Update plan commands when template textarea is edited
    document.getElementById('mrc-adelete-cmd-template').addEventListener('input', () => {
        // Re-resolve commands for all plan items using the current template text
        for (const item of state.mrc.adeletePlan) {
            item.command = mrcAdeleteResolveCommand(item.cc);
        }
        mrcAdeleteRenderPlan();
    });
    // acreate bindings
    document.getElementById('mrc-ac-cc-header').addEventListener('click', () => mrcAcreateToggleSection('mrc-ac-cc'));
    document.getElementById('mrc-ac-policy-header').addEventListener('click', () => mrcAcreateToggleSection('mrc-ac-policy'));
    document.getElementById('mrc-ac-folder-header').addEventListener('click', () => mrcAcreateToggleSection('mrc-ac-folder'));
    document.getElementById('mrc-ac-list-folder-header').addEventListener('click', () => mrcAcreateToggleSection('mrc-ac-list-folder'));
    document.getElementById('mrc-ac-list-filter').addEventListener('change', () => {
        state.mrc.acreateListFilter = document.getElementById('mrc-ac-list-filter').value || '*';
        const folder = state.mrc.acreateListSelectedFolder;
        if (folder) mrcAcreateListSelectFolder(folder);
    });
    document.getElementById('btn-mrc-ac-generate').addEventListener('click', mrcAcreateGenerate);
    document.getElementById('btn-mrc-acreate-submit').addEventListener('click', mrcAcreateSubmitPlan);
    document.getElementById('mrc-acreate-cmd-template').addEventListener('input', () => {
        for (const item of state.mrc.acreatePlan) {
            item.command = mrcAcreateResolveCommand(item.file);
        }
        mrcAcreateRenderPlan();
    });

    // vdrdbxml bindings
    document.getElementById('mrc-vdr-cc-header').addEventListener('click', () => mrcVdrToggleSection('mrc-vdr-cc'));
    document.getElementById('mrc-vdr-idx-header').addEventListener('click', () => mrcVdrToggleSection('mrc-vdr-idx'));
    document.getElementById('mrc-vdr-ig-header').addEventListener('click', () => mrcVdrToggleSection('mrc-vdr-ig'));
    document.getElementById('mrc-vdr-pol-header').addEventListener('click', () => mrcVdrToggleSection('mrc-vdr-pol'));
    document.getElementById('btn-mrc-vdr-generate').addEventListener('click', mrcVdrGeneratePlan);
    document.getElementById('btn-mrc-vdr-submit').addEventListener('click', mrcVdrSubmitPlan);

    // ── Tool 3: Migrate ──
    document.querySelectorAll('.mig-mode-card').forEach(el => {
        el.addEventListener('click', () => migSelectMode(el.dataset.mode));
    });
    migInit();
    document.getElementById('mig-worker-select').addEventListener('change', e => {
        state.mig.selectedWorker = e.target.value || null;
    });
    document.getElementById('btn-mig-step1-next').addEventListener('click', migStep1Next);
    document.getElementById('btn-mig-step2-back').addEventListener('click', () => migGoToStep(1));
    document.getElementById('btn-mig-step2-next').addEventListener('click', () => migPrepareAndPreview());
    document.getElementById('btn-mig-step3-back').addEventListener('click', () => {
        migGoToStep(state.mig.mode === 'all' ? 1 : 2);
    });
    document.getElementById('btn-mig-submit').addEventListener('click', migSubmitPlan);
    // Select-all checkboxes for each category
    document.querySelectorAll('.mig-select-all').forEach(cb => {
        cb.addEventListener('change', e => {
            const cat = e.target.dataset.cat;
            const table = e.target.closest('table');
            table.querySelectorAll('.mig-item-check').forEach(c => { c.checked = e.target.checked; });
        });
    });

    // ── Tool 3b: Remove Definitions ──
    rdLoadWorkers();
    document.getElementById('rd-worker-select').addEventListener('change', e => {
        state.rd.selectedWorker = e.target.value || null;
    });
    document.querySelectorAll('.rd-repo-btn').forEach(btn => {
        btn.addEventListener('click', () => rdSelectRepo(btn.dataset.repo));
    });
    // Load target items by default
    rdLoadAllCategories();
    document.getElementById('btn-rd-step1-next').addEventListener('click', rdPrepareAndPreview);
    document.getElementById('btn-rd-step2-back').addEventListener('click', () => rdGoToStep(1));
    document.getElementById('btn-rd-submit').addEventListener('click', rdSubmitPlan);
    document.querySelectorAll('.rd-select-all').forEach(cb => {
        cb.addEventListener('change', e => {
            const table = e.target.closest('table');
            table.querySelectorAll('.rd-item-check').forEach(c => { c.checked = e.target.checked; });
        });
    });

    // ── Tool 4: Workers ──
    document.getElementById('btn-wk-refresh').addEventListener('click', wkLoadWorkers);
    document.getElementById('btn-wk-step2-back').addEventListener('click', () => wkGoToStep(1));
    document.getElementById('btn-wk-add-step').addEventListener('click', wkAddStep);
    document.getElementById('wk-step-command').addEventListener('keydown', e => { if (e.key === 'Enter') wkAddStep(); });
    document.getElementById('btn-wk-submit-plan').addEventListener('click', wkSubmitPlan);
    document.getElementById('btn-wk-step3-back').addEventListener('click', () => wkGoToStep(2));
    document.getElementById('btn-wk-refresh-tasks').addEventListener('click', wkLoadTasks);
    document.getElementById('btn-wk-refresh-logs').addEventListener('click', wkLoadLogs);
    document.getElementById('btn-wk-live-log-refresh').addEventListener('click', () => {
        if (state.wk.selectedWorker) wkFetchLiveLog(state.wk.selectedWorker);
    });
    document.getElementById('log-modal-close').addEventListener('click', () => {
        document.getElementById('log-modal').style.display = 'none';
    });

    // Stepper clicks (Tool 4 — Workers)
    document.querySelectorAll('#tool-workers .step').forEach(el => {
        el.addEventListener('click', () => {
            const step = parseInt(el.dataset.step);
            if (step < state.wk.currentStep) wkGoToStep(step);
            if (step === 3 && step <= state.wk.currentStep && state.wk.selectedWorker) {
                wkLoadTasks();
                wkLoadLogs();
                wkGoToStep(3);
            }
        });
    });

    // Initialize default tool (MRC)
    mrcInit();
});
