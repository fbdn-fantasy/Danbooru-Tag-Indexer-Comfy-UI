"""Danbooru Tag Indexer for ComfyUI. No pip dependencies to install."""
import asyncio
import logging
from pathlib import Path

import folder_paths
from aiohttp import web  # Already required and provided by ComfyUI.
from server import PromptServer

from .catalog import Catalog, Collections, ROOT

WEB_DIRECTORY = "./web"
__version__ = "7.0.0"
LIBRARY_TYPE = "DANBOORU_TAG_LIBRARY"


class TagIndex:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = (LIBRARY_TYPE,)
    RETURN_NAMES = ("tag_library",)
    CATEGORY = "Danbooru Tag Indexer"
    FUNCTION = "library"
    DESCRIPTION = "Search and browse the offline tag index. Wire directly to Saved Tags to enable stars."

    def library(self):
        return ({"catalog": "bundled-v1"},)


class SavedTags:
    @classmethod
    def INPUT_TYPES(cls):
        return {"optional": {"tag_library": (LIBRARY_TYPE,)}}

    RETURN_TYPES = ()
    CATEGORY = "Danbooru Tag Indexer"
    FUNCTION = "view"
    OUTPUT_NODE = True
    DESCRIPTION = "View saved tags with descriptions and folder paths, copy names, and add personal entries. Works without running a prompt."

    def view(self, tag_library=None):
        return {"ui": {}}


NODE_CLASS_MAPPINGS = {"DanbooruTagIndex": TagIndex, "DanbooruSavedTags": SavedTags}
NODE_DISPLAY_NAME_MAPPINGS = {"DanbooruTagIndex": "Danbooru · Tag Index", "DanbooruSavedTags": "Danbooru · Saved Tags"}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

_catalog = Catalog(Path(__file__).parent / "data/catalog.sqlite.gz", Path(folder_paths.get_user_directory()) / "danbooru-tag-indexer-cache")
_routes = PromptServer.instance.routes


def user_store(request):
    # Use ComfyUI's user resolver, never a raw header or browser-supplied path.
    manager = PromptServer.instance.user_manager
    path = manager.get_request_user_filepath(request, "danbooru-tag-indexer/saved.sqlite")
    if not path:
        raise ValueError("ComfyUI could not resolve your user storage folder")
    return Collections(Path(path))


async def respond(function):
    try:
        result = await asyncio.to_thread(function)
        return web.json_response(result, headers={"Cache-Control": "no-store"})
    except (ValueError, KeyError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        logging.exception("Danbooru Tag Indexer request failed")
        return web.json_response({"error": "Could not read or save the library. Check the ComfyUI console and available disk space, then retry."}, status=500)


@_routes.get("/danbooru-indexer/catalog")
async def browse(request):
    return await respond(lambda: _catalog.browse(request.query.get("parent", ROOT), request.query.get("q", ""), request.query.get("offset", 0)))


@_routes.get("/danbooru-indexer/detail")
async def detail(request):
    return await respond(lambda: _catalog.detail(request.query.get("name", "")))


@_routes.get("/danbooru-indexer/outline")
async def outline(request):
    return await respond(lambda: _catalog.outline(request.query.get("name", ROOT)))


@_routes.get("/danbooru-indexer/collections")
async def collections(request):
    return await respond(lambda: user_store(request).list())


@_routes.get("/danbooru-indexer/collections/{identifier}")
async def entries(request):
    return await respond(lambda: user_store(request).entries(request.match_info["identifier"]))


@_routes.post("/danbooru-indexer/collections/{identifier}")
async def mutate(request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
    except (ValueError, TypeError):
        return web.json_response({"error": "Invalid JSON request"}, status=400)

    def action():
        store = user_store(request)
        identifier = request.match_info["identifier"]
        operation = data.get("action")
        if operation == "ensure":
            store.ensure(identifier, data.get("title", "Saved tags"))
        elif operation == "save":
            store.put(identifier, _catalog.snapshot(data.get("name", ""), data.get("path"), data.get("context")))
        elif operation == "custom":
            store.custom(identifier, data)
        elif operation == "remove":
            store.remove(identifier, data.get("key", ""))
        else:
            raise ValueError("Unknown library operation")
        return {"ok": True}

    return await respond(action)
