"""Upload games, BIOS files and RetroArch cores from a browser in the same Wi-Fi.

Runs only while the upload page is open. The address carries a random token, files
go only into the Emulation folders on the encrypted drive, and arrive as a ".part"
file that's renamed when complete (an aborted upload leaves nothing half-done).
"""

from __future__ import annotations

import html
import json
import re
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
    from gamingcrypt.emulation.bios import UPLOAD_KINDS

    # BIOS by kind: named and put where its emulator looks (emulation/bios.place)
    incoming = paths.bios / ".incoming"
    found.update({f"bios:{kind}": (f"BIOS: {label}", incoming) for kind, label in UPLOAD_KINDS.items()})
    found["bios"] = ("BIOS: other file (bios folder as it is)", paths.bios)
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
select,button,.pick{{font-size:1.1em;padding:.6em;margin:.4em 0;width:100%;box-sizing:border-box;border-radius:8px}}
button{{background:#4f8cff;color:#fff;border:0}} button:disabled{{background:#3a3f4b;color:#8b93a7}}
.pick{{display:block;text-align:center;border:2px dashed #4f8cff;color:#e8eaf0;cursor:pointer}}
.pick.over{{background:#1d2433}} #files{{position:absolute;opacity:0;width:1px;height:1px;overflow:hidden}}
#chosen{{color:#8b93a7}} .done{{color:#3fb950}} .err{{color:#e5484d}} progress{{width:100%}}</style></head><body>
<h1>GamingCrypt</h1><p>Files go to the encrypted drive of your handheld.</p>
<label for="folder">Folder</label><select id="folder">{options}</select>
<input type="file" id="files" multiple>
<label for="files" class="pick" id="drop">Choose files - or drop them here</label>
<p id="chosen">No files chosen</p>
<button id="send" disabled>Upload</button>
<progress id="bar" value="0" max="1"></progress><ul id="log"></ul>
<script>
const input=document.getElementById('files'), drop=document.getElementById('drop'),
      chosenText=document.getElementById('chosen'), sendButton=document.getElementById('send');
let chosen=[];
function size(n){{const u=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<3){{n/=1024;i++}}
  return (i?n.toFixed(1):n)+' '+u[i]}}
function choose(list){{
  chosen=[...list];
  const total=chosen.reduce((s,f)=>s+f.size,0);
  chosenText.textContent=chosen.length
    ? chosen.length+(chosen.length==1?' file':' files')+' chosen ('+size(total)+'): '+chosen.map(f=>f.name).join(', ')
    : 'No files chosen';
  sendButton.disabled=!chosen.length;
}}
input.addEventListener('change',()=>choose(input.files));
input.addEventListener('input',()=>choose(input.files));
['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{{e.preventDefault();drop.classList.add('over')}}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,()=>drop.classList.remove('over')));
drop.addEventListener('drop',e=>{{e.preventDefault();choose(e.dataTransfer.files)}});
sendButton.addEventListener('click',send);
async function send(){{
  const files=chosen, folder=document.getElementById('folder').value;
  const log=document.getElementById('log'), bar=document.getElementById('bar');
  sendButton.disabled=true;
  for(const f of files){{
    const li=document.createElement('li'); li.textContent=f.name+' …'; log.prepend(li);
    await new Promise(done=>{{
      const x=new XMLHttpRequest();
      x.open('PUT','upload?folder='+encodeURIComponent(folder)+'&name='+encodeURIComponent(f.name));
      x.upload.onprogress=e=>{{bar.value=e.total?e.loaded/e.total:0}};
      x.onload=()=>{{const note=x.responseText!='ok'?' - '+x.responseText:'';
                    li.textContent=f.name+(x.status==200?' ✓'+note:' - '+x.responseText);
                    li.className=x.status==200?'done':'err';done()}};
      x.onerror=()=>{{li.textContent=f.name+' - connection lost';li.className='err';done()}};
      x.send(f);
    }});
  }}
  input.value=''; choose([]);
}}
</script></body></html>"""


class UploadServer:
    def __init__(self, paths: EmulationPaths | None, on_received: Callable[[str, Path], None] | None = None,
                 token: str | None = None, ports=PORTS, host: str = "0.0.0.0",
                 folders: Callable[[], dict[str, tuple[str, Path]]] | None = None):
        self.paths = paths
        self.folders = folders or (lambda: targets(paths))  # folder id -> (label, folder)
        self.on_received = on_received or (lambda folder, path: None)
        from gamingcrypt.emulation.words import phrase

        self.token = token or phrase()  # two words: easy to type into a phone
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
                    self._reply(200, json.dumps({k: v[0] for k, v in owner.folders().items()}),
                                "application/json")
                    return
                options = "".join(f'<option value="{html.escape(k)}">{html.escape(label)}</option>'
                                  for k, (label, _p) in owner.folders().items())
                self._reply(200, PAGE.format(options=options), "text/html; charset=utf-8")

            def do_PUT(self) -> None:  # noqa: N802
                route = self._route()
                if route is None or route[0] != "upload":
                    self._reply(404, "not found")
                    return
                query = route[1]
                folder_id = (query.get("folder") or [""])[0]
                name = safe_name((query.get("name") or [""])[0])
                folder = owner.folders().get(folder_id)
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
                message = "ok"
                if folder_id.startswith("bios:"):
                    from gamingcrypt.emulation import bios

                    ok, message, written = bios.place(owner.paths, folder_id[5:], final)
                    if not ok:
                        self._reply(422, message)
                        return
                    for path in written:
                        owner.on_received("bios", path)
                else:
                    owner.on_received(folder_id, final)
                self._reply(200, message)

        return Handler
