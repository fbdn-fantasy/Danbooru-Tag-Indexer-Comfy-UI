"""Run with: python -m unittest discover -s tests -p test_*.py -v"""
import importlib.util
import json
import re
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "tests/.cache"
CACHE.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("catalog", ROOT / "catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog.Catalog(ROOT / "data/catalog.sqlite.gz", ROOT / "tests/.cache/catalog-tests")

    def test_real_database_integrity_and_roots(self):
        with closing(sqlite3.connect(self.catalog.path())) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT count(*) FROM nodes").fetchone()[0], 204345)
        labels = [r["label"] for r in self.catalog.browse()["items"]]
        self.assertIn("Visual characteristics", labels)

    def test_search_exact_name_first_and_pagination(self):
        self.assertEqual(self.catalog.browse(query="blue eyes")["items"][0]["name"], "blue_eyes")
        first = self.catalog.browse(query="hair")
        second = self.catalog.browse(query="hair", offset=60)
        self.assertTrue(first["more"])
        self.assertFalse({r["name"] for r in first["items"]} & {r["name"] for r in second["items"]})
        self.assertEqual(self.catalog.browse(query='"***()')['items'], [])

    def test_save_snapshots_all_direct_parents_and_description(self):
        record = self.catalog.snapshot("blue_eyes")
        self.assertTrue(record["description"])
        self.assertEqual({p[-1]["id"] if p else "tag_groups" for p in record["paths"]}, {p["name"] for p in record["parents"]})
        self.assertTrue(any(p[0]["label"] == "Visual characteristics" for p in record["paths"]))
        path = [p["id"] for p in record["paths"][0]]
        self.assertIn(record["paths"][0], self.catalog.snapshot("blue_eyes", path)["paths"])
        with self.assertRaises(ValueError):
            self.catalog.snapshot("blue_eyes", ["tag_group:animals"])
        with self.assertRaises(ValueError):
            self.catalog.snapshot("tag_groups")

    def test_egyptian_toe_search_and_previously_hidden_browsing_route(self):
        for query in ("Egyptian Toe", "egyptian_toe", "egyptian toe"):
            self.assertEqual(self.catalog.browse(query=query)["items"][0]["name"], "egyptian_toe")
        route = ["toes", "section:toes#related-tags-1", "section:toes#appearance-2", "egyptian_toe"]
        for parent, child in zip(route, route[1:]):
            self.assertIn(child, [r["name"] for r in self.catalog.browse(parent=parent)["items"]])
        record = self.catalog.snapshot("egyptian_toe")
        self.assertIn("first (big) toe", record["description"])
        self.assertTrue(any(p[-1]["id"] == "section:toes#appearance-2" for p in record["paths"]))
        self.assertTrue(any(p[0]["label"] == "Visual characteristics" for p in record["paths"]))
        route = [p["id"] for p in record["paths"][0]]
        self.assertIn(record["paths"][0], self.catalog.snapshot("egyptian_toe", route)["paths"])

    def test_xrefs_remain_accessible_without_becoming_hundreds_of_parent_paths(self):
        names = [r["name"] for r in self.catalog.browse(parent="greek_toe")["items"]]
        self.assertIn("egyptian_toe", names)
        self.assertEqual(len(self.catalog.snapshot("blue_eyes")["paths"]), 2)

    def test_mixed_relationships_remain_accessible_across_pages(self):
        # A large group exercises multiple pages and overlap of relationship types.
        with closing(sqlite3.connect(self.catalog.path())) as db:
            name, count = db.execute("SELECT p.name,count(DISTINCT e.child_id) c FROM nodes p JOIN edges e ON e.parent_id=p.id GROUP BY p.id HAVING c BETWEEN 150 AND 250 ORDER BY c DESC LIMIT 1").fetchone()
            expected = {r[0] for r in db.execute("SELECT DISTINCT n.name FROM edges e JOIN nodes p ON p.id=e.parent_id JOIN nodes n ON n.id=e.child_id WHERE p.name=?", (name,))}
        result, offset = [], 0
        while True:
            page = self.catalog.browse(parent=name, offset=offset)
            result.extend(r["name"] for r in page["items"])
            if not page["more"]:
                break
            offset += catalog.PAGE_SIZE
        self.assertEqual(set(result), expected)
        self.assertEqual(len(result), count)

    def test_main_sections_and_subsections_match_reference(self):
        outline = self.catalog.outline()
        self.assertEqual([n["label"] for n in outline], ["Intro", "Visual characteristics", "Copyrights, artists, projects and media", "Metatags", "See also"])
        self.assertIn("list of wikis", outline[0]["description"])
        visual = outline[1]
        self.assertEqual([n["label"] for n in visual["children"]], ["Image composition and style", "Body", "Attire and body accessories", "Sex", "Objects", "Creatures", "Plants", "Games", "Real world", "More"])
        self.assertEqual([n["label"] for n in outline[2]["children"]], ["Genres of video games", "Artists", "Characters", "More"])
        self.assertNotEqual(visual["children"][-1]["name"], outline[2]["children"][-1]["name"])
        self.assertEqual([n["name"] for n in outline[3]["children"]], ["tag_group:metatags", "tag_group:drawing_software"])
        self.assertEqual([n["name"] for n in outline[4]["children"]], ["pool_groups", "list_of_meta-wikis"])

    def test_page_local_nested_lists_do_not_merge_other_wiki_contents(self):
        visual = self.catalog.outline()[1]["children"]
        composition = visual[0]["children"]
        self.assertEqual([n["name"] for n in composition], ["tag_group:artistic_license", "tag_group:image_composition", "tag_group:patterns", "tag_group:symbols", "tag_group:text", "tag_group:year_tags"])
        self.assertEqual([n["name"] for n in composition[1]["children"]], ["tag_group:backgrounds", "tag_group:censorship", "tag_group:character_count", "tag_group:colors", "tag_group:fine_art_parody", "tag_group:focus_tags", "tag_group:lighting", "tag_group:prints", "list_of_style_parodies", "tag_group:visual_aesthetic"])
        body = visual[1]["children"]
        self.assertEqual([n["name"] for n in body], ["tag_group:body_parts", "injury"])
        parts = body[0]["children"]
        on = next(e for e in parts if e["name"] == "on")
        self.assertEqual(on["label"], "Tag group:On (object)")
        self.assertEqual(on["kind"], "group")
        self.assertEqual([n["name"] for n in parts[2]["children"]], ["tag_group:ears_tags", "tag_group:eyes_tags", "eyebrows", "nose"])
        self.assertEqual([n["name"] for n in parts[3]["children"]], ["tag_group:hair_color", "tag_group:hair_styles"])
        attire = visual[2]["children"]
        self.assertEqual([n["name"] for n in attire[1]["children"]], ["tag_group:handwear", "tag_group:headwear", "tag_group:legwear", "mask", "tag_group:neck_and_neckwear", "tag_group:sexual_attire", "tag_group:sleeves", "swimsuit"])
        self.assertEqual(visual[3]["children"][0]["children"][0]["name"], "tag_group:simulated_sex_acts")

    def test_all_outline_routes_are_valid_and_repeated_links_stay_separate(self):
        outline = self.catalog.outline()
        occurrences = []
        with closing(sqlite3.connect(self.catalog.path())) as db:
            def walk(entries, parent="tag_groups"):
                for entry in entries:
                    self.assertIsNotNone(db.execute("SELECT 1 FROM edges e JOIN nodes p ON p.id=e.parent_id JOIN nodes n ON n.id=e.child_id WHERE p.name=? AND n.name=?", (parent, entry["name"])).fetchone())
                    occurrences.append(entry["name"])
                    walk(entry["children"], entry["name"])
            walk(outline)
        self.assertEqual(len(occurrences), 211)
        self.assertEqual(occurrences.count("tag_group:eyewear"), 2)
        self.assertEqual(occurrences.count("tag_group:neck_and_neckwear"), 2)

    def test_feet_source_order_backlink_exclusion_and_unlinked_labels(self):
        outline = self.catalog.outline("tag_group:feet")
        self.assertEqual([e["label"] for e in outline], ["Main", "Style", "Anatomy / Parts", "Toes", "Poses & Views", "Clothing & Accessories", "Actions & Fetish", "Misc / Technical", "See Also"])
        self.assertEqual([e["name"] for e in outline[1]["children"]], ["barefoot", "no_shoes"])
        self.assertEqual([e["name"] for e in outline[2]["children"][0]["children"]], ["arched_soles", "light-skinned_soles"])
        self.assertEqual([e["name"] for e in outline[4]["children"]], ["dorsiflexion", "plantar_flexion", "en_pointe", "tiptoes", "foot_dangle", "pigeon-toed", "the_pose"])
        clothing = outline[5]
        self.assertEqual([e["label"] for e in clothing["children"]], ["Anklet", "Toe ring", "Toe seam", "Legwear", "Footwear"])
        legwear = clothing["children"][3]
        self.assertEqual(legwear["children"][0]["name"], "socks")
        self.assertNotIn("tag_groups", [e["name"] for e in outline])
        record = self.catalog.snapshot("socks", context={"page":"tag_group:feet", "route":[clothing["name"],legwear["name"],"socks"]})
        self.assertIn("Legwear", [p["label"] for p in record["paths"][0]])
        with self.assertRaises(ValueError):
            self.catalog.snapshot("egyptian_toe", context={"page":"tag_group:feet", "route":[clothing["name"],"egyptian_toe"]})

    def test_generic_outlines_inside_and_outside_visual_categories(self):
        for page in ["tag_group:ass", "tag_group:hair", "tag_group:fighting_games", "list_of_official_mascots", "tag_group:metatags", "pool_groups", "list_of_meta-wikis", "list_of_pokemon_trainer_classes"]:
            with self.subTest(page=page):
                outline = self.catalog.outline(page)
                self.assertTrue(outline)
                def inspect(entries):
                    for e in entries:
                        self.assertNotEqual(e["name"], "tag_groups")
                        self.assertNotIn("[[", e["label"])
                        inspect(e["children"])
                inspect(outline)
        self.assertEqual(self.catalog.outline("tag_group:ass")[0]["label"], "Anatomy of the ass")
        objects = next(e for e in self.catalog.outline("tag_group:hair") if e["label"]=="Objects")
        self.assertEqual([e["label"] for e in objects["children"]], ["Objects for hair care and hairdressing", "Accessories for the hair"])
        trainers = self.catalog.outline("list_of_pokemon_trainer_classes")
        self.assertGreater(len(trainers), 100)
        self.assertIn("ace_trainer_(pokemon)", [e["name"] for e in trainers])

    def test_real_tags_with_wiki_children_can_be_opened_and_saved(self):
        for name in ["toes", "feet", "soles", "barefoot", "socks"]:
            with self.subTest(name=name):
                self.assertEqual(self.catalog.detail(name)["kind"], "tag")
                self.assertEqual(self.catalog.snapshot(name)["name"], name)
        with self.assertRaises(ValueError):
            self.catalog.snapshot("tag_group:feet")

    def test_tag_wikis_expose_complete_lists_without_invented_sections(self):
        def flatten(entries):
            return [e for entry in entries for e in [entry, *flatten(entry["children"])]]
        toes = next(e for e in flatten(self.catalog.outline("tag_group:feet")) if e["name"] == "toes")
        self.assertTrue(toes["expandable"])
        self.assertTrue(self.catalog.browse(query="toes")["items"][0]["expandable"])
        full = flatten(self.catalog.outline("toes"))
        names = {e["name"] for e in full}
        expected = {"long_toes", "greek_toe", "egyptian_toe", "toenails", "long_toenails", "toenail_polish", "sharp_toenails", "toe_cleavage", "toe_ring", "toe_seam", "toe_socks", "between_toes", "en_pointe", "tiptoes", "toe_grab", "toe_scrunch", "toe_sucking", "dorsiflexion", "plantar_flexion", "spread_toes", "barefoot", "sandals", "soles", "prehensile_toes", "prehensile_feet"}
        self.assertTrue(expected <= names, expected - names)
        self.assertIn("Appearance", {e["label"] for e in full})
        self.assertIn("Actions", {e["label"] for e in full})
        self.assertIn("See also", {e["label"] for e in full})
        record = self.catalog.snapshot("egyptian_toe", context={"page":"toes", "route":["section:toes#related-tags-1", "section:toes#appearance-2", "egyptian_toe"]})
        self.assertEqual([p["label"] for p in record["paths"][0]][-2:], ["Related tags", "Appearance"])
        nails = self.catalog.outline("toenails")
        self.assertEqual([e["label"] for e in nails], ["See also"])
        self.assertEqual(nails[0]["children"][0]["name"], "fingernails")
        self.assertNotIn("Referenced tags", {e["label"] for e in full})
        self.assertIn("Digits of the", toes["description"])

    def test_all_main_category_pages_retain_source_list_links(self):
        def names(entries):
            return {e["name"] for entry in entries for e in [entry]} | set().union(*(names(e["children"]) for e in entries))
        def groups(entries):
            return {e["name"] for e in entries if e["kind"] == "group"} | set().union(*(groups(e["children"]) for e in entries))
        pages = groups(self.catalog.outline()) | {"toes", "toenails", "ass", "hair", "feet", "pokemon", "hatsune_miku", "kyoto_animation"}
        with closing(sqlite3.connect(self.catalog.path())) as db:
            for page in sorted(pages):
                with self.subTest(page=page):
                    text = self.catalog.detail(page)["description"]
                    links = []
                    for line in text.splitlines():
                        match = re.match(r"^[ \t]*-\s+\[\[([^|\]]+)", line) or re.fullmatch(r"\s*\[\[([^|\]]+)(?:\|[^\]]+)?\]\]\s*", line)
                        if match:
                            links.append(match[1])
                    expected = {name for name in links if name not in {page, "tag_groups"} and db.execute("SELECT 1 FROM nodes WHERE name=?", (name,)).fetchone()}
                    outline = self.catalog.outline(page)
                    self.assertFalse(expected - names(outline), expected - names(outline))
                    self.assertNotIn(f"outline:{page}:references", names(outline))

    def test_folder_cycle_terminates(self):
        with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
            cache = Path(tmp)
            with closing(sqlite3.connect(cache / "catalog-v1.sqlite")) as db, db:
                db.executescript("CREATE TABLE nodes(id INTEGER,name TEXT,display_name TEXT); CREATE TABLE edges(parent_id INTEGER,child_id INTEGER,edge_type TEXT,position INTEGER); INSERT INTO nodes VALUES(1,'a','A'),(2,'b','B'); INSERT INTO edges VALUES(1,2,'child',0),(2,1,'child',0);")
            c = catalog.Catalog(Path("unused"), cache)
            self.assertEqual(c.folder_path("a"), [{"id": "a", "label": "A"}])


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=CACHE)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "saved.sqlite"
        self.store = catalog.Collections(self.path)
        self.a, self.b = str(uuid.uuid4()), str(uuid.uuid4())
        self.store.ensure(self.a, "First")
        self.store.ensure(self.b, "Second")

    def test_custom_tags_persist_and_collections_are_isolated(self):
        self.store.custom(self.a, {"name": "my_tag", "folder": "Personal / Hair", "description": "My description"})
        records = catalog.Collections(self.path).entries(self.a)
        self.assertEqual(records[0]["paths"][0][-1]["label"], "Hair")
        self.assertEqual(records[0]["description"], "My description")
        self.assertEqual(self.store.entries(self.b), [])
        self.store.remove(self.a, records[0]["key"])
        self.assertEqual(self.store.entries(self.a), [])

    def test_parallel_saves_do_not_lose_updates(self):
        def save(i):
            catalog.Collections(self.path).custom(self.a, {"name": f"tag_{i}"})
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(save, range(30)))
        self.assertEqual(len(self.store.entries(self.a)), 30)

    def test_bad_ids_and_input_rejected(self):
        for bad in ["../../outside", "", "abc", None]:
            with self.assertRaises(ValueError):
                self.store.ensure(bad)
        with self.assertRaises(ValueError):
            self.store.custom(self.a, {"name": " "})
        with self.assertRaises(ValueError):
            self.store.custom(str(uuid.uuid4()), {"name": "not_created"})

    def test_catalog_and_personal_names_do_not_collide(self):
        self.store.put(self.a, {"key": "catalog:blue_eyes", "name": "blue_eyes", "custom": False})
        self.store.custom(self.a, {"name": "blue_eyes"})
        self.assertEqual(len(self.store.entries(self.a)), 2)
        self.store.remove(self.a, "catalog:blue_eyes")
        self.assertTrue(self.store.entries(self.a)[0]["custom"])

    def test_v1_saved_records_are_read_without_rewriting_identifiers(self):
        old = {"key": "catalog:egyptian_toe", "name": "egyptian_toe", "description": "Old snapshot", "paths": [[{"id": "old_folder", "label": "Old folder"}]], "custom": False}
        self.store.put(self.a, old)
        self.assertEqual(catalog.Collections(self.path).entries(self.a), [old])


if __name__ == "__main__":
    unittest.main()
