"""Preserve the main wiki page's heading order and list indentation.

The catalog graph merges relationships from many wiki pages. That graph is useful
for exploration but cannot reproduce where a link appeared on one specific page.
The stored page text retains its table-of-contents levels and nested list layout.
"""
import re

TOC = re.compile(r'^([ \t]*)-\s+[\d.]+\s+"([^"]+)":#dtext-([^\s]+)\s*$')
LINK = re.compile(r'^([ \t]*)-\s+\[\[([^|\]]+)(?:\|([^\]]+))?\]\](.*)$')


def entry_kind(name, original):
    """The old 'group' means a wiki has links, not that it isn't a real tag."""
    if original == "section" or name.startswith(("section:", "outline:")):
        return "section"
    if name in {"tag_groups", "pool_groups"} or name.startswith(("tag_group:", "list_of_", "help:", "howto:", "about:", "template:")):
        return "group"
    return "tag"


def has_wiki_links(name, text):
    """Only listed or heading links form expandable wiki navigation.

    A mention inside prose remains in the description; it is not a category.
    """
    for line in (text or "").splitlines():
        if re.match(r"^(?:[ \t]*-\s+|##\s+)?\[\[", line):
            match = re.search(r"\[\[([^|\]]+)", line)
            if match and match[1] not in {name, "tag_groups"}:
                return True
    return False


def page_outline(page, text, metadata, section_parents):
    """Parse any indexed wiki in source order, including unlinked list labels.

    Navigation prose before the first heading is not a category. TOC entries are
    skipped; heading IDs and nesting come from the page's own indexed sections.
    """
    sections = [v for k, v in metadata.items() if k.startswith(f"section:{page}#")]
    sections.sort(key=lambda s: int(s["name"].rsplit("-", 1)[-1]))
    remaining = list(sections)
    roots, headings, bullets = [], {}, []
    current = None
    for line_number, line in enumerate(text.splitlines()):
        if TOC.match(line):
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            heading_link = re.fullmatch(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]", title)
            if heading_link:
                name, alias = heading_link.groups()
                if name in metadata and name not in {page, "tag_groups"}:
                    info = metadata[name]
                    (current["children"] if current else roots).append({"name": name, "label": readable(alias or info["label"]), "kind": entry_kind(name, info["kind"]), "children": []})
                continue
            match = next((s for s in remaining if s["label"].casefold() == title.casefold()), None)
            if match:
                remaining.remove(match)
            name = match["name"] if match else f"outline:{page}:heading:{line_number}"
            current = {"name": name, "label": readable(title), "kind": "section", "children": [], "description": ""}
            parent = headings.get(section_parents.get(name))
            (parent["children"] if parent else roots).append(current)
            headings[name] = current
            bullets = []
            continue
        bullet = re.match(r"^([ \t]*)-\s+(.*)$", line)
        if not bullet:
            # Extracted wiki table cells may be standalone links without bullets.
            if re.fullmatch(r"\s*\[\[[^\]]+\]\]\s*", line):
                indent, content = "", line.strip()
            else:
                continue  # Excludes '[See tag_groups]' and other prose backlinks.
        else:
            indent, content = bullet.groups()
        depth = len(indent.expandtabs(2)) // 2
        link = re.match(r"^\[\[([^|\]]+)(?:\|([^\]]+))?\]\](.*)$", content)
        if link:
            name, alias, note = link.groups()
            if name in {page, "tag_groups"}:
                continue
            info = metadata.get(name, {"label": name, "kind": "tag"})
            entry = {"name": name, "label": readable(alias or info["label"]), "kind": entry_kind(name, info["kind"]), "children": [], "note": note.strip()}
        elif "[[" not in content and content.strip():
            entry = {"name": f"outline:{page}:list:{line_number}", "label": readable(content.strip()), "kind": "section", "children": []}
        else:
            continue
        while bullets and bullets[-1][0] >= depth:
            bullets.pop()
        siblings = bullets[-1][1]["children"] if bullets else current["children"] if current else roots
        siblings.append(entry)
        bullets.append((depth, entry))
    def prune_empty_sections(entries):
        result = []
        for entry in entries:
            entry["children"] = prune_empty_sections(entry["children"])
            if entry["kind"] != "section" or entry["children"] or entry.get("description"):
                result.append(entry)
        return result
    return prune_empty_sections(roots)


def readable(text):
    text = re.sub(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]", lambda m: m[2] or m[1], text)
    text = text.replace("_", " ")
    text = text[:1].upper() + text[1:]
    if text.startswith("Tag group:"):
        prefix, suffix = text.split(":", 1)
        text = prefix + ":" + suffix[:1].upper() + suffix[1:]
    return text


def main_outline(text, metadata):
    """Return a finite, page-local outline, never global graph children."""
    toc = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = TOC.match(line)
        if match:
            indent, label, anchor = match.groups()
            toc.append((len(indent.expandtabs(2)) // 2, label, anchor))
    if not toc:
        raise ValueError("The main category page has no structured table of contents")

    roots, heading_stack, bullet_stack = [], [], []
    section = None
    heading_index = 0
    for line in text.splitlines():
        if line.startswith("## "):
            if heading_index >= len(toc):
                raise ValueError("The category outline has more headings than its table of contents")
            level, title, anchor = toc[heading_index]
            if title.casefold() != line[3:].strip().casefold():
                raise ValueError("The category heading order does not match its table of contents")
            name = f"section:tag_groups#{anchor}-{heading_index}"
            if name not in metadata:
                raise ValueError(f"Missing indexed section: {name}")
            section = {"name": name, "label": line[3:].strip(), "kind": "section", "children": [], "description": ""}
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            siblings = heading_stack[-1][1]["children"] if heading_stack else roots
            siblings.append(section)
            heading_stack.append((level, section))
            bullet_stack = []
            heading_index += 1
            continue
        if section is None:
            continue
        match = LINK.match(line)
        if match:
            indent, name, alias, note = match.groups()
            depth = len(indent.expandtabs(2)) // 2
            info = metadata.get(name)
            if info is None:
                raise ValueError(f"A category link is missing from the bundled catalog: {name}")
            entry = {"name": name, "label": readable(alias or info["label"]), "kind": info["kind"], "children": [], "note": note.strip()}
            entry["category_link"] = entry["label"].casefold().startswith("tag group:")
            while bullet_stack and bullet_stack[-1][0] >= depth:
                bullet_stack.pop()
            siblings = bullet_stack[-1][1]["children"] if bullet_stack else section["children"]
            siblings.append(entry)
            bullet_stack.append((depth, entry))
        elif line.strip():
            section["description"] += line.strip() + "\n"
    if heading_index != len(toc):
        raise ValueError("The category outline is incomplete")
    return roots
