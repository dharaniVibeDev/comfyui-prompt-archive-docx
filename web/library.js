import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { previewRecord, applyRecord } from "./reload.js";

function el(tag, text, parent, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    parent?.append(node);
    return node;
}
function icon(name) {
    const paths = {
        archive: '<rect x="3" y="3" width="18" height="5" rx="1.5"/><path d="M5 8v12h14V8M9 12h6"/>',
        search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        close: '<path d="m6 6 12 12M6 18 18 6"/>',
        refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M18 18a8 8 0 0 1-14-6"/>',
        folder: '<path d="M3 7V5h6l2 2h10v12H3z"/>',
        copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/>',
        back: '<path d="m12 5-7 7 7 7M5 12h15"/>',
    };
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '1.6'); svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = paths[name] || paths.archive;
    return svg;
}
function button(parent, text, action, className = '', symbol) {
    const node = el('button', undefined, parent, className); node.type = 'button';
    if (symbol) node.append(icon(symbol));
    el('span', text, node);
    if (action) node.onclick = action;
    return node;
}
async function request(path, options) {
    const response = await api.fetchApi(`/prompt-archive/${path}`, options);
    if (!response.ok) throw new Error(await response.text());
    return response.json();
}
const modelName = name => name ? name.split(/[\\/]/).pop().replace(/\.safetensors$/i, '') : 'Model unavailable';
const dateLabel = value => new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
const display = value => value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);

function previewImage(parent, record, small = false) {
    const frame = el('div', undefined, parent, small ? 'pa-thumbnail' : 'pa-preview');
    const image = el('img', undefined, frame);
    image.alt = `Archived image from ${record.workflow_name}`;
    image.loading = small ? 'lazy' : 'eager'; image.decoding = 'async';
    image.src = api.apiURL(`/prompt-archive/records/${record.record_id}/preview?size=${small ? 256 : 768}`);
    image.onerror = () => { image.remove(); el('span', 'Preview unavailable', frame, 'pa-muted'); };
    return frame;
}

function reviewSettings(record, owner, onApplied) {
    const dialog = el('dialog', undefined, document.body, 'prompt-archive-review');
    dialog.setAttribute('aria-labelledby', 'pa-review-title');
    const heading = el('div', undefined, dialog, 'pa-review-heading');
    el('h2', 'Review settings', heading).id = 'pa-review-title';
    const cancel = () => { dialog.close(); dialog.remove(); };
    button(heading, 'Cancel', cancel);
    const summary = el('p', 'Comparing with the open workflow…', dialog, 'pa-muted');
    const scroll = el('div', undefined, dialog, 'pa-review-scroll');
    const footer = el('div', undefined, dialog, 'pa-review-footer');
    const confirmation = el('label', undefined, footer, 'pa-confirmation');
    const checked = el('input', undefined, confirmation); checked.type = 'checkbox'; checked.disabled = true;
    el('span', 'I reviewed these changes. Apply them to the open workflow.', confirmation);
    const error = el('p', '', footer, 'pa-error'); error.setAttribute('role', 'alert');
    const apply = button(footer, 'Confirm reload', null, 'pa-primary'); apply.disabled = true;
    checked.onchange = () => { apply.disabled = !checked.checked; };
    dialog.addEventListener('cancel', event => { event.preventDefault(); cancel(); });
    dialog.addEventListener('keydown', event => event.stopPropagation());
    dialog.addEventListener('close', () => { if (dialog.isConnected) dialog.remove(); });
    dialog.showModal();
    previewRecord(record).then(plan => {
        if (!dialog.isConnected || !owner.isConnected) { cancel(); return; }
        summary.textContent = `${plan.changes.length} changes · ${plan.unchanged} already match. Only widget values will be applied.`;
        if (plan.changes.length) {
            const table = el('table', undefined, scroll, 'pa-comparison');
            const head = el('tr', undefined, el('thead', undefined, table));
            for (const text of ['Setting', 'Current workflow', 'Archived value']) el('th', text, head).scope = 'col';
            const body = el('tbody', undefined, table);
            for (const change of plan.changes) {
                const row = el('tr', undefined, body);
                const field = el('th', change.name.replaceAll('_', ' '), row); field.scope = 'row';
                el('small', change.node.title || change.node.type, field);
                field.title = change.label;
                el('pre', display(change.old), el('td', undefined, row));
                el('pre', display(change.value), el('td', undefined, row));
            }
            checked.disabled = false;
        } else el('p', 'Your mapped settings already match this generation.', scroll, 'pa-empty');
        if (plan.skipped.length) {
            const details = el('details', undefined, scroll, 'pa-technical');
            el('summary', `${plan.skipped.length} connected or unsupported fields will be left alone`, details);
            el('pre', plan.skipped.join('\n'), details);
        }
        apply.onclick = async () => {
            if (!checked.checked || !owner.isConnected) return;
            apply.disabled = true; checked.disabled = true;
            try { const result = await applyRecord(record, plan, true); onApplied(result); cancel(); }
            catch (reason) { error.textContent = reason.message; checked.checked = false; summary.textContent = 'Reload was not applied. Close this comparison and review again.'; }
        };
    }).catch(reason => { summary.textContent = 'These settings cannot be applied to the open workflow.'; error.textContent = reason.message; });
    return dialog;
}

