"""Offline catalog and personal collections. Uses only the Python standard library."""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from collections import deque
from contextlib import closing
from functools import lru_cache
from pathlib import Path

if __package__:
    from .navigation import main_outline, page_outline, entry_kind, has_wiki_links
else:
    from navigation import main_outline, page_outline, entry_kind, has_wiki_links

ROOT = "tag_groups"
PAGE_SIZE = 60
# Cross-references remain browsable but are not all parent folders (a common
# trait can be mentioned by thousands of character pages).
PARENT_EDGE = "(e.edge_type='child' OR (e.edge_type='related' AND p.kind IN ('group','section')))"
_unpack_lock = threading.Lock()


def connect(path: Path, readonly=False):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30) if readonly else sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def collection_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid saved collection ID") from None


def bounded_text(value, label, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} must be text of at most {maximum} characters")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Enter {label.lower()}")
    return value


class Catalog:
    def __init__(self, seed: Path, cache: Path):
        self.seed = seed
        self.cache = cache

    def path(self):
        target = self.cache / "catalog-v1.sqlite"
        if target.exists():
            return target
        with _unpack_lock:
            if not target.exists():
                self.cache.mkdir(parents=True, exist_ok=True)
                temporary = self.cache / f"catalog-{uuid.uuid4().hex}.tmp"
                try:
                    with gzip.open(self.seed, "rb") as source, temporary.open("wb") as dest:
                        shutil.copyfileobj(source, dest, 1024 * 1024)
                    with closing(connect(temporary, True)) as db:
                        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("The bundled catalog failed its integrity check")
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        return target

    def browse(self, parent=ROOT, query="", offset=0):
        query = bounded_text(query, "Search", 300)
        parent = bounded_text(parent, "Category", 1000, True)
        offset = max(0, int(offset))
        fields = "n.name,n.display_name AS label,n.kind,(SELECT count(DISTINCT child_id) FROM edges WHERE parent_id=n.id) AS children,n.coverage,n.description AS _wiki"
        with closing(connect(self.path(), True)) as db:
            if query:
                tokens = re.findall(r"[^\W_]+", query, re.UNICODE)[:8]
                match = " AND ".join('"' + t + '"*' for t in tokens)
                if not match:
                    return {"items": [], "more": False}
                try:
                    rows = db.execute(f"SELECT {fields} FROM nodes_fts JOIN nodes n ON n.id=nodes_fts.rowid WHERE nodes_fts MATCH ? ORDER BY CASE WHEN n.name=? THEN 0 ELSE 1 END,rank,n.name LIMIT ? OFFSET ?", (match, query.lower().replace(" ", "_"), PAGE_SIZE + 1, offset)).fetchall()
                except sqlite3.OperationalError as error:
                    if "fts5" not in str(error).lower():
                        raise
                    # Unusual Python builds without FTS5 still support name searching.
                    rows = db.execute(f"SELECT {fields} FROM nodes n WHERE instr(lower(n.name),?) OR instr(lower(n.display_name),?) ORDER BY n.name LIMIT ? OFFSET ?", (query.lower().replace(" ", "_"), query.lower(), PAGE_SIZE + 1, offset)).fetchall()
            else:
                rows = db.execute(f"""SELECT {fields},
                    CASE min(CASE e.edge_type WHEN 'child' THEN 0 WHEN 'related' THEN 1 ELSE 2 END)
                        WHEN 0 THEN 'child' WHEN 1 THEN 'related' ELSE 'xref' END AS relation
                    FROM edges e JOIN nodes n ON n.id=e.child_id JOIN nodes p ON p.id=e.parent_id
                    WHERE p.name=? GROUP BY n.id
                    ORDER BY min(e.position),min(e.id),n.name
                    LIMIT ? OFFSET ?""", (parent, PAGE_SIZE + 1, offset)).fetchall()
            items = [dict(r) for r in rows[:PAGE_SIZE]]
            for item in items:
                item["kind"] = entry_kind(item["name"], item["kind"])
                wiki_text = item.pop("_wiki")
                item["expandable"] = has_wiki_links(item["name"], wiki_text)
                if item["kind"] == "tag":
                    item["description"] = re.split(r"(?m)^## ", wiki_text, maxsplit=1)[0].strip()
            return {"items": items, "more": len(rows) > PAGE_SIZE}

    @lru_cache(maxsize=64)
    def outline(self, page=ROOT):
        page = bounded_text(page, "Category", 1000, True)
        if page.startswith("section:"):
            owner = page[8:].rsplit("#", 1)[0]
            def find(entries):
                for entry in entries:
                    if entry["name"] == page:
                        return entry["children"]
                    match = find(entry["children"])
                    if match is not None:
                        return match
            return find(self.outline(owner)) or []
        with closing(connect(self.path(), True)) as db:
            row = db.execute("SELECT description FROM nodes WHERE name=?", (page,)).fetchone()
            if row is None:
                raise ValueError("This category is not in the bundled index")
            text = row[0]
            names = set(re.findall(r"\[\[([^|\]]+)", text))
            prefix = f"section:{page}#"
            metadata = {r["name"]: dict(r) for r in db.execute("SELECT name,display_name AS label,kind FROM nodes WHERE name>=? AND name<?", (prefix, prefix + "\uffff"))}
            for name in names:
                row = db.execute("SELECT name,display_name AS label,kind,description AS _wiki FROM nodes WHERE name=?", (name,)).fetchone()
                if row:
                    metadata[name] = dict(row)
            section_parents = {r[0]: r[1] for r in db.execute("SELECT n.name,p.name FROM nodes n JOIN edges e ON e.child_id=n.id JOIN nodes p ON p.id=e.parent_id WHERE n.name>=? AND n.name<? AND p.name>=? AND p.name<? ORDER BY e.position", (prefix,prefix + "\uffff",prefix,prefix + "\uffff"))}
        result = main_outline(text, metadata) if page == ROOT else page_outline(page, text, metadata, section_parents)
        def decorate(entries):
            for entry in entries:
                entry["kind"] = "group" if entry.get("category_link") else entry_kind(entry["name"], entry["kind"])
                wiki_text = metadata.get(entry["name"], {}).get("_wiki", "")
                entry["expandable"] = has_wiki_links(entry["name"], wiki_text)
                if entry["kind"] == "tag":
                    entry["description"] = re.split(r"(?m)^## ", wiki_text, maxsplit=1)[0].strip()
                decorate(entry["children"])
        decorate(result)
        return result

    @lru_cache(maxsize=1)
    def hierarchy(self):
        """Build a cycle-safe parent tree once; prefer original child-only paths.

        A reverse SQL walk per tag becomes expensive when See also links create
        large cycles. This bounded forward traversal visits each edge at most
        twice and retains only one parent pointer per reachable entry.
        """
        with closing(connect(self.path(), True)) as db:
            root = db.execute("SELECT id FROM nodes WHERE name=?", (ROOT,)).fetchone()
            if root is None:
                return {}
            children, references = {}, {}
            for row in db.execute("SELECT e.parent_id,e.child_id,e.edge_type FROM edges e JOIN nodes p ON p.id=e.parent_id WHERE e.edge_type='child' OR p.kind IN ('group','section') ORDER BY e.position,e.id"):
                target = children if row["edge_type"] == "child" else references
                target.setdefault(row["parent_id"], []).append(row["child_id"])
        parents = {root[0]: None}
        for include_references in (False, True):
            queue = deque(parents)
            while queue:
                parent = queue.popleft()
                linked = children.get(parent, [])
                if include_references:
                    linked = linked + references.get(parent, [])
                for child in linked:
                    if child not in parents:
                        parents[child] = parent
                        queue.append(child)
        return parents

    @lru_cache(maxsize=2048)
    def folder_path(self, name):
        parents = self.hierarchy()
        with closing(connect(self.path(), True)) as db:
            row = db.execute("SELECT id,name,display_name FROM nodes WHERE name=?", (name,)).fetchone()
            if row is None:
                return []
            result = []
            while row is not None and row["name"] != ROOT:
                result.append({"id": row["name"], "label": row["display_name"]})
                parent_id = parents.get(row["id"])
                row = db.execute("SELECT id,name,display_name FROM nodes WHERE id=?", (parent_id,)).fetchone() if parent_id is not None else None
            return result[::-1]

    def detail(self, name):
        name = bounded_text(name, "Tag name", 1000, True)
        with closing(connect(self.path(), True)) as db:
            row = db.execute("SELECT id,name,display_name AS label,kind,description,source_url,coverage,(SELECT count(DISTINCT child_id) FROM edges WHERE parent_id=nodes.id) AS children FROM nodes WHERE name=?", (name,)).fetchone()
            if row is None:
                raise ValueError("This entry is not in the bundled index")
            result = dict(row)
            result["kind"] = entry_kind(name, result["kind"])
            parents = db.execute(f"SELECT DISTINCT p.name,p.display_name AS label FROM edges e JOIN nodes p ON p.id=e.parent_id WHERE e.child_id=? AND {PARENT_EDGE} ORDER BY CASE e.edge_type WHEN 'child' THEN 0 WHEN 'related' THEN 1 ELSE 2 END,e.position,p.name", (row["id"],)).fetchall()
            result["parents"] = [dict(p) for p in parents]
            return result

    def snapshot(self, name, browse_path=None, context=None):
        result = self.detail(name)
        if result["kind"] != "tag":
            raise ValueError("Open a category and star an individual tag")
        paths = [self.folder_path(p["name"]) for p in result["parents"]]
        if context is not None:
            if not isinstance(context, dict) or not isinstance(context.get("route"), list) or not 1 <= len(context["route"]) <= 128:
                raise ValueError("Invalid outline context")
            page = bounded_text(context.get("page"), "Category", 1000, True)
            entries = self.outline(page)
            selected_path = []
            for target in context["route"]:
                entry = next((e for e in entries if e["name"] == target), None)
                if entry is None:
                    raise ValueError("This tag is not on the selected category route")
                selected_path.append({"id": entry["name"], "label": entry["label"]})
                entries = entry["children"]
            if selected_path[-1]["id"] != name:
                raise ValueError("The outline route does not end at this tag")
            prefix = [] if page == ROOT else self.folder_path(page)
            route = prefix + selected_path[:-1]
            if route and route not in paths:
                paths.insert(0, route)
        if not paths:
            # An entry reachable only by references gets one meaningful source
            # location, rather than thousands of unrelated incoming mentions.
            route = self.folder_path(name)
            paths = [route[:-1]] if len(route) > 1 else []
        if browse_path:
            # Preserve the precise route used by the user, after checking every edge.
            if not isinstance(browse_path, list) or len(browse_path) > 64:
                raise ValueError("Invalid category path")
            previous = ROOT
            validated = []
            with closing(connect(self.path(), True)) as db:
                for child in [*browse_path, name]:
                    child = bounded_text(child, "Category", 1000, True)
                    row = db.execute("SELECT n.name,n.display_name FROM edges e JOIN nodes n ON n.id=e.child_id JOIN nodes p ON p.id=e.parent_id WHERE p.name=? AND n.name=?", (previous, child)).fetchone()
                    if row is None:
                        raise ValueError("The browsing path no longer matches this tag")
                    if child != name:
                        validated.append({"id": row[0], "label": row[1]})
                    previous = child
            if validated not in paths:
                paths.insert(0, validated)
        result.pop("id", None)
        result["paths"] = paths or [[]]
        result["key"] = "catalog:" + name
        result["custom"] = False
        return result


