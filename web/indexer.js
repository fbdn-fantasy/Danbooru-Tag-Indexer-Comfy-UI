import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { INDEX, SAVED, kind, sourceFor, targetsFor, savedView, displayText, tagText, contextRemainder, shortDescription } from "./library.mjs";

const controllers = new Map();
const ROOT = "tag_groups";
const css = document.createElement("link");
css.rel = "stylesheet";
css.href = new URL("./indexer.css", import.meta.url).href;
document.head.append(css);

function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}
function button(text, title, action, className = "dti-button") {
    const b = el("button", className, text);
    b.type = "button";
    b.title = title;
    b.setAttribute("aria-label", title);
    b.addEventListener("click", action);
    return b;
}
async function request(path, data) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);
    let response;
    try { response = await api.fetchApi("/danbooru-indexer" + path, {
        ...(data ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) } : {}),
        cache: "no-store", signal: controller.signal,
    }); } finally { clearTimeout(timeout); }
    let result;
    try { result = await response.json(); } catch { throw new Error("The library server did not respond. Restart ComfyUI and refresh this page."); }
    if (!response.ok) throw new Error(result.error || `Library request failed (${response.status})`);
    return result;
}
function collectionPath(id) { return "/collections/" + encodeURIComponent(id); }
function uuid() {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16));
}
function updateConnections() {
    for (const controller of controllers.values()) controller.connectionStatus();
}
async function refreshCollection(id) {
    await Promise.all([...controllers.values()].filter(c => c.saved && c.id === id).map(c => {
        c.notify("");
        return c.loadSaved();
    }));
    updateConnections();
}

