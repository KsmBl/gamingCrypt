"""Upload games, BIOS files and RetroArch cores from a browser in the same Wi-Fi.

Runs only while the upload page is open. The address carries a random token, files
go only into the Emulation folders on the encrypted drive, and arrive as a ".part"
file that's renamed when complete (an aborted upload leaves nothing half-done).
"""

from __future__ import annotations

import html
import json
import re
import secrets
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.systems import SYSTEMS

PORTS = range(8080, 8090)
CHUNK = 1024 * 1024
SAFE_NAME = re.compile(r"^[^/\\\0]+$")


def local_ip() -> str:
    """The address other devices in the network reach this one at (nothing is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET address: only picks the outgoing interface
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def targets(paths: EmulationPaths) -> dict[str, tuple[str, Path]]:
    """Upload folder id -> (label, folder)."""
    found = {f"roms/{s.folder}": (f"Games: {s.name}", paths.roms_for(s)) for s in SYSTEMS}
    found["bios"] = ("BIOS files", paths.bios)
    found["cores"] = ("RetroArch cores (*_libretro.so)", paths.cores)
    return found


def safe_name(name: str) -> str | None:
    name = Path(unquote(name)).name.strip()
    if not name or name.startswith(".") or not SAFE_NAME.match(name):
        return None
    return name


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>GamingCrypt upload</title><style>
body{{font-family:sans-serif;background:#0f1117;color:#e8eaf0;max-width:720px;margin:2em auto;padding:0 1em}}
select,input,button{{font-size:1.1em;padding:.5em;margin:.4em 0;width:100%;box-sizing:border-box}}
button{{background:#4f8cff;color:#fff;border:0;border-radius:8px}} .done{{color:#3fb950}} .err{{color:#e5484d}}
progress{{width:100%}}</style></head><body>
<h1>GamingCrypt</h1><p>Files go to the encrypted drive of your handheld.</p>
<label>Folder</label><select id="folder">{options}</select>
<input type="file" id="files" multiple><button onclick="send()">Upload</button>
<progress id="bar" value="0" max="1"></progress><ul id="log"></ul>
<script>
async function send(){{
  const files=[...document.getElementById('files').files], folder=document.getElementById('folder').value;
  const log=document.getElementById('log'), bar=document.getElementById('bar');
  for(const f of files){{
    const li=document.createElement('li'); li.textContent=f.name+' …'; log.prepend(li);
    await new Promise(done=>{{
      const x=new XMLHttpRequest();
      x.open('PUT','upload?folder='+encodeURIComponent(folder)+'&name='+encodeURIComponent(f.name));
      x.upload.onprogress=e=>{{bar.value=e.loaded/e.total}};
      x.onload=()=>{{li.textContent=f.name+(x.status==200?' ✓':' - '+x.responseText);
                    li.className=x.status==200?'done':'err';done()}};
      x.onerror=()=>{{li.textContent=f.name+' - connection lost';li.className='err';done()}};
      x.send(f);
    }});
  }}
}}
</script></body></html>"""


class UploadServer:
    def __init__(self, paths: EmulationPaths, on_received: Callable[[str, Path], None] | None = None,
                 token: str | None = None, ports=PORTS, host: str = "0.0.0.0"):
        self.paths = paths
        self.on_received = on_received or (lambda folder, path: None)
        self.token = token or secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
        self.ports, self.host = ports, host
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def port(self) -> int | None:
        return self.server.server_address[1] if self.server else None

    def url(self, ip: str | None = None) -> str:
        return f"http://{ip or local_ip()}:{self.port}/{self.token}/"

    def start(self) -> bool:
        handler = self._handler()
        for port in self.ports:
            try:
                self.server = ThreadingHTTPServer((self.host, port), handler)
                break
            except OSError:
                continue
        if self.server is None:
            return False
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="gamingcrypt-upload", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # quiet
                pass

            def _reply(self, code: int, body: str, kind: str = "text/plain; charset=utf-8") -> None:
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self) -> tuple[str, dict] | None:
                url = urlparse(self.path)
                prefix = f"/{owner.token}/"
                if not url.path.startswith(prefix):
                    return None
                return url.path[len(prefix):], parse_qs(url.query)

            def do_GET(self) -> None:  # noqa: N802
                route = self._route()
                if route is None:
                    self._reply(404, "not found")
                    return
                path, _query = route
                if path == "folders":
                    self._reply(200, json.dumps({k: v[0] for k, v in targets(owner.paths).items()}),
                                "application/json")
                    return
                options = "".join(f'<option value="{html.escape(k)}">{html.escape(label)}</option>'
                                  for k, (label, _p) in targets(owner.paths).items())
                self._reply(200, PAGE.format(options=options), "text/html; charset=utf-8")

            def do_PUT(self) -> None:  # noqa: N802
                route = self._route()
                if route is None or route[0] != "upload":
                    self._reply(404, "not found")
                    return
                query = route[1]
                folder_id = (query.get("folder") or [""])[0]
                name = safe_name((query.get("name") or [""])[0])
                folder = targets(owner.paths).get(folder_id)
                if folder is None or name is None:
                    self._reply(400, "bad folder or file name")
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self._reply(411, "length required")
                    return
                target_dir = folder[1]
                target_dir.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(target_dir).free < length + 64 * 1024 * 1024:
                    self._reply(507, "not enough space on the drive")
                    return
                part = target_dir / f".{name}.part"
                received = 0
                try:
                    with open(part, "wb") as out:
                        while received < length:
                            chunk = self.rfile.read(min(CHUNK, length - received))
                            if not chunk:
                                break
                            out.write(chunk)
                            received += len(chunk)
                    if received != length:
                        raise OSError("upload incomplete")
                    final = target_dir / name
                    part.replace(final)
                except OSError as exc:
                    part.unlink(missing_ok=True)
                    self._reply(500, str(exc))
                    return
                owner.on_received(folder_id, final)
                self._reply(200, "ok")

        return Handler