class Collections:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entries(collection TEXT NOT NULL, key TEXT NOT NULL,
                    record TEXT NOT NULL, PRIMARY KEY(collection,key));
                PRAGMA user_version=1;
            """)

    def list(self):
        with closing(connect(self.path)) as db:
            return [dict(r) for r in db.execute("SELECT c.id,c.title,count(e.key) AS count FROM collections c LEFT JOIN entries e ON e.collection=c.id GROUP BY c.id ORDER BY c.title,c.id")]

    def ensure(self, identifier, title="Saved tags"):
        identifier = collection_id(identifier)
        title = bounded_text(title, "Collection name", 120, True)
        with closing(connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO collections VALUES(?,?)", (identifier, title))
        return identifier

    def entries(self, identifier):
        identifier = collection_id(identifier)
        with closing(connect(self.path)) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT record FROM entries WHERE collection=? ORDER BY key", (identifier,))]

    def put(self, identifier, record):
        identifier = collection_id(identifier)
        with closing(connect(self.path)) as db, db:
            if not db.execute("SELECT 1 FROM collections WHERE id=?", (identifier,)).fetchone():
                raise ValueError("Saved collection not found; refresh the Saved Tags node")
            db.execute("INSERT INTO entries VALUES(?,?,?) ON CONFLICT(collection,key) DO UPDATE SET record=excluded.record", (identifier, record["key"], json.dumps(record, ensure_ascii=False)))

    def custom(self, identifier, data):
        name = bounded_text(data.get("name", ""), "Tag name", 300, True)
        description = bounded_text(data.get("description", ""), "Description", 30000)
        folder = bounded_text(data.get("folder", ""), "Folder path", 1000)
        labels = [p.strip() for p in folder.split("/") if p.strip()]
        path = [{"id": "custom:" + "/".join(labels[:i + 1]), "label": label} for i, label in enumerate(labels)]
        record = {"key": "custom:" + name, "name": name, "label": name.replace("_", " "), "kind": "tag", "description": description, "paths": [path], "custom": True}
        self.put(identifier, record)
        return record

    def remove(self, identifier, key):
        identifier = collection_id(identifier)
        key = bounded_text(key, "Tag key", 1100, True)
        with closing(connect(self.path)) as db, db:
            db.execute("DELETE FROM entries WHERE collection=? AND key=?", (identifier, key))

