import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { clone, supportedName, walk } from "./widgets.js";

const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function structure(graph) {
    return JSON.stringify(walk(graph).map(({ node, path }) => ({ path, type: node.type, mode: node.mode,
        inputs: (node.inputs ?? []).filter(i => i.link != null).map(i => [i.name, i.link]),
        outputs: (node.outputs ?? []).map(o => [o.name, [...(o.links ?? [])].sort()]),
    })));
}
async function matchingGraph(record, graph) {
    if (!walk(graph).some(({ node }) => node.type === "PromptArchiveDOCX")) throw new Error("Add Prompt Archive DOCX to this workflow before reloading settings.");
    const response = await api.fetchApi("/prompt-archive/workflow-hash", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(graph.serialize()) });
    if (!response.ok) throw new Error(await response.text());
    if ((await response.json()).workflow_hash !== record.workflow_hash) throw new Error("This generation belongs to a different workflow structure. Open its original workflow to reload. Nothing has changed.");
    if (app.graph !== graph) throw new Error("The open workflow changed. Review the settings again.");
}

export async function previewRecord(record) {
    const graph = app.graph, workflow = app.extensionManager?.workflow?.activeWorkflow, initial = structure(graph);
    await matchingGraph(record, graph);
    if (initial !== structure(graph) || workflow !== app.extensionManager?.workflow?.activeWorkflow) throw new Error("The workflow changed during comparison. Review the settings again.");
    const all = walk(graph), bindings = [], skipped = [], keys = new Set();
    const saved = record.widget_snapshot?.length ? record.widget_snapshot : (record.settings ?? []).flatMap(item => Object.entries(item.inputs).filter(([name]) => supportedName(name)).map(([name, value]) => ({ path: item.node_id.split(":"), type: item.class_type, name, value })));
    for (const setting of record.settings ?? []) for (const name of Object.keys(setting.inputs)) if (!supportedName(name)) skipped.push(`${setting.node_id} · ${setting.class_type}.${name}: no supported widget mapping`);
    for (const item of saved) {
        const node = all.find(entry => equal(entry.path, item.path))?.node;
        const label = `${item.path.join("/")} · ${node?.title || item.type} · ${item.name}`;
        const skip = reason => skipped.push(`${label}: ${reason}`);
        if (!node || node.type !== item.type || !supportedName(item.name)) { skip("node or field does not match"); continue; }
        const widget = node.widgets?.find(w => w.name === item.name);
        if (!widget) { skip("widget missing"); continue; }
        if (node.inputs?.find(i => i.name === item.name)?.link != null) { skip("connected input; its source control supplies this value"); continue; }
        const key = JSON.stringify([item.path, item.name]);
        if (keys.has(key)) continue;
        keys.add(key);
        const values = typeof widget.options?.values === "function" ? widget.options.values() : widget.options?.values;
        if (Array.isArray(values) && !values.some(v => equal(v, item.value))) { skip("saved option is unavailable; the model or LoRA may have moved"); continue; }
        if (typeof widget.value === "number" && (typeof item.value !== "number" || !Number.isFinite(item.value))) { skip("invalid numeric value"); continue; }
        if (typeof item.value === "number" && ((widget.options?.min != null && item.value < widget.options.min) || (widget.options?.max != null && item.value > widget.options.max))) { skip("value is outside current widget bounds"); continue; }
        bindings.push({ node, widget, path: item.path, name: item.name, label, old: clone(widget.value), value: clone(item.value) });
    }
    // Seed mode is reviewed too, rather than changed after confirmation as a side effect.
    for (const { node, path } of all) {
        if (!bindings.some(b => b.node === node && /^(seed|noise_seed)(?:_\d+)?$/.test(b.name))) continue;
        const control = node.widgets?.find(w => w.name === "control_after_generate" || (node.type === "SeedNode" && w.name === "fixed"));
        if (!control) continue;
        const binding = bindings.find(b => b.node === node && b.widget === control);
        if (binding) binding.value = "fixed";
        else bindings.push({ node, widget: control, path, name: control.name, label: `${path.join("/")} · ${node.title || node.type} · Seed behavior`, old: clone(control.value), value: "fixed" });
    }
    const changes = bindings.filter(b => !equal(b.old, b.value));
    return { record, graph, workflow, structure: initial, nodes: all.map(n => n.node), bindings, changes, skipped, unchanged: bindings.length - changes.length, used: false };
}

export async function applyRecord(record, plan, confirmed = false) {
    if (!confirmed || !plan || plan.record !== record || plan.used) throw new Error("Review the settings comparison and explicitly confirm before reloading.");
    const { graph, workflow } = plan;
    const stale = () => app.graph !== graph || app.extensionManager?.workflow?.activeWorkflow !== workflow || structure(graph) !== plan.structure || walk(graph).some((n, i) => n.node !== plan.nodes[i]) || plan.bindings.some(b => !equal(b.widget.value, b.old));
    if (stale()) throw new Error("The graph or its settings changed after comparison. Review again before confirming. Nothing has changed.");
    await matchingGraph(record, graph);
    if (stale()) throw new Error("The graph changed during confirmation. Review again. Nothing has changed.");
    plan.used = true;
    const applied = [];
    graph.beforeChange?.();
    try {
        for (const change of plan.changes) {
            // Native promoted widgets propagate through setters; arbitrary callbacks may rewire nodes.
            change.widget.value = clone(change.value);
            if (!equal(change.widget.value, change.value)) throw new Error(`${change.label}: widget changed the requested value`);
            applied.push(change.label);
        }
        if (structure(graph) !== plan.structure || app.graph !== graph || walk(graph).some((n, i) => n.node !== plan.nodes[i])) throw new Error("A custom widget changed the graph structure; reload was cancelled.");
    } catch (error) {
        for (const change of [...plan.changes].reverse()) change.widget.value = clone(change.old);
        throw error;
    } finally {
        graph.afterChange?.(); graph.setDirtyCanvas(true, true);
    }
    return { applied, skipped: plan.skipped, unchanged: plan.unchanged, notes: record.notes ?? [] };
}
