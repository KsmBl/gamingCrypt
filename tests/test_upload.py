"""Add games / cores / BIOS over Wi-Fi: browser upload and SMB share, only while the page is open."""

import http.client
import re
import subprocess

import pytest
from PySide6.QtCore import QUrl

from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.sharing import SmbShare
from gamingcrypt.emulation.upload_server import UploadServer, safe_name, targets
from gamingcrypt.helper import veracrypt_helper as helper

try:  # must be imported before the QApplication exists
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - optional
    QWebEngineView = None


@pytest.fixture
def paths(tmp_path):
    p = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    p.ensure()
    return p


@pytest.fixture
def server(paths):
    got = []
    s = UploadServer(paths, lambda folder, path: got.append((folder, path.name)), token="tok123",
                     ports=range(18080, 18120), host="127.0.0.1")
    assert s.start()
    s._got = got
    yield s
    s.stop()


def request(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    return response.status, response.read().decode()


def test_page_and_upload(server, paths):
    status, page = request(server, "GET", "/tok123/")
    assert status == 200 and "roms/snes" in page and "RetroArch cores" in page
    status, _ = request(server, "PUT", "/tok123/upload?folder=roms/snes&name=Super%20Mario%20World.sfc", b"ROM!")
    assert status == 200 and (paths.roms / "snes" / "Super Mario World.sfc").read_bytes() == b"ROM!"
    request(server, "PUT", "/tok123/upload?folder=cores&name=snes9x_libretro.so", b"core")
    assert (paths.cores / "snes9x_libretro.so").exists()
    assert server._got == [("roms/snes", "Super Mario World.sfc"), ("cores", "snes9x_libretro.so")]
    assert server.url("192.168.1.198") == f"http://192.168.1.198:{server.port}/tok123/"


def run_js(qtbot, view, script):
    results = []
    view.page().runJavaScript(script, 0, results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    return results[0]


@pytest.mark.skipif(QWebEngineView is None, reason="needs QtWebEngine")
def test_browser_shows_the_chosen_files_and_uploads_them(qtbot, server, paths):
    view = QWebEngineView()
    qtbot.addWidget(view)
    with qtbot.waitSignal(view.loadFinished, timeout=10000):
        view.load(QUrl(server.url("127.0.0.1")))
    assert run_js(qtbot, view, "document.getElementById('chosen').textContent") == "No files chosen"
    assert run_js(qtbot, view, "document.getElementById('send').disabled") is True
    run_js(qtbot, view, """(() => {
        const dt = new DataTransfer();
        dt.items.add(new File(['ROM!'], 'Chrono Trigger.sfc'));
        dt.items.add(new File(['x'.repeat(2048)], 'Zelda.sfc'));
        const input = document.getElementById('files');
        input.files = dt.files;
        input.dispatchEvent(new Event('change'));
        document.getElementById('folder').value = 'roms/snes';
        return true; })()""")
    assert run_js(qtbot, view, "document.getElementById('chosen').textContent") == \
        "2 files chosen (2.0 KB): Chrono Trigger.sfc, Zelda.sfc"
    run_js(qtbot, view, "document.getElementById('send').click(); true")
    qtbot.waitUntil(lambda: len(server._got) == 2, timeout=5000)
    assert (paths.roms / "snes" / "Chrono Trigger.sfc").read_bytes() == b"ROM!"
    qtbot.waitUntil(lambda: run_js(qtbot, view, "document.getElementById('chosen').textContent")
                    == "No files chosen", timeout=5000)
    assert run_js(qtbot, view, "document.querySelectorAll('#log .done').length") == 2


def test_refused_requests(server, paths):
    assert request(server, "GET", "/wrong/")[0] == 404  # no token, no page
    assert request(server, "PUT", "/tok123/upload?folder=../../etc&name=x", b"x")[0] == 400
    assert request(server, "PUT", "/tok123/upload?folder=bios&name=..%2F..%2Fevil", b"x")[0] == 200
    assert (paths.bios / "evil").exists() and not (paths.root.parent / "evil").exists()  # stays in bios/
    assert request(server, "PUT", "/tok123/upload?folder=bios&name=.hidden", b"x")[0] == 400


def test_aborted_upload_leaves_nothing(server, paths):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("PUT", "/tok123/upload?folder=bios&name=big.bin")
    conn.putheader("Content-Length", "1000")
    conn.endheaders()
    conn.send(b"only a bit")
    conn.close()  # connection lost
    import time

    time.sleep(0.3)
    assert not (paths.bios / "big.bin").exists() and not list(paths.bios.glob(".*.part"))


def test_safe_names_and_targets(paths):
    assert safe_name("a%2Fb.sfc") == "b.sfc" and safe_name("") is None and safe_name(".x") is None
    assert set(targets(paths)) >= {"roms/snes", "roms/psx", "bios", "cores"}


# --- SMB through the helper -------------------------------------------------------------------

def test_helper_smb_config_only_shares_inside_home(tmp_path):
    run_dir = str(tmp_path / "run")
    home = tmp_path / "home"
    share = home / "GamingCrypt" / "Emulation"
    share.mkdir(parents=True)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    helper.SMB_TOOLS["smbd"].insert(0, "/bin/true")
    helper.SMB_TOOLS["smbpasswd"].insert(0, "/bin/true")
    try:
        assert helper.smb_start([str(tmp_path / "elsewhere")], "password1", str(home), "gay", run, run_dir) == 2
        assert helper.smb_start([str(share)], "short", str(home), "gay", run, run_dir) == 2
        assert helper.smb_start([str(share)], "password1", str(home), "gay", run, run_dir) == 0
    finally:
        helper.SMB_TOOLS["smbd"].pop(0)
        helper.SMB_TOOLS["smbpasswd"].pop(0)
    conf = (tmp_path / "run" / "smb.conf").read_text()
    assert f"path = {share}" in conf and "valid users = gay" in conf and "map to guest = never" in conf
    assert calls[0][1] == "password1\npassword1\n" and "-a" in calls[0][0]  # password on stdin only
    assert calls[1][0][-1] == "-D"
    (tmp_path / "run" / "smbd.pid").write_text("4242")
    killed = []
    helper.smb_stop(run_dir, kill=lambda pid, sig: killed.append(pid))
    assert killed == [4242] and not (tmp_path / "run").exists()


def test_helper_main_dispatches_smb(monkeypatch):
    seen = []
    monkeypatch.setattr(helper, "smb_stop", lambda: seen.append("stop") or 0)
    assert helper.main(["smb-stop"]) == 0 and seen == ["stop"]


def test_share_client():
    from gamingcrypt.helper.veracrypt_helper import HELPER_VERSION

    calls = []

    def run(cmd, **kw):
        if cmd[-1] == "version":
            return subprocess.CompletedProcess(cmd, 0, f"{HELPER_VERSION}\n", "")
        calls.append((cmd, kw.get("input")))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    share = SmbShare(helper="/h", runner=run, exists=lambda p: True, user="gay")
    assert share.start("/home/gay/GamingCrypt/Emulation") == (True, "")
    assert calls[0][0] == ["sudo", "-n", "/h", "smb-start", "/home/gay/GamingCrypt/Emulation"]
    assert calls[0][1] == share.password + "\n" and re.fullmatch(r"([A-Z][a-z]+){2}", share.password)
    share.stop()
    share.stop()  # only once
    assert [c[0][-1] for c in calls] == ["/home/gay/GamingCrypt/Emulation", "smb-stop"]
    assert SmbShare(helper="/h", exists=lambda p: False).start("/x")[1].startswith("Run ./install.sh")


# --- the page --------------------------------------------------------------------------------

class FakeShare:
    def __init__(self, ok=True):
        self.ok, self.user, self.password, self.running, self.events = ok, "gay", "Secret1234", False, []

    def start(self, folder):
        self.events.append(("start", folder))
        self.running = self.ok
        return (True, "") if self.ok else (False, "Samba is not installed (run ./install.sh)")

    def stop(self):
        self.events.append(("stop",))
        self.running = False


def new_page(paths, share):
    from gamingcrypt.ui.upload_page import UploadPage

    factory = lambda p, cb: UploadServer(p, cb, token="t", ports=range(18120, 18160), host="127.0.0.1")  # noqa
    return UploadPage(paths, server_factory=factory, share=share, ip=lambda: "192.168.1.198")


def make_page(qtbot, paths, share):
    page = new_page(paths, share)
    qtbot.addWidget(page)
    return page


def test_page_shows_both_ways_and_stops_them_when_left(qtbot, paths):
    share = FakeShare()
    page = make_page(qtbot, paths, share)
    page.show()
    assert page.url.text().startswith("http://192.168.1.198:") and page.url.text().endswith("/t/")
    qtbot.waitUntil(lambda: "Password: Secret1234" in page.smb.text())
    assert "\\\\192.168.1.198\\GamingCrypt" in page.smb.text() and "User: gay" in page.smb.text()
    port = page.server.port
    status = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    status.request("PUT", "/t/upload?folder=roms/gba&name=Pokemon.gba", body=b"x")
    assert status.getresponse().status == 200
    qtbot.waitUntil(lambda: "roms/gba/Pokemon.gba" in page.log.text())
    page.hide()  # left the page
    assert page.server is None and ("stop",) in share.events
    with pytest.raises(OSError):
        http.client.HTTPConnection("127.0.0.1", port, timeout=1).request("GET", "/t/")


def test_share_not_available(qtbot, paths):
    page = make_page(qtbot, paths, FakeShare(ok=False))
    page.show()
    qtbot.waitUntil(lambda: "Not available" in page.smb.text())
    page.hide()


def test_games_tab_add_games(qtbot, paths, monkeypatch):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"],
                   emulation_root=str(paths.root))
    tab.upload_page_factory = lambda p: new_page(p, FakeShare())  # the tab deletes it when left
    qtbot.addWidget(tab)
    tab.show()
    assert tab.home.add_card.isVisible()
    tab.home.add_card.tapped.emit()
    page = tab.currentWidget()
    assert page.server is not None
    (paths.roms / "snes" / "Zelda.sfc").write_text("x")
    page.done_button.click()
    assert tab.currentWidget() is tab.home and page.server is None
    qtbot.waitUntil(lambda: "snes" in tab.home.system_cards)  # rescanned


def test_no_add_card_without_the_drive(qtbot):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"])
    qtbot.addWidget(tab)
    tab.show()
    assert not tab.home.add_card.isVisible()


def test_it_says_these_are_emulator_games(qtbot, paths):
    """Adding games here is only for the emulators - Steam games come from the Steam library."""
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.emulation.systems import BY_ID
    from gamingcrypt.ui.emulation_pages import SystemPage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"],
                   emulation_root=str(paths.root))
    qtbot.addWidget(tab)
    assert tab.home.add_card.title.text() == "⬆ Add ROMs"
    assert tab.home.add_card.subtitle.text().startswith("Emulator games")
    assert SystemPage(tab, BY_ID["snes"], []).add_button.text() == "⬆  Add ROMs"
    page = make_page(qtbot, paths, FakeShare())
    texts = " ".join(label.text() for label in page.findChildren(type(page.log)))
    assert "Add emulator games" in texts and "emulators (RetroArch) only" in texts and "Steam games" in texts


