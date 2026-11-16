// Pure graph helpers: every transfer is resolved through an actual typed wire.
export const INDEX = "DanbooruTagIndex";
export const SAVED = "DanbooruSavedTags";
export const TYPE = "DANBOORU_TAG_LIBRARY";
export const kind = node => node?.comfyClass || node?.type;
export function linkAt(graph, id) {
    return graph?.links?.get?.(id) ?? graph?.links?.[id];
}
export function sourceFor(node) {
    const input = node.inputs?.find(i => i.name === "tag_library" && i.type === TYPE);
    if (input?.link == null) return null;
    const link = linkAt(node.graph, input.link);
    const source = node.graph?.getNodeById(link?.origin_id);
    return kind(source) === INDEX && source.outputs?.[link.origin_slot]?.type === TYPE ? source : null;
}
export function targetsFor(node) {
    const result = [];
    for (const output of node.outputs || []) {
        if (output.type !== TYPE) continue;
        for (const id of output.links || []) {
            const link = linkAt(node.graph, id);
            const target = node.graph?.getNodeById(link?.target_id);
            if (kind(target) === SAVED && sourceFor(target) === node && !result.includes(target)) result.push(target);
        }
    }
    return result;
}
export const displayText = text => String(text ?? "").replaceAll("_", " ");
export const tagText = entry => displayText(entry.name);

export function shortDescription(description) {
    const lines = [];
    for (const line of String(description ?? "").trim().split(/\r?\n/)) {
        if (!line.trim() || /^\s*(?:#{1,6}\s|h\d\.|[-*]\s|\d+[.)]\s)/.test(line)) break;
        lines.push(line.trim());
    }
    const text = displayText(lines.join(" ")
        .replace(/\[\[([^|\]]+)(?:\|([^\]]+))?\]\]/g, (_, target, label) => label || target)
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/"([^"]+)":https?:\/\/\S+/g, "$1")
        .replace(/\s+/g, " ")).trim();
    if (!text) return "No short description available.";
    if (text.length <= 220) return text;
    const prefix = text.slice(0, 219);
    const space = prefix.lastIndexOf(" ");
    return (space > 150 ? prefix.slice(0, space) : prefix).trimEnd() + "…";
}

// A linked wiki replaces a parent's preview. Keep any extra preview entries,
// with their original source routes, without duplicating the wiki's tags.
export function contextRemainder(context, full, route = []) {
    const present = new Set();
    const collect = entries => entries.forEach(e => { present.add(e.name); collect(e.children || []); });
    collect(full);
    const visit = (entries, parent) => entries.flatMap(entry => {
        const sourceRoute = entry.sourceRoute || [...parent, entry.name];
        const children = visit(entry.children || [], sourceRoute);
        return present.has(entry.name) ? children : [{ ...entry, children, sourceRoute }];
    });
    return visit(context, route);
}
export function savedView(records, query) {
    const q = displayText(query).trim().toLocaleLowerCase();
    const tags = new Map();
    for (const entry of records) {
        const paths = entry.paths?.length ? entry.paths : [[]];
        const text = displayText([entry.name, entry.label, entry.description, ...paths.flat().map(p => p.label)].join(" ")).toLocaleLowerCase();
        if (!q || text.includes(q)) tags.set(entry.key, entry);
    }
    return [...tags.values()].sort((a, b) => tagText(a).localeCompare(tagText(b)));
}