class BrowserNode {
    constructor(node) {
        this.node = node;
        this.saved = kind(node) === SAVED;
        this.records = [];
        this.path = [];
        this.rooted = true;
        this.query = "";
        this.offset = 0;
        this.generation = 0;
        this.savedGeneration = 0;
        this.busy = false;
        this.disposed = false;
        this.starButtons = new Map();
        this.expandedSections = new Set();
        this.expandedSaved = new Set();
        this.pageOutlines = new Map();
        this.treePages = new Map();
        this.treeEpoch = 0;
        this.returnView = null;
        this.root = el("div", "dti-root");
        this.root.setAttribute("aria-label", this.saved ? "Saved tag browser" : "Danbooru tag browser");
        for (const type of ["pointerdown", "mousedown", "dblclick", "keydown", "keyup", "wheel"]) {
            this.root.addEventListener(type, event => event.stopPropagation());
        }
        this.search = el("input", "dti-search");
        this.search.type = "search";
        this.search.placeholder = this.saved ? "Search your saved tags…" : "Search tags and descriptions…";
        this.search.setAttribute("aria-label", this.search.placeholder);
        this.search.addEventListener("input", () => {
            this.query = this.search.value;
            this.generation++;
            clearTimeout(this.searchTimer);
            this.searchTimer = setTimeout(() => this.showList(), 220);
        });
        this.root.append(this.search);
        if (this.saved) this.addCollectionControls();
        this.crumbs = el("nav", "dti-crumbs");
        this.crumbs.setAttribute("aria-label", "Category path");
        this.content = el("div", "dti-content");
        this.message = el("div", "dti-message");
        this.message.setAttribute("role", "status");
        this.footer = el("div", "dti-footer");
        this.status = el("span", "dti-status");
        this.footer.append(this.status, button("↻", "Refresh library and connection", () => this.start()));
        this.root.append(this.crumbs, this.content, this.message, this.footer);
        const widget = node.addDOMWidget("danbooru_browser", "custom", this.root, {
            serialize: false, hideOnZoom: false,
            getMinHeight: () => 350, getHeight: () => "100%",
        });
        // A computeSize override makes LiteGraph treat this as fixed-height.
        // Leave its native DOM computeLayoutSize intact so free space is allocated
        // on both grow and shrink, including when a workflow restores node size.
        widget.serialize = false;
        node.setSize([440, 570]);
        this.renderCrumbs();
    }
    get id() { return this.node.properties.danbooru_collection; }
    addCollectionControls() {
        const bar = el("div", "dti-collection-bar");
        this.collections = el("select", "dti-select");
        this.collections.setAttribute("aria-label", "Saved collection");
        this.collections.addEventListener("change", () => {
            this.node.properties.danbooru_collection = this.collections.value;
            this.path = [];
            this.node.graph?.setDirtyCanvas?.(true, true);
            this.start();
        });
        bar.append(this.collections, button("+", "Create a separate saved collection", () => this.newCollection()));
        this.root.append(bar);
        const tools = el("div", "dti-tools");
        tools.append(button("+ Personal tag", "Add a tag only to this saved collection", () => this.customForm()));
        this.root.append(tools);
    }
    async start() {
        if (this.disposed || !this.node.graph) return;
        this.message.textContent = "";
        this.connectionStatus();
        if (this.saved) {
            if (!this.node.properties.danbooru_collection) this.node.properties.danbooru_collection = uuid();
            await this.loadSaved(true);
        } else await this.showList();
    }
    async loadSaved(ensure = false) {
        const id = this.id, generation = ++this.savedGeneration;
        try {
            this.status.textContent = "Loading saved collection…";
            if (ensure) await request(collectionPath(id), { action: "ensure" });
            const [records, collections] = await Promise.all([request(collectionPath(id)), request("/collections")]);
            if (this.disposed || id !== this.id || generation !== this.savedGeneration) return;
            this.records = records;
            const savedKeys = new Set(records.map(entry => `${id}:${entry.key}`));
            for (const key of this.expandedSaved) {
                if (key.startsWith(`${id}:`) && !savedKeys.has(key)) this.expandedSaved.delete(key);
            }
            this.collections.replaceChildren(...collections.map(c => {
                const option = el("option", "", `${c.title} · ${c.count}`);
                option.value = c.id;
                option.selected = c.id === id;
                return option;
            }));
            this.showList();
            updateConnections();
        } catch (error) { if (!this.disposed && id === this.id && generation === this.savedGeneration) this.fail(error); }
    }
    connectionStatus() {
        if (this.disposed || this.busy) return;
        if (this.saved) {
            this.status.textContent = sourceFor(this.node) ? "● Connected · saves enabled" : "○ Disconnected · saved tags kept";
        } else {
            const targets = targetsFor(this.node);
            this.status.textContent = targets.length ? `● Connected · ${targets.length} saved node${targets.length === 1 ? "" : "s"}` : "○ Connect to Saved Tags to enable stars";
            for (const [b, name] of this.starButtons) this.setStar(b, name);
        }
    }
    fail(error) {
        this.message.textContent = error.message || String(error);
        this.message.classList.add("dti-error");
        this.status.textContent = "! Library error · use ↻ to retry";
    }
    notify(text) {
        this.message.classList.remove("dti-error");
        this.message.textContent = text;
    }
    renderCrumbs() {
        this.crumbs.hidden = this.saved;
        if (this.saved) return;
        this.crumbs.replaceChildren(button("All", "Browse main categories", () => this.navigate([]), "dti-crumb"));
        this.path.forEach((p, i) => {
            this.crumbs.append(el("span", "dti-separator", "›"), button(displayText(p.label), displayText(p.label), () => this.navigate(this.path.slice(0, i + 1)), "dti-crumb"));
        });
    }
    navigate(path, rooted = this.rooted) {
        this.path = path;
        this.rooted = !path.length || rooted;
        this.query = "";
        this.search.value = "";
        this.showList();
    }
    async showList(append = false) {
        const generation = ++this.generation;
        if (!append) { this.treeEpoch++; this.returnView = null; }
        this.renderCrumbs();
        if (!append) {
            this.offset = 0;
            this.starButtons.clear();
            this.content.replaceChildren();
        }
        if (this.saved) {
            const tags = savedView(this.records, this.query);
            for (const tag of tags) this.content.append(this.savedCard(tag));
            if (!tags.length) this.empty(this.query ? "No saved tags match your search." : "Star a tag in the connected Index, or add your own personal tag.");
            return;
        }
        const loading = el("div", "dti-empty", "Loading index… First use prepares the bundled database.");
        this.content.append(loading);
        try {
            if (!this.query) {
                const page = this.path.at(-1)?.id || ROOT;
                const outline = await this.fetchOutline(page);
                if (generation !== this.generation || this.disposed) return;
                loading.remove();
                this.renderOutline(outline, { page });
                this.connectionStatus();
                return;
            }
            const params = new URLSearchParams({ q: this.query, offset: String(this.offset) });
            const result = await request("/catalog?" + params);
            if (generation !== this.generation || this.disposed) return;
            loading.remove();
            this.renderOutline(result.items.map(item => ({ ...item, children: [], lazy: item.kind !== "tag" })), { page: null, append, search: true });
            if (!result.items.length && !append) this.empty(this.query ? "No matches. Try another name or description." : "No entries in this category.");
            if (result.more) {
                const more = button("Load more", "Load the next 60 results", () => { more.remove(); this.offset += 60; this.showList(true); }, "dti-button dti-more");
                this.content.append(more);
            }
            this.connectionStatus();
        } catch (error) {
            if (generation !== this.generation || this.disposed) return;
            loading.remove();
            this.fail(error);
        }
    }
    empty(text) { this.content.append(el("div", "dti-empty", text)); }
    async fetchOutline(page) {
        if (!this.pageOutlines.has(page)) {
            const result = await request("/outline?" + new URLSearchParams({ name: page }));
            this.pageOutlines.set(page, result);
        }
        return this.pageOutlines.get(page);
    }
    renderOutline(outline, options = {}) {
        const { page = ROOT, append = false, search = false } = options;
        const epoch = this.treeEpoch;
        const scope = `${page || "search"}:${search ? this.query : ""}`;
        if (!append) this.content.replaceChildren();
        if (!search) {
            const controls = el("div", "dti-outline-tools");
            const expand = (entries, prefix = scope) => {
                entries.forEach((entry, i) => {
                    const key = `${prefix}/${i}`;
                    const loaded = this.treePages.get(key);
                    if (entry.children.length || (entry.kind === "section" && !entry.lazy) || loaded) this.expandedSections.add(key);
                    expand(loaded?.entries || entry.children, key);
                });
            };
            controls.append(el("span", "dti-outline-title", "Categories"),
                button("Expand all", "Expand all loaded sections", () => { expand(outline); this.renderOutline(outline, options); }, "dti-text-button"),
                button("Collapse all", "Collapse all sections", () => { this.expandedSections.clear(); this.renderOutline(outline, options); }, "dti-text-button"));
            this.content.append(controls);
        }
        const list = (entries, route = [], prefix = scope, owner = page, ancestors = page ? [page] : []) => {
            const ul = el("ul", "dti-outline");
            entries.forEach((entry, i) => {
                const key = `${prefix}/${i + (search && prefix === scope ? this.offset : 0)}`;
                const nextRoute = entry.sourceRoute || [...route, entry.name];
                const li = el("li", "dti-outline-item");
                li.dataset.name = entry.name;
                const row = el("div", "dti-outline-row");
                const isTag = entry.kind === "tag";
                // An explicit category sublist belongs to the current wiki.
                // Do not replace it with the linked category's different page.
                const wiki = (entry.kind === "group" && !entry.children.length) || entry.lazy || (isTag && entry.expandable);
                const loop = wiki && ancestors.includes(entry.name);
                const branch = !isTag || entry.children.length > 0 || wiki;
                const body = el("div", "dti-outline-body");
                body.hidden = !this.expandedSections.has(key);
                let populated = false, pending = false;
                let label;
                const sync = () => {
                    toggle.textContent = body.hidden ? "›" : "⌄";
                    toggle.setAttribute("aria-label", `${body.hidden ? "Expand" : "Collapse"} ${displayText(entry.label)}`);
                    toggle.setAttribute("aria-expanded", String(!body.hidden));
                    label?.setAttribute("aria-expanded", String(!body.hidden));
                };
                const populate = async () => {
                    if (pending || populated) return;
                    pending = true;
                    try {
                        let loaded = this.treePages.get(key);
                        if (wiki && !loaded && !loop) {
                            body.replaceChildren(el("div", "dti-outline-description", "Loading full wiki list…"));
                            const children = await this.fetchOutline(entry.name);
                            if (epoch !== this.treeEpoch || this.disposed) return;
                            loaded = { page: entry.name, entries: children };
                            this.treePages.set(key, loaded);
                            // Reveal headings immediately, but never automatically
                            // follow linked tag pages (which can refer back here).
                            const openHeadings = (entries, prefix) => entries.forEach((child, j) => {
                                if (child.kind !== "section") return;
                                const childKey = `${prefix}/${j}`;
                                this.expandedSections.add(childKey);
                                openHeadings(child.children, childKey);
                            });
                            openHeadings(children, key);
                        }
                        body.replaceChildren();
                        if (loop) body.append(el("div", "dti-outline-description", "This page is already expanded above."));
                        else {
                            if (entry.description) {
                                const text = el("div", "dti-outline-description");
                                this.renderDescription(text, entry.description);
                                body.append(text);
                            }
                            const children = loaded?.entries || entry.children;
                            body.append(list(children, loaded ? [] : nextRoute, key, loaded?.page || owner, [...ancestors, entry.name]));
                            if (loaded && entry.children.length) {
                                const extras = contextRemainder(entry.children, children, nextRoute);
                                if (extras.length) {
                                    body.append(list(extras, nextRoute, `${key}/context`, owner, [...ancestors, entry.name]));
                                }
                            }
                            if (!children.length && !entry.description) body.append(el("div", "dti-outline-description", "No listed entries in this indexed section."));
                        }
                        populated = true;
                        this.connectionStatus();
                    } catch (error) {
                        body.replaceChildren(el("div", "dti-outline-description", error.message), button("Retry", "Retry loading category", () => populate()));
                    } finally { pending = false; }
                };
                const toggle = button(body.hidden ? "›" : "⌄", `${body.hidden ? "Expand" : "Collapse"} ${displayText(entry.label)}`, () => {
                    body.hidden = !body.hidden;
                    if (body.hidden) this.expandedSections.delete(key);
                    else { this.expandedSections.add(key); void populate(); }
                    sync();
                }, "dti-outline-toggle");
                toggle.setAttribute("aria-expanded", String(!body.hidden));
                if (branch) row.append(toggle);
                else row.append(el("span", "dti-outline-dot", "·"));
                if (isTag) {
                    const tag = this.tagRow(entry, owner ? { page: owner, route: nextRoute } : null, branch ? () => toggle.click() : null);
                    label = tag.querySelector(".dti-tag-name");
                    if (branch) label.setAttribute("aria-expanded", String(!body.hidden));
                    row.append(tag);
                } else {
                    label = button(displayText(entry.label), `${entry.kind === "section" ? "Toggle section" : "Expand category"} ${displayText(entry.label)}`, () => toggle.click(), `dti-outline-label${entry.kind === "section" ? " is-section" : ""}`);
                    label.setAttribute("aria-expanded", String(!body.hidden));
                    row.append(label);
                }
                if (entry.note) row.append(el("span", "dti-outline-note", displayText(entry.note)));
                li.append(row);
                if (branch) { li.append(body); if (!body.hidden) void populate(); }
                ul.append(li);
            });
            return ul;
        };
        this.content.append(list(outline));
    }
    folderRow(label, count, action, relation = "child") {
        label = displayText(label);
        const row = button("", `Open ${label}`, action, "dti-folder");
        row.append(el("span", "dti-folder-icon", "▱"), el("span", "dti-label", label), el("span", "dti-count", String(count)), el("span", "", "›"));
        if (relation !== "child") row.title += relation === "related" ? " · Related tags" : " · See also";
        return row;
    }
    async copyTag(entry) {
        const text = tagText(entry);
        try {
            if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
            else throw new Error("Clipboard API unavailable");
        } catch {
            // Browsers may withhold the Clipboard API on local-network HTTP.
            const input = el("textarea", "dti-copy-buffer");
            input.value = text;
            this.root.append(input);
            input.focus();
            input.select();
            let copied = false;
            try { copied = document.execCommand("copy"); } catch { /* show manual fallback */ }
            input.remove();
            if (!copied) { this.notify(`Select “${text}” and press Ctrl+C to copy.`); return; }
        }
        this.notify(`Copied: ${text}`);
    }
    savedCard(entry) {
        const card = el("article", "dti-saved-card");
        const text = tagText(entry);
        const key = `${this.id}:${entry.key}`;
        card.setAttribute("aria-label", `Saved tag: ${text}`);
        const header = el("div", "dti-saved-header");
        const summary = el("div", "dti-saved-summary", shortDescription(entry.description));
        const details = el("div", "dti-saved-details");
        let populated = false;
        const update = () => {
            const open = this.expandedSaved.has(key);
            arrow.textContent = open ? "⌄" : "›";
            arrow.setAttribute("aria-label", `${open ? "Collapse" : "Expand"} saved details for ${text}`);
            arrow.setAttribute("aria-expanded", String(open));
            tag.querySelector(".dti-tag-name").setAttribute("aria-expanded", String(open));
            summary.hidden = open;
            details.hidden = !open;
            if (open && !populated) {
                for (const path of entry.paths || []) {
                    if (path.length) details.append(el("div", "dti-path", path.map(p => displayText(p.label)).join(" › ")));
                }
                const description = el("div", "dti-description");
                this.renderDescription(description, entry.description || "No description was recorded for this tag.");
                details.append(description);
                if (entry.custom) details.append(button("Edit personal tag", `Edit ${text}`, () => this.customForm(entry), "dti-button"));
                populated = true;
            }
        };
        const arrow = button("›", `Expand saved details for ${text}`, () => {
            if (this.expandedSaved.has(key)) this.expandedSaved.delete(key);
            else this.expandedSaved.add(key);
            update();
        }, "dti-outline-toggle dti-saved-toggle");
        const tag = this.tagRow(entry, null, () => arrow.click());
        tag.querySelector(".dti-tag-name").setAttribute("aria-label", `Toggle saved tag ${text}`);
        header.append(arrow, tag);
        card.append(header, summary, details);
        update();
        return card;
    }
    tagRow(entry, browsePath = null, expand = null) {
        const row = el("div", "dti-tag");
        row.dataset.dtiName = entry.name;
        const text = tagText(entry);
        const name = button(text, expand ? `Expand tag ${text}` : `Read about ${text}`, expand || (() => this.details(entry, browsePath)), "dti-tag-name");
        row.append(name);
        if (entry.custom) row.append(el("span", "dti-badge", "Personal"));
        if (entry.relation && entry.relation !== "child") row.append(el("span", "dti-relation", entry.relation === "related" ? "Related" : "See also"));
        row.append(button("Copy", `Copy ${text}`, () => this.copyTag(entry), "dti-button dti-copy"));
        if (this.saved) row.append(button("★", `Remove ${text} from this collection`, () => this.remove(entry), "dti-star is-saved"));
        else {
            const star = button("☆", `Save ${text}`, () => this.toggle(entry.name, browsePath), "dti-star");
            if (entry.kind !== "tag") return row;
            star.dataset.dtiTag = entry.name;
            this.starButtons.set(star, entry.name);
            this.setStar(star, entry.name);
            row.append(star);
        }
        return row;
    }
    connectedCollections() {
        const result = new Map();
        for (const target of targetsFor(this.node)) {
            const controller = controllers.get(target);
            if (controller?.id) result.set(controller.id, controller);
        }
        return [...result.values()];
    }
    setStar(star, name) {
        const targets = this.connectedCollections();
        const all = targets.length > 0 && targets.every(t => t.records.some(r => r.key === "catalog:" + name));
        star.textContent = all ? "★" : "☆";
        star.classList.toggle("is-saved", all);
        star.disabled = !targets.length || this.busy;
        star.title = !targets.length ? "Wire this Index directly to a Saved Tags node first" : `${all ? "Unsave" : "Save"} in ${targets.length} connected collection${targets.length === 1 ? "" : "s"}`;
        star.setAttribute("aria-label", star.title + ": " + displayText(name));
        star.setAttribute("aria-pressed", String(all));
    }
    async toggle(name, browsePath = null) {
        const targets = this.connectedCollections();
        if (!targets.length || this.busy) return;
        const remove = targets.every(t => t.records.some(r => r.key === "catalog:" + name));
        this.busy = true;
        this.status.textContent = "Saving…";
        for (const [b, n] of this.starButtons) this.setStar(b, n);
        const ids = targets.map(t => t.id);
        let failure;
        try {
            for (const target of targets) {
                if (!targetsFor(this.node).includes(target.node) || !ids.includes(target.id)) throw new Error("Connection changed. Reconnect and retry.");
                await request(collectionPath(target.id), remove ? { action: "remove", key: "catalog:" + name } : { action: "save", name, ...(Array.isArray(browsePath) ? { path: browsePath } : { context: browsePath }) });
            }
        } catch (error) { failure = error; }
        finally {
            await Promise.all(ids.map(refreshCollection));
            this.busy = false;
            updateConnections();
            if (failure) this.fail(failure);
            else this.notify(remove ? "Removed from the connected collection." : "Saved with parent folders and description.");
        }
    }
    async remove(entry) {
        if (this.busy) return;
        this.busy = true;
        const id = this.id;
        try {
            await request(collectionPath(id), { action: "remove", key: entry.key });
            await refreshCollection(id);
            this.notify("Removed from this collection.");
        } catch (error) { this.fail(error); }
        finally { this.busy = false; updateConnections(); }
    }
    backToList() {
        if (!this.returnView) { this.showList(); return; }
        const view = this.returnView;
        this.returnView = null;
        ++this.generation;
        this.content.replaceChildren(...view.nodes);
        this.content.scrollTop = view.scroll;
        this.starButtons = new Map([...this.content.querySelectorAll("button[data-dti-tag]")].map(b => [b, b.dataset.dtiTag]));
        this.connectionStatus();
    }
    async details(entry, browsePath = null) {
        if (!this.returnView) this.returnView = { nodes: [...this.content.childNodes], scroll: this.content.scrollTop, stars: new Map(this.starButtons) };
        const generation = ++this.generation;
        this.content.replaceChildren(el("div", "dti-empty", "Loading description…"));
        try {
            const detail = this.saved ? entry : await request("/detail?" + new URLSearchParams({ name: entry.name }));
            if (generation !== this.generation || this.disposed) return;
            if (!this.saved && detail.kind !== "tag") {
                this.navigate(detail.name === ROOT ? [] : [{ id: detail.name, label: detail.label }], false);
                return;
            }
            this.starButtons.clear();
            this.content.replaceChildren(button("‹ Back to results", "Return to tags", () => this.backToList(), "dti-button dti-back"), this.tagRow(detail, browsePath));
            if (detail.paths) {
                for (const path of detail.paths) this.content.append(el("div", "dti-path", path.map(p => displayText(p.label)).join(" › ") || "All saved tags"));
            } else if (detail.parents?.length) {
                const parents = el("div", "dti-parent-links");
                for (const parent of detail.parents) parents.append(button(displayText(parent.label), `Browse ${displayText(parent.label)}`, () => this.navigate([{ id: parent.name, label: parent.label }], false), "dti-crumb"));
                this.content.append(parents);
            }
            const body = el("div", "dti-description");
            this.renderDescription(body, detail.description || "No description was recorded for this tag.");
            this.content.append(body);
            const actions = el("div", "dti-tools");
            if (!this.saved && detail.children) actions.append(button("Browse linked entries", "Browse this entry's tags and references", () => this.navigate([{ id: detail.name, label: detail.label }], false)));
            if (detail.custom) actions.append(button("Edit personal tag", "Edit this personal tag's folder and description", () => this.customForm(detail)));
            this.content.append(actions);
        } catch (error) { if (generation === this.generation) this.fail(error); }
    }
    renderDescription(body, text) {
        // Text-only rendering: wiki content can never inject markup or scripts.
        for (const line of text.split("\n")) {
            const p = el("div", /^h[1-6]\.|^## /.test(line) ? "dti-heading" : "dti-paragraph");
            const clean = line.replace(/^h[1-6]\.\s*|^## /, "");
            for (const part of clean.split(/(\[\[[^\]]+\]\])/g)) {
                const match = part.match(/^\[\[([^|\]]+)(?:\|([^\]]*))?\]\]$/);
                if (match && !this.saved) p.append(button(displayText(match[2] || match[1]), `Read ${displayText(match[1])}`, () => this.details({ name: match[1] }), "dti-inline-link"));
                else p.append(document.createTextNode(match ? displayText(match[2] || match[1]) : part));
            }
            body.append(p);
        }
    }
    customForm(entry = null) {
        ++this.generation;
        const id = this.id;
        this.content.replaceChildren();
        const form = el("form", "dti-form");
        const fields = {};
        for (const [key, label, value, max] of [
            ["name", "Tag name", entry ? tagText(entry) : "", 300],
            ["folder", "Folders (separate with /)", entry?.paths?.[0]?.map(p => p.label).join(" / ") || "Personal", 1000],
            ["description", "Description (optional)", entry?.description || "", 30000],
        ]) {
            const wrapper = el("label", "dti-field", label);
            const input = el(key === "description" ? "textarea" : "input", "dti-input");
            input.value = value;
            input.maxLength = max;
            input.required = key === "name";
            if (key === "name" && entry) input.readOnly = true;
            wrapper.append(input);
            fields[key] = input;
            form.append(wrapper);
        }
        const actions = el("div", "dti-tools");
        const save = el("button", "dti-button dti-primary", "Save personal tag");
        save.type = "submit";
        actions.append(save, button("Cancel", "Return without saving", () => this.showList()));
        form.append(actions);
        form.addEventListener("submit", async event => {
            event.preventDefault();
            save.disabled = true;
            try {
                if (!entry && this.records.some(r => r.key === "custom:" + fields.name.value.trim())) throw new Error("A personal tag with this name exists. Open it and choose Edit personal tag.");
                await request(collectionPath(id), { action: "custom", name: entry?.name || fields.name.value, folder: fields.folder.value, description: fields.description.value });
                await refreshCollection(id);
                this.notify("Personal tag saved. The main index is unchanged.");
            } catch (error) { this.fail(error); save.disabled = false; }
        });
        this.content.append(form);
    }
    newCollection() {
        ++this.generation;
        this.content.replaceChildren();
        const form = el("form", "dti-form");
        const label = el("label", "dti-field", "New collection name");
        const input = el("input", "dti-input");
        input.required = true;
        input.maxLength = 120;
        input.placeholder = "For example: Character references";
        label.append(input);
        const submit = el("button", "dti-button dti-primary", "Create collection");
        submit.type = "submit";
        form.append(label, submit, button("Cancel", "Return to saved tags", () => this.showList()));
        form.addEventListener("submit", async event => {
            event.preventDefault();
            submit.disabled = true;
            try {
                const id = uuid();
                await request(collectionPath(id), { action: "ensure", title: input.value });
                this.node.properties.danbooru_collection = id;
                this.path = [];
                this.query = this.search.value = "";
                this.node.graph?.setDirtyCanvas?.(true, true);
                await this.loadSaved();
            } catch (error) { this.fail(error); submit.disabled = false; }
        });
        this.content.append(form);
    }
    dispose() {
        this.disposed = true;
        clearTimeout(this.searchTimer);
        clearTimeout(this.startTimer);
        this.generation++;
        controllers.delete(this.node);
        this.root.remove();
        updateConnections();
    }
}

