import assert from "node:assert/strict";
import test from "node:test";
import { INDEX, SAVED, TYPE, sourceFor, targetsFor, savedView, displayText, tagText, contextRemainder, shortDescription } from "../web/library.mjs";

function graph(useMap = false) {
    const a = { id: 1, type: INDEX, outputs: [{ type: TYPE, links: [4] }] };
    const b = { id: 2, type: SAVED, inputs: [{ name: "tag_library", type: TYPE, link: 4 }] };
    const other = { id: 3, type: SAVED, inputs: [{ name: "tag_library", type: TYPE, link: null }] };
    const links = { 4: { origin_id: 1, origin_slot: 0, target_id: 2, target_slot: 0 } };
    const g = { links: useMap ? new Map([[4, links[4]]]) : links, getNodeById: id => [a, b, other].find(n => n.id === id) };
    for (const n of [a, b, other]) n.graph = g;
    return { a, b, other, g };
}
for (const map of [false, true]) test(`only actual wires select targets (${map ? "Map" : "object"} links)`, () => {
    const { a, b, other } = graph(map);
    assert.deepEqual(targetsFor(a), [b]);
    assert.equal(sourceFor(b), a);
    assert.equal(sourceFor(other), null);
    b.inputs[0].link = null;
    assert.deepEqual(targetsFor(a), []);
});
test("incompatible ports and missing links cannot transfer", () => {
    const { a, b, g } = graph();
    a.outputs[0].type = "STRING";
    assert.equal(sourceFor(b), null);
    a.outputs[0].type = TYPE;
    delete g.links[4];
    assert.deepEqual(targetsFor(a), []);
});
test("saved list shows tags immediately and searches all metadata without duplicates", () => {
    const folder = { id: "hair", label: "Hair" };
    const record = { key: "catalog:a", name: "long_hair", paths: [[folder], [{ id: "body", label: "Body" }, folder]], description: "Length" };
    assert.equal(savedView([record], "").length, 1);
    assert.equal(savedView([record], "long hair").length, 1);
    assert.equal(savedView([record], "long_hair").length, 1);
    assert.equal(savedView([record], "length").length, 1);
    assert.equal(savedView([record], "body").length, 1);
    assert.equal(savedView([record], "unrelated").length, 0);
    assert.equal(savedView([record, record], "").length, 1);
});
test("display and clipboard use spaces while storage identifiers remain intact", () => {
    const record = { name: "egyptian_toe", key: "catalog:egyptian_toe" };
    assert.equal(tagText(record), "egyptian toe");
    assert.equal(displayText("long_blue_hair"), "long blue hair");
    assert.equal(record.name, "egyptian_toe");
    assert.equal(record.key, "catalog:egyptian_toe");
});
test("full wiki expansion retains unique parent entries and their save routes", () => {
    const context = [{ name: "toenails", children: [{ name: "sharp_toenails", children: [] }, { name: "long_toenails", children: [] }] }];
    const full = [{ name: "section", children: [{ name: "toenails", children: [] }, { name: "long_toenails", children: [] }] }];
    const extra = contextRemainder(context, full, ["appearance"]);
    assert.deepEqual(extra.map(e => e.name), ["sharp_toenails"]);
    assert.deepEqual(extra[0].sourceRoute, ["appearance", "toenails", "sharp_toenails"]);
    assert.equal(context[0].children.length, 2);
});
test("saved summary shows the definition without wiki sections or link markup", () => {
    const wiki = "A condition in which the second toe is longer than the first (big) toe. Also known as Morton's toe or Greek foot.\n\n## See also\n- [[egyptian_toe]]\n\n## External links\nLong wiki";
    assert.equal(shortDescription(wiki), wiki.split("\n")[0]);
    assert.equal(shortDescription("Digits of the [[feet|feet]].\n## Examples\n- image"), "Digits of the feet.");
    assert.equal(shortDescription("Wearing [[toe_socks]].\nA wrapped line.\n\nMore text."), "Wearing toe socks. A wrapped line.");
});
test("long and missing saved descriptions stay compact without changing stored text", () => {
    const entry = {description: "A personal explanation about a tag. ".repeat(30)};
    const original = entry.description;
    const summary = shortDescription(entry.description);
    assert.ok(summary.length <= 220);
    assert.ok(summary.endsWith("…"));
    assert.equal(entry.description, original);
    assert.equal(shortDescription("## See also\n- [[feet]]"), "No short description available.");
    assert.equal(shortDescription(null), "No short description available.");
    assert.equal(shortDescription("<img src=x onerror=alert(1)>"), "<img src=x onerror=alert(1)>");
});