def test_qr_codes_for_the_phone(qtbot, paths):
    from gamingcrypt.ui.qr import qr_pixmap
    from gamingcrypt.ui.upload_page import smb_url

    assert smb_url("192.168.1.198", "gay", "a/b:c") == "smb://gay:a%2Fb%3Ac@192.168.1.198/GamingCrypt"
    pixmap = qr_pixmap("http://192.168.1.198:8080/t/", 220)
    assert pixmap is not None and pixmap.width() == pixmap.height() and 180 <= pixmap.width() <= 220
    image = pixmap.toImage()
    assert image.pixelColor(2, 2).name() == "#ffffff"  # quiet zone: phones need it
    assert any(image.pixelColor(x, x).name() == "#000000" for x in range(pixmap.width()))
    page = make_page(qtbot, paths, FakeShare())
    page.show()
    assert page.browser_qr.isVisible() and page.browser_qr.qr_text == page.url.text()
    qtbot.waitUntil(lambda: page.smb_qr.isVisible())
    assert page.smb_qr.qr_text == "smb://gay:Secret1234@192.168.1.198/GamingCrypt"
    page.hide()


def test_no_smb_qr_without_the_share(qtbot, paths):
    page = make_page(qtbot, paths, FakeShare(ok=False))
    page.show()
    qtbot.waitUntil(lambda: "Not available" in page.smb.text())
    assert not page.smb_qr.isVisible() and page.browser_qr.isVisible()
    page.hide()