function chain(object, name, callback) {
    const original = object[name];
    object[name] = function (...args) {
        const result = original?.apply(this, args);
        callback.apply(this, args);
        return result;
    };
}

app.registerExtension({
    name: "Danbooru.TagIndexer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (![INDEX, SAVED].includes(nodeData.name)) return;
        chain(nodeType.prototype, "onNodeCreated", function () {
            this.properties ||= {};
            const controller = new BrowserNode(this);
            controllers.set(this, controller);
            const schedule = () => {
                clearTimeout(controller.startTimer);
                controller.startTimer = setTimeout(() => controller.start(), 100);
            };
            chain(this, "onAdded", schedule);
            chain(this, "onConfigure", schedule);
            chain(this, "onConnectionsChange", () => setTimeout(updateConnections, 0));
            chain(this, "onRemoved", () => controller.dispose());
            schedule();
        });
    },
    async afterConfigureGraph() {
        for (const controller of controllers.values()) {
            clearTimeout(controller.startTimer);
            await controller.start();
        }
        updateConnections();
    },
});

// Refresh persisted data after returning to this tab or reconnecting the server.
// This never chooses a transfer target: transfers always resolve actual graph links.
const refreshSaved = () => {
    for (const controller of controllers.values()) if (controller.saved) controller.loadSaved();
};
window.addEventListener("focus", refreshSaved);
api.addEventListener("reconnected", refreshSaved);
