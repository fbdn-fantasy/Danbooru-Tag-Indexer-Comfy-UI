"""Development harness, not ComfyUI. Tests the real routes with small host API shims.

Run: python tests/preview_server.py
Then visit http://127.0.0.1:8199 . All test data stays in tests/.cache/preview.
"""
import asyncio
import importlib.util
import json
import mimetypes
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/.cache/preview"
routes = {}


class RouteTable:
    def register(self, method, path):
        def decorator(function):
            routes[method, path] = function
            return function
        return decorator

    def get(self, path):
        return self.register("GET", path)

    def post(self, path):
        return self.register("POST", path)


class UserManager:
    def get_request_user_filepath(self, request, file):
        return str(DATA / "user" / file)


sys.modules["folder_paths"] = types.SimpleNamespace(get_user_directory=lambda: str(DATA))
sys.modules["aiohttp"] = types.SimpleNamespace(web=types.SimpleNamespace(json_response=lambda value, status=200, headers=None: (status, value)))
sys.modules["server"] = types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=RouteTable(), user_manager=UserManager())))
spec = importlib.util.spec_from_file_location("dti_preview", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Request:
    def __init__(self, handler, identifier=None):
        url = urlsplit(handler.path)
        self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.match_info = {"identifier": identifier}
        self.headers = handler.headers
        self.body = handler.rfile.read(int(handler.headers.get("Content-Length", 0)))

    async def json(self):
        return json.loads(self.body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        path = urlsplit(self.path).path
        function = routes.get((self.command, path))
        identifier = None
        prefix = "/danbooru-indexer/collections/"
        if function is None and path.startswith(prefix):
            identifier = path[len(prefix):]
            function = routes.get((self.command, prefix + "{identifier}"))
        if function:
            status, result = asyncio.run(function(Request(self, identifier)))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
            return
        files = {"/": ROOT / "tests/preview.html", "/scripts/app.js": ROOT / "tests/host_app.mjs", "/scripts/api.js": ROOT / "tests/host_api.mjs"}
        if path.startswith("/extensions/dti/"):
            file = (ROOT / "web" / path[len("/extensions/dti/"):]).resolve()
            if file.parent != (ROOT / "web").resolve():
                self.send_error(404)
                return
        else:
            file = files.get(path)
        if not file or not file.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript" if file.suffix in (".js", ".mjs") else mimetypes.guess_type(str(file))[0] or "text/plain")
        self.end_headers()
        self.wfile.write(file.read_bytes())

    def log_message(self, fmt, *args):
        if args and isinstance(args[0], str) and "favicon" in args[0]:
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    print("Development preview: http://127.0.0.1:8199 (not an actual ComfyUI host)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8199), Handler).serve_forever()