def test_qr_without_segno(monkeypatch):
    import builtins

    from gamingcrypt.ui.qr import qr_pixmap

    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **k: (_ for _ in ()).throw(ImportError()) if name == "segno"
                        else real(name, *a, **k))
    assert qr_pixmap("x") is None


def test_passwords_and_addresses_are_two_words(paths):
    from gamingcrypt.emulation.sharing import new_password
    from gamingcrypt.emulation.words import WORDS, phrase

    assert len(set(WORDS)) == len(WORDS) >= 300 and all(w.isalpha() and w.islower() for w in WORDS)
    for _ in range(50):
        word = phrase()
        parts = re.findall(r"[A-Z][a-z]+", word)
        assert len(parts) == 2 and "".join(parts) == word and all(p.lower() in WORDS for p in parts)
    assert re.fullmatch(r"([A-Z][a-z]+){2}", new_password())
    assert len({phrase() for _ in range(30)}) > 20  # random
    server = UploadServer(paths)
    assert re.fullmatch(r"([A-Z][a-z]+){2}", server.token)


# --- BIOS by kind ------------------------------------------------------------------------------

def _zip(files):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_bios_kinds_are_offered(server):
    _status, page = request(server, "GET", "/tok123/")
    assert "BIOS: PlayStation (PS1) BIOS" in page and "BIOS: Switch firmware" in page
    assert "BIOS: PlayStation 2 BIOS" in page and "bios:switch-keys" in page


