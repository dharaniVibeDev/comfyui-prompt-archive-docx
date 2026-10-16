import { app } from "../../scripts/app.js";
import { clone, supportedName, walk } from "./widgets.js";
import { openBrowser } from "./library.js";
export { walk } from "./widgets.js";
export { openBrowser } from "./library.js";
export { previewRecord, applyRecord } from "./reload.js";

const TYPE = "PromptArchiveDOCX";
function snapshots(output) {
    const entries = [];
    for (const { node, path } of walk(app.graph)) {
        if (node.type === TYPE) continue;
        const executed = output?.[path.join(":")]?.inputs ?? {};
        for (const widget of node.widgets ?? []) {
            if (!supportedName(widget.name) || widget.type === "button") continue;
            let value = executed[widget.name];
            if (value === undefined || (Array.isArray(value) && value.length === 2 && output?.[value[0]])) value = widget.value;
            if (value === undefined || typeof value === "function") continue;
            entries.push({ path, type: node.type, name: widget.name, value: clone(value) });
        }
    }
    return entries;
}

app.registerExtension({
    name: "PromptArchive.DOCXWorkflowReload",
    setup() {
        const css = document.createElement("link"); css.rel = "stylesheet"; css.href = new URL("./archive.css", import.meta.url).href; document.head.append(css);
        const original = app.graphToPrompt;
        app.graphToPrompt = async function (...args) {
            const result = await original.apply(this, args);
            if (!walk(app.graph).some(({ node }) => node.type === TYPE)) return result;
            result.workflow.extra ??= {};
            const active = app.extensionManager?.workflow?.activeWorkflow;
            result.workflow.extra.prompt_archive = { workflow_name: active?.name || active?.path?.split("/").pop()?.replace(/\.json$/i, ""), workflow_file_name: active?.path || null, widgets: snapshots(result.output) };
            return result;
        };
    },
    nodeCreated(node) {
        if (node.comfyClass !== TYPE && node.type !== TYPE) return;
        node.addWidget("button", "Browse archives / Reload", null, openBrowser, { serialize: false });
        const previous = node.onExecuted;
        node.onExecuted = function (message) {
            previous?.apply(this, arguments);
            this.promptArchiveLastRecords = message.archive_records ?? [];
            const paths = this.promptArchiveLastRecords.map(record => record.docx_path);
            const status = (message.archive_status ?? []).join(" ");
            this.title = paths.length ? `Prompt Archive DOCX · ${paths.length} saved` : "Prompt Archive DOCX";
            app.extensionManager?.toast?.add({ severity: "info", summary: "Prompt Archive DOCX", detail: paths.join("\n") || status, life: 8000 });
        };
    },
});