export function openBrowser() {
    const existing = document.querySelector('.prompt-archive-browser');
    if (existing) { existing.querySelector('input[type="search"]')?.focus(); return; }
    const previousFocus = document.activeElement;
    const panel = el('section', undefined, document.body, 'prompt-archive-browser');
    panel.setAttribute('aria-label', 'Prompt archive library');
    let controller, timer, loading = 0, selectedId, selection = 0, offset = 0, total = 0, workflowRows = [], currentHash = '', scope = 'all', review;
    const close = () => { clearTimeout(timer); controller?.abort(); review?.close(); panel.remove(); previousFocus?.focus?.(); };
    const header = el('header', undefined, panel, 'pa-header');
    const identity = el('div', undefined, header, 'pa-identity'); identity.append(icon('archive'));
    el('h2', 'Prompt archive', identity);
    const count = el('span', 'Local generation history', identity, 'pa-muted pa-library-count');
    const headerActions = el('div', undefined, header, 'pa-actions');
    const refresh = button(headerActions, 'Refresh', () => { offset = 0; loadWorkflows(); load(); }, 'pa-icon-button', 'refresh'); refresh.title = 'Refresh archive history';
    const closeButton = button(headerActions, 'Close', close, 'pa-icon-button', 'close');
    const tools = el('form', undefined, panel, 'pa-toolbar');
    const searchWrap = el('div', undefined, tools, 'pa-search'); searchWrap.append(icon('search'));
    const search = el('input', undefined, searchWrap); search.type = 'search'; search.placeholder = 'Search prompts, models, or workflow names'; search.setAttribute('aria-label', 'Search archive');
    const advanced = el('details', undefined, tools, 'pa-filters');
    el('summary', 'Advanced filters', advanced);
    const filterFields = el('div', undefined, advanced, 'pa-filter-fields');
    const fields = {};
    for (const [key, name, type] of [['checkpoint', 'Model', 'text'], ['loras', 'LoRA', 'text'], ['date_from', 'From date', 'date'], ['date_to', 'To date', 'date'], ['workflow_hash', 'Workflow hash', 'text']]) {
        const label = el('label', name, filterFields);
        const input = el('input', undefined, label); input.type = type; input.name = key; fields[key] = input;
        input.onchange = () => { offset = 0; load(); };
    }
    button(filterFields, 'Clear filters', () => { for (const field of Object.values(fields)) field.value = ''; offset = 0; load(); });
    const body = el('div', undefined, panel, 'pa-body');
    const sidebar = el('nav', undefined, body, 'pa-workflows'); sidebar.setAttribute('aria-label', 'Workflows');
    const library = el('div', undefined, body, 'pa-library');
    const libraryHeading = el('div', undefined, library, 'pa-library-heading');
    const libraryTitle = el('h3', 'All workflows', libraryHeading);
    const status = el('span', 'Loading…', libraryHeading, 'pa-muted'); status.setAttribute('role', 'status');
    const gallery = el('div', undefined, library, 'pa-gallery'); gallery.setAttribute('aria-label', 'Archived generations');
    const paging = el('div', undefined, library, 'pa-paging');
    const prev = button(paging, 'Previous', () => { offset = Math.max(0, offset - 48); load(); });
    const pageLabel = el('span', '', paging, 'pa-muted');
    const next = button(paging, 'Next', () => { offset += 48; load(); });
    const inspector = el('aside', undefined, body, 'pa-inspector'); inspector.setAttribute('aria-label', 'Generation details');
    el('p', 'Select an image to see its prompts and settings.', inspector, 'pa-empty');
    const notice = el('div', '', panel, 'pa-notice'); notice.setAttribute('role', 'status');
    function say(text, isError = false) { notice.textContent = text; notice.classList.toggle('pa-error', isError); }
    async function copy(text, label) {
        try { await navigator.clipboard.writeText(text); say(`${label} copied.`); }
        catch { const area = el('textarea', text, inspector, 'pa-copy-fallback'); area.setAttribute('aria-label', `${label} to copy`); area.focus(); area.select(); say('Press Ctrl+C to copy the selected text.'); }
    }
    function chooseScope(value) { scope = value; offset = 0; panel.dataset.view = 'gallery'; renderNavigation(); load(); }
    function renderNavigation() {
        sidebar.replaceChildren();
        el('span', 'History', sidebar, 'pa-nav-label');
        const nav = (text, value, amount) => {
            const entry = button(sidebar, text, () => chooseScope(value), 'pa-workflow');
            entry.title = text; entry.dataset.scope = value;
            if (value === scope) entry.setAttribute('aria-current', 'page');
            if (amount != null) el('span', String(amount), entry, 'pa-workflow-count');
        };
        nav('All workflows', 'all', workflowRows.reduce((sum, w) => sum + w.count, 0));
        nav('Current workflow', 'current', currentHash ? workflowRows.filter(w => w.hash === currentHash).reduce((sum, w) => sum + w.count, 0) : undefined);
        el('span', 'By workflow', sidebar, 'pa-nav-label');
        workflowRows.forEach(row => nav(row.name, JSON.stringify([row.name, row.hash]), row.count));
    }
    async function loadWorkflows() {
        try { const result = await request('workflows'); if (!panel.isConnected) return; workflowRows = result.workflows; count.textContent = `${workflowRows.reduce((sum, w) => sum + w.count, 0)} generations · Local history`; renderNavigation(); }
        catch (error) { say(`Could not load workflows: ${error.message}`, true); }
    }
    async function show(id, reveal = true) {
        selectedId = id; const token = ++selection;
        if (reveal) panel.dataset.view = 'detail';
        for (const card of gallery.querySelectorAll('.pa-generation')) card.setAttribute('aria-pressed', String(card.dataset.recordId === id));
        inspector.setAttribute('aria-busy', 'true');
        try {
            const record = await request(`records/${encodeURIComponent(id)}`);
            if (token !== selection || !panel.isConnected) return;
            inspector.replaceChildren(); inspector.scrollTop = 0;
            button(inspector, 'Back to gallery', () => { panel.dataset.view = 'gallery'; gallery.querySelector(`[data-record-id="${id}"]`)?.focus(); }, 'pa-back', 'back');
            previewImage(inspector, record);
            const title = el('div', undefined, inspector, 'pa-record-title');
            el('h3', modelName(record.checkpoint), title).title = record.checkpoint || '';
            el('p', record.workflow_name, title, 'pa-workflow-origin');
            el('p', `${dateLabel(record.created_at)} · ${record.width ?? '?'} × ${record.height ?? '?'} · ${Math.ceil((record.docx_bytes || 0) / 1024)} KB DOCX`, title, 'pa-muted');
            const actions = el('div', undefined, inspector, 'pa-record-actions');
            button(actions, 'Copy prompt', () => copy(record.positive_prompt ?? '', 'Positive prompt'), '', 'copy').disabled = record.positive_prompt == null;
            const reload = button(actions, 'Reload settings', () => { review = reviewSettings(record, panel, result => { say(`${result.applied.length} settings reloaded in the current workflow. Connections preserved.`); renderReport(result); }); }, 'pa-primary', 'refresh');
            reload.title = 'Compare settings before confirming reload';
            const reportSlot = el('div', undefined, inspector);
            function renderReport(result) {
                reportSlot.replaceChildren();
                const details = el('details', undefined, reportSlot, 'pa-technical');
                el('summary', `${result.applied.length} changed · ${result.unchanged} already matched · Reload report`, details);
                el('pre', ['CHANGED', ...result.applied, '', 'LEFT ALONE', ...result.skipped, '', 'CAPTURE NOTES', ...result.notes].join('\n'), details);
            }
            const prompts = el('div', undefined, inspector, 'pa-prompts');
            for (const [key, name] of [['positive_prompt', 'Positive prompt'], ['negative_prompt', 'Negative prompt'], ['camera_prompt', 'Camera'], ['lighting_prompt', 'Lighting']]) {
                const section = el('details', undefined, prompts, 'pa-prompt'); section.open = key === 'positive_prompt';
                const summary = el('summary', name, section);
                if (record[key] == null) el('span', 'Not captured', summary, 'pa-muted');
                const text = record[key] == null ? 'No separate text was captured for this field.' : record[key] === '' ? 'Empty / zero conditioning' : record[key];
                el('pre', text, section);
                if (record[key]) button(section, `Copy ${name.toLowerCase()}`, () => copy(record[key], name), 'pa-text-button');
            }
            if (record.positive_prompt == null) {
                const sources = (record.settings ?? []).filter(source => source.class_type.includes('PrimitiveString') && typeof source.inputs?.value === 'string' && source.inputs.value);
                if (sources.length) {
                    const section = el('details', undefined, prompts, 'pa-prompt'); section.open = true;
                    el('summary', `Captured source text · ${sources.length} inputs`, section);
                    el('p', 'The final generated prompt was not stored in this record. These are the original captured inputs, without rewriting.', section, 'pa-source-note pa-muted');
                    for (const source of sources) {
                        el('h4', source.title || `Text node ${source.node_id}`, section, 'pa-source-title');
                        el('pre', source.inputs.value, section);
                        button(section, 'Copy source text', () => copy(source.inputs.value, 'Source text'), 'pa-text-button');
                    }
                }
            }
            const settings = el('dl', undefined, inspector, 'pa-settings');
            for (const [label, value] of [['Seed', record.seed], ['Steps', record.steps], ['CFG', record.cfg], ['Sampler', record.sampler], ['Scheduler', record.scheduler], ['Dimensions', `${record.width ?? '?'} × ${record.height ?? '?'}`], ['Batch size', record.batch_size], ['Checkpoint / model', record.checkpoint]]) {
                const item = el('div', undefined, settings); el('dt', label, item); el('dd', display(value), item);
            }
            const loras = el('section', undefined, inspector, 'pa-section'); el('h4', 'LoRAs', loras);
            if (!record.loras?.length) el('p', 'No active LoRAs captured', loras, 'pa-muted');
            for (const lora of record.loras ?? []) {
                el('p', modelName(lora.name || lora.lora), loras, 'pa-lora-name');
                el('p', `Model ${display(lora.strength_model ?? lora.strength)} · CLIP ${display(lora.strength_clip)}${lora.enabled === false ? ' · Disabled' : ''}`, loras, 'pa-muted');
            }
            const files = el('section', undefined, inspector, 'pa-section'); el('h4', 'Archive file', files);
            const path = el('input', undefined, files, 'pa-path'); path.value = record.docx_path; path.readOnly = true; path.title = record.docx_path; path.setAttribute('aria-label', 'DOCX file location');
            const fileActions = el('div', undefined, files, 'pa-file-actions');
            async function open(kind) {
                try { await request(`records/${id}/${kind}`, { method: 'POST' }); say(kind === 'open-docx' ? 'DOCX opened in your default document app.' : 'Archive folder opened.'); }
                catch (error) { say(error.message, true); }
            }
            button(fileActions, 'Open DOCX', () => open('open-docx'));
            button(fileActions, 'Open folder', () => open('open-folder'), '', 'folder');
            button(fileActions, 'Copy path', () => copy(record.docx_path, 'File path'), 'pa-text-button');
            const download = el('a', 'Download DOCX', fileActions); download.href = api.apiURL(`/prompt-archive/records/${id}/docx`); download.download = '';
            const technical = el('details', undefined, inspector, 'pa-technical'); el('summary', 'Advanced details', technical);
            const data = el('dl', undefined, technical, 'pa-settings');
            for (const [key, label] of [['workflow_hash', 'Workflow hash'], ['workflow_file_name', 'Workflow file'], ['image_path', 'Original image'], ['record_id', 'Record ID'], ['created_at', 'Timestamp']]) { const item = el('div', undefined, data); el('dt', label, item); el('dd', display(record[key]), item); }
            if (record.notes?.length) el('pre', record.notes.join('\n'), technical);
        } catch (error) { if (token === selection) { inspector.replaceChildren(); el('p', `Could not open this generation: ${error.message}`, inspector, 'pa-empty pa-error'); } }
        finally { if (token === selection) inspector.removeAttribute('aria-busy'); }
    }
    async function load() {
        const token = ++loading; controller?.abort(); controller = new AbortController();
        gallery.setAttribute('aria-busy', 'true'); status.textContent = 'Loading…';
        try {
            const query = new URLSearchParams({ limit: '48', offset: String(offset) });
            if (search.value.trim()) query.set('q', search.value.trim());
            for (const [key, input] of Object.entries(fields)) if (input.value) query.set(key, input.value);
            let title = 'All workflows';
            if (scope === 'current') {
                const hashed = await request('workflow-hash', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(app.graph.serialize()) });
                currentHash = hashed.workflow_hash; query.set('workflow_hash', currentHash); title = 'Current workflow'; renderNavigation();
            } else if (scope !== 'all') {
                const row = workflowRows.find(row => JSON.stringify([row.name, row.hash]) === scope);
                if (row) { query.set('workflow_name_exact', row.name); query.set('workflow_hash', row.hash); title = row.name; }
            }
            const result = await request(`records?${query}`, { signal: controller.signal });
            if (token !== loading || !panel.isConnected) return;
            total = result.total; libraryTitle.textContent = title; libraryTitle.title = title;
            status.textContent = `${total} ${total === 1 ? 'generation' : 'generations'}`;
            gallery.replaceChildren();
            const groups = new Map();
            for (const record of result.records) { const key = JSON.stringify([record.workflow_name, record.workflow_hash]); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(record); }
            for (const records of groups.values()) {
                const section = el('section', undefined, gallery, 'pa-workflow-group');
                const heading = el('div', undefined, section, 'pa-group-heading'); el('h4', records[0].workflow_name, heading);
                const grid = el('div', undefined, section, 'pa-grid');
                for (const record of records) {
                    const card = el('button', undefined, grid, 'pa-generation'); card.type = 'button'; card.dataset.recordId = record.record_id;
                    card.setAttribute('aria-label', `Generation from ${record.workflow_name}, ${dateLabel(record.created_at)}`); card.setAttribute('aria-pressed', String(selectedId === record.record_id));
                    previewImage(card, record, true);
                    const caption = el('div', undefined, card, 'pa-caption');
                    el('strong', modelName(record.checkpoint), caption).title = record.checkpoint || '';
                    el('span', record.workflow_name, caption, 'pa-card-workflow').title = record.workflow_name;
                    const time = el('time', dateLabel(record.created_at), caption); time.dateTime = record.created_at;
                    card.onclick = () => show(record.record_id);
                }
            }
            if (!total) {
                const empty = el('div', undefined, gallery, 'pa-empty'); el('h4', 'No generations found', empty); el('p', 'Try another search or workflow, or clear the advanced filters.', empty);
                selectedId = null; ++selection; inspector.replaceChildren(); el('p', 'Select a generation from your archive.', inspector, 'pa-empty'); panel.dataset.view = 'gallery';
            } else if (!result.records.some(record => record.record_id === selectedId)) show(result.records[0].record_id, false);
            prev.disabled = offset === 0; next.disabled = offset + result.records.length >= total;
            paging.hidden = total <= 48; pageLabel.textContent = total ? `${offset + 1}–${offset + result.records.length} of ${total}` : '';
        } catch (error) { if (error.name !== 'AbortError' && token === loading) { status.textContent = 'Could not load history'; say(error.message, true); } }
        finally { if (token === loading) gallery.removeAttribute('aria-busy'); }
    }
    tools.onsubmit = event => { event.preventDefault(); clearTimeout(timer); offset = 0; load(); };
    search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { offset = 0; load(); }, 220); };
    panel.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Escape') close(); });
    panel.addEventListener('wheel', event => event.stopPropagation());
    renderNavigation();
    loadWorkflows().then(load); search.focus();
}