def test_ps1_bios_is_named_by_its_checksum(server, paths, monkeypatch):
    import hashlib

    from gamingcrypt.emulation import bios

    data = b"ps1 bios"
    monkeypatch.setitem(bios.REQUIREMENTS, "psx", bios.Requirement(
        {"scph5501.bin": hashlib.md5(data).hexdigest(), "scph1001.bin": "0" * 32}))
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:psx&name=PSX%20BIOS%20(USA).bin", data)
    assert status == 200 and text == "saved as scph5501.bin (known good)"
    assert (paths.bios / "scph5501.bin").read_bytes() == data and not list((paths.bios / ".incoming").iterdir())
    assert ("bios", "scph5501.bin") in server._got
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:psx&name=mine.bin", b"other")
    assert status == 422 and "already have a known good" in text  # the good one stays
    assert (paths.bios / "scph5501.bin").read_bytes() == data
    (paths.bios / "scph5501.bin").unlink()
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:psx&name=mine.bin", b"other")
    assert status == 200 and "unknown version" in text and (paths.bios / "scph5501.bin").read_bytes() == b"other"


def test_bios_zip_and_dreamcast_subfolder(server, paths):
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:dreamcast&name=dc.zip",
                           _zip({"bios/dc_boot.bin": b"boot", "readme.txt": b"hi"}))
    assert status == 200 and (paths.bios / "dc" / "dc_boot.bin").read_bytes() == b"boot"
    assert not (paths.bios / "readme.txt").exists()


def test_ps2_bios_goes_to_its_folder(server, paths):
    status, _ = request(server, "PUT", "/tok123/upload?folder=bios:ps2&name=SCPH-70004.bin", b"ps2")
    assert status == 200 and (paths.bios / "pcsx2" / "bios" / "SCPH-70004.bin").read_bytes() == b"ps2"


def test_switch_keys_are_recognised_by_content(server, paths):
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:switch-keys&name=keys.txt",
                           b"header_key = 0123\nmaster_key_00 = 4567\n")
    assert status == 200 and text == "saved as prod.keys" and (paths.bios / "switch" / "prod.keys").exists()
    title = b"0" * 32 + b" = " + b"1" * 32 + b"\n"
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:switch-keys&name=t.txt", title)
    assert text == "saved as title.keys"
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:switch-keys&name=x.txt", b"hello")
    assert status == 422 and "no Switch keys" in text


def test_switch_firmware_zip_is_unpacked(server, paths):
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:switch-firmware&name=Firmware%2019.zip",
                           _zip({"Firmware 19/a.nca": b"a", "Firmware 19/b.nca": b"b", "note.txt": b"x"}))
    firmware = paths.bios / "switch" / "firmware"
    assert status == 200 and text == "2 firmware files" and sorted(f.name for f in firmware.iterdir()) == ["a.nca", "b.nca"]
    status, text = request(server, "PUT", "/tok123/upload?folder=bios:switch-firmware&name=x.zip", _zip({"a.txt": b""}))
    assert status == 422 and "no firmware" in text


def test_place_rejects_unknown_kinds(paths, tmp_path):
    from gamingcrypt.emulation import bios

    upload = tmp_path / "x.bin"
    upload.write_bytes(b"x")
    assert bios.place(paths, "snes", upload)[0] is False and not upload.exists()
