export const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
const supported = /^(text|text_g|text_l|prompt|positive|negative|camera_prompt|lighting_prompt|instruction|scene_instruction|value|string|string_a|string_b|delimiter|seed|noise_seed|steps|cfg|guidance|sampler_name|scheduler|width|height|batch_size|ckpt_name|unet_name|clip_name|vae_name|weight_dtype|shift|sampling|lora_name|strength|strength_model|strength_clip|denoise|add_noise|start_at_step|end_at_step|return_with_leftover_noise|control_after_generate|aspect_ratio|resolution|lora_\d+)$/;
export const supportedName = name => supported.test(name) || supported.test(name.replace(/_\d+$/, "")) || ["megapixels", "switch", "fixed"].includes(name);

export function walk(graph, prefix = [], result = []) {
    for (const node of graph?._nodes ?? []) {
        const path = [...prefix, String(node.id)];
        result.push({ node, path });
        if (node.subgraph) walk(node.subgraph, path, result);
    }
    return result;
}
