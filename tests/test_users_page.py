"""Settings -> Security -> Users, and the app with more than one user."""

import copy
from pathlib import Path

import pytest

from gamingcrypt import users
from gamingcrypt.config import DEFAULTS
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.users_page import CodeFlow, NamePage
from gamingcrypt.unlock import kdf
from tests.test_users import ADMIN_CODE, FAST, Volume, verify


def config():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method="pin", volume="/tmp/x.vc", kdf=kdf.new_params(**FAST))
    return cfg


@pytest.fixture
def tab(qtbot):
    from gamingcrypt.ui.settings_tab import SettingsTab

    saved = []
    tab = SettingsTab(config(), lambda c: saved.append(copy.deepcopy(c)), system=SystemControls(), admin_check=verify)
    tab._saved = saved
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    tab.show_sub_tab("Security")
    return tab


def enter_new(flow, method, code, repeat=None):
    flow.choose_method(method)
    flow.input.secret_entered.emit(code)
    flow.input.secret_entered.emit(code if repeat is None else repeat)


def add(qtbot, tab, name, method, code, admin_code=ADMIN_CODE):
    section = tab.users_section
    section.add_button.click()
    page = tab.currentWidget()
    assert isinstance(page, NamePage)
    page.edit.setText(name)
    page.ok_button.click()
    flow = tab.currentWidget()
    assert isinstance(flow, CodeFlow)
    enter_new(flow, method, code)
    flow.input.secret_entered.emit(admin_code)
    return flow


def test_one_admin_at_first(tab):
    section = tab.users_section
    assert list(section.rows) == ["admin"] and "admin  ·  Admin" in section.rows["admin"]["label"].text()
    assert set(section.rows["admin"]) == {"label", "rename"}  # no age, no deleting, the code is the drive's own
    assert section.add_button.isVisibleTo(tab) and tab.reset_button.isVisibleTo(tab)


def test_adding_a_user(qtbot, tab):
    section = tab.users_section
    flow = add(qtbot, tab, "Mia", "pattern", "14789")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    cfg = tab.config
    mia = users.all_users(cfg)[1]
    assert (mia.name, mia.method, mia.admin) == ("Mia", "pattern", False) and "Mia can log in now" in tab.status.text()
    assert users.volume_password(cfg, mia.id, "14789") == kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"])
    assert tab._saved[-1]["users"][0]["name"] == "Mia" and "keyring" in tab._saved[-1]["unlock"]
    assert set(section.rows[mia.id]) == {"label", "rename", "age", "code", "delete", "locks"}
    assert flow is not tab.currentWidget()


def test_the_admins_code_has_to_be_right(qtbot, tab):
    """Wrong: only the admin's code is asked again - Mia's new code, chosen and repeated before
    it, stays (it was all thrown away and asked from the start)."""
    flow = add(qtbot, tab, "Mia", "pin", "1111", admin_code="000000")
    qtbot.waitUntil(lambda: "not the admin's code" in flow.status.text(), timeout=10000)
    assert tab.currentWidget() is flow and len(users.all_users(tab.config)) == 1
    assert flow.index == 1 and "admin's code" in flow.prompt.text() and flow.answers["new"] == "1111"
    flow.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    mia = users.all_users(tab.config)[1]
    assert users.volume_password(tab.config, mia.id, "1111")  # the code entered before the wrong one


def test_a_new_code_has_to_be_repeated(qtbot, tab):
    tab.users_section.add_button.click()
    tab.currentWidget().edit.setText("Mia")
    tab.currentWidget().ok_button.click()
    flow = tab.currentWidget()
    enter_new(flow, "pin", "1111", repeat="1112")
    assert "didn't match" in flow.status.text() and flow.index == 0 and "Choose the new PIN" in flow.prompt.text()
    flow.input.secret_entered.emit("1111")
    assert "Repeat" in flow.prompt.text()
    assert flow.gamepad_back() and tab.currentWidget() is tab.overview  # given up: nothing happened
    assert len(users.all_users(tab.config)) == 1


def test_names(qtbot, tab):
    section = tab.users_section
    section.add_button.click()
    page = tab.currentWidget()
    page.edit.setText("ADMIN")
    page.ok_button.click()
    assert "already a user called" in page.status.text() and tab.currentWidget() is page
    page.cancel_button.click()
    assert tab.currentWidget() is tab.overview
    section.rows["admin"]["rename"].click()
    page = tab.currentWidget()
    assert page.edit.text() == "admin"
    page.edit.setText("Papa")
    page.ok_button.click()
    assert users.admin(tab.config).name == "Papa" and tab._saved[-1]["admin"] == {"name": "Papa"}
    assert "Papa  ·  Admin" in section.rows["admin"]["label"].text()


def test_age_new_code_and_deleting(qtbot, tab):
    from gamingcrypt.ui.modal import open_modal

    add(qtbot, tab, "Mia", "pin", "1111")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    section, cfg = tab.users_section, tab.config
    mia = users.all_users(cfg)[1]
    age = section.rows[mia.id]["age"]
    assert age.currentData() is None and [age.itemData(i) for i in range(age.count())] == [None, 0, 6, 12, 16, 18]
    age.setCurrentIndex(age.findData(12))
    assert users.get(cfg, mia.id).age == 12 and tab._saved[-1]["users"][0]["age"] == 12
    assert section.rows[mia.id]["age"].currentData() == 12
    section.rows[mia.id]["code"].click()  # the admin gives her another one
    flow = tab.currentWidget()
    enter_new(flow, "password", "geheim")
    flow.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    assert users.volume_password(cfg, mia.id, "1111") is None and users.volume_password(cfg, mia.id, "geheim")
    assert users.get(cfg, mia.id).method == "password" and users.get(cfg, mia.id).age == 12
    section.rows[mia.id]["delete"].click()
    modal = open_modal(tab)
    assert "Delete the user Mia?" in modal.content.question.text() and len(users.all_users(cfg)) == 2
    modal.content.action_button.click()
    assert [u.name for u in users.all_users(cfg)] == ["admin"] and tab._saved[-1]["users"] == []


def test_a_user_sees_only_themselves_and_changes_their_own_code(qtbot):
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master)
    users.add(cfg, "Ben", "pin", "2222", master)
    users.enter(cfg, mia.id)
    tab = SettingsTab(cfg, lambda c: None, system=SystemControls())
    qtbot.addWidget(tab)
    tab.show()
    tab.show_sub_tab("Security")  # (not there for a user - see below; the section itself still knows who's who)
    section = tab.users_section
    assert list(section.rows) == [mia.id] and set(section.rows[mia.id]) == {"label", "code"}
    assert section.add_button.isHidden() and tab.reset_button.isHidden()
    assert "logged in as Mia" in section.hint.text()
    section.rows[mia.id]["code"].click()
    flow = tab.currentWidget()
    flow.input.secret_entered.emit("9999")  # not her current one
    enter_new(flow, "pin", "3333")
    qtbot.waitUntil(lambda: "not your current code" in flow.status.text(), timeout=10000)
    assert flow.index == 0 and flow.answers["new"] == "3333"  # only the current one again
    flow.input.secret_entered.emit("1111")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    assert users.volume_password(cfg, mia.id, "3333") and users.volume_password(cfg, mia.id, "1111") is None


def test_a_changed_code_is_the_one_the_lock_after_sleep_checks(qtbot):
    """Whoever is logged in changes their own code: the lock after sleep must take the new one
    (it kept checking the old one). Another user's new code doesn't touch it."""
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master)
    users.enter(cfg, mia.id)
    changed = []
    tab = SettingsTab(cfg, lambda c: None, system=SystemControls(), code_changed=changed.append)
    qtbot.addWidget(tab)
    tab.show()
    tab.users_section.rows[mia.id]["code"].click()
    flow = tab.currentWidget()
    flow.input.secret_entered.emit("1111")
    enter_new(flow, "pin", "3333")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    assert changed == ["3333"]


def test_the_admin_giving_someone_a_code_keeps_the_admins_check(qtbot, tab):
    changed = []
    tab.users_section.code_changed = changed.append
    add(qtbot, tab, "Mia", "pin", "1111")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    mia = users.all_users(tab.config)[1]
    tab.users_section.rows[mia.id]["code"].click()
    flow = tab.currentWidget()
    enter_new(flow, "pin", "2222")
    flow.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    assert changed == []  # Mia's code: the admin still unlocks with their own


def test_the_admins_new_drive_code_is_the_one_the_lock_after_sleep_checks(qtbot, tab):
    from PySide6.QtWidgets import QWidget

    changed = []
    tab.code_changed = changed.append
    wizard = QWidget()  # (the reset wizard, done: its new code)
    wizard.new_secret = "918273"
    tab.wizard = wizard
    tab.addWidget(wizard)
    tab._reset_done()
    assert changed == ["918273"] and tab.wizard is None and "Unlock method changed" in tab.status.text()


def test_the_app_hands_new_codes_to_the_lock_after_sleep(qtbot, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.unlock.verifier import VerifyUnlocker

    cfg = config()
    window = MainWindow(cfg, lambda c: None, Volume("x").factory, page_factory=lambda c: {})
    qtbot.addWidget(window)
    window.verifier_path = tmp_path / "verifier"
    window.remember_code(ADMIN_CODE)
    window.show_shell()
    settings = window.shell.pages["Settings"]
    assert settings.code_changed == window.remember_code
    settings.code_changed("5555")
    assert VerifyUnlocker(window.verifier).unlock("5555").success
    assert not VerifyUnlocker(window.verifier).unlock(ADMIN_CODE).success


# --- the app -----------------------------------------------------------------------------------

def test_logging_in_as_a_user_and_locking_again(qtbot, tmp_path):
    from gamingcrypt.app import MainWindow

    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pattern", "14789", master, age=12)
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    cfg["steam"]["api_key"] = "A" * 32
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    saved = []
    window = MainWindow(cfg, lambda c: saved.append(copy.deepcopy(c)), volume.factory, page_factory=lambda c: {})
    qtbot.addWidget(window)
    lock = window.stack.currentWidget()
    assert window.screen_name == "lock" and lock.user_row.isVisibleTo(lock) and lock.user.admin
    lock.user_buttons[mia.id].click()
    lock.input.secret_entered.emit("14789")
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    assert users.current(cfg).id == mia.id and cfg["steam"]["api_key"] == ""  # her own Steam settings
    assert saved[-1]["last_user"] == mia.id and "session" not in saved[-1]
    assert saved[-1]["steam"]["api_key"] == "A" * 32  # the admin's are written as the admin's
    assert window.verifier["user"] == mia.id and not window.is_admin_code(ADMIN_CODE)
    settings = window.shell.pages["Settings"]
    assert list(settings.users_section.rows) == [mia.id] and not settings.reset_button.isVisibleTo(settings)
    window.panic_lock()
    lock = window.stack.currentWidget()
    assert window.screen_name == "lock" and users.current(cfg).admin and cfg["steam"]["api_key"] == "A" * 32
    assert lock.user.id == mia.id and lock.method == "pattern"  # who was there last is chosen
    lock.user_buttons["admin"].click()
    lock.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    assert users.current(cfg).admin and window.is_admin_code(ADMIN_CODE) and not window.is_admin_code("14789")
    assert len(window.shell.pages["Settings"].users_section.rows) == 2


def test_a_config_from_before_starts_as_ever(qtbot, tmp_path):
    from gamingcrypt.app import MainWindow

    cfg = config()
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    before = copy.deepcopy(cfg)
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    saved = []
    window = MainWindow(cfg, lambda c: saved.append(copy.deepcopy(c)), volume.factory, page_factory=lambda c: {})
    qtbot.addWidget(window)
    lock = window.stack.currentWidget()
    assert not lock.user_row.isVisibleTo(lock) and lock.method == "pin"
    lock.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    assert users.current(cfg).admin and saved == []  # nothing rewritten
    assert {k: v for k, v in cfg.items() if k != "session"} == before


# --- what a user can't do, and what's their own --------------------------------------------------

@pytest.fixture
def emu(tmp_path):
    from gamingcrypt.emulation.library import EmulationPaths

    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Mario.sfc").write_bytes(b"m" * 500)
    (paths.cores / "snes9x_libretro.so").write_text("x")
    (paths.states / "Mario.state1").write_text("the admin's")  # slot 1
    (paths.saves / "Mario.srm").write_text("the admin's card")
    return paths


def games_tab(qtbot, emu, user):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(games=[SteamGame(620, "Portal 2", installed=True)]), emulation_root=str(emu.root),
                   user=user)
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: len(tab.roms.get("snes", [])) == 1)
    return tab


def a_user(age=None):
    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    return cfg, users.add(cfg, "Mia", "pin", "1111", master, age=age)


def test_only_the_admin_can_delete_games(qtbot, emu):
    from gamingcrypt.ui.game_detail import GameDetailPage

    cfg, mia = a_user()
    for user, allowed in ((None, True), (users.admin(cfg), True), (mia, False)):
        tab = games_tab(qtbot, emu, user)
        assert tab.can_delete is allowed
        tab.open_rom(tab.roms["snes"][0])
        page = tab.currentWidget()
        page.options_button.click()
        assert page.remove_button.isVisibleTo(page.window()) is allowed
        page.ask_remove()
        assert (page.confirm is not None) is allowed
        tab.games[620] = tab.service.games[0]
        steam_page = GameDetailPage(tab, tab.service.games[0])
        qtbot.addWidget(steam_page)
        steam_page.show()
        steam_page.options_button.click()
        assert steam_page.uninstall_button.isVisibleTo(steam_page.window()) is allowed
        tab.close()


def test_storage_offers_no_deleting_to_a_user(qtbot, emu):
    from gamingcrypt.emulation.library import scan
    from gamingcrypt.emulation.systems import BY_ID
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, games_running=lambda: set(), emulation_fn=lambda: emu, can_delete=lambda: False)
    qtbot.addWidget(page)
    page.show()
    page.refresh()
    qtbot.waitUntil(lambda: len(page.rom_rows) == 1)
    qtbot.wait(300)  # (the list is filled when the page shows and when it's refreshed)
    mario = scan(emu, BY_ID["snes"])[0]
    text, remove, move = page.rom_rows[mario.appid]
    assert not text.isHidden() and remove.isHidden() and move.isHidden()
    page.ask_remove(mario, 0)
    assert page.confirm is None and mario.path.exists()


def test_each_user_has_saves_and_save_states_of_their_own(qtbot, emu):
    from gamingcrypt.emulation import retroarch, savestates
    from gamingcrypt.emulation.library import EmulationPaths

    cfg, mia = a_user()
    assert EmulationPaths(emu.root).states == emu.root / "states"  # the admin's: where they always were
    admin_tab, mia_tab = games_tab(qtbot, emu, users.admin(cfg)), games_tab(qtbot, emu, mia)
    assert admin_tab.emulation.states == emu.root / "states" and admin_tab.emulation.saves == emu.root / "saves"
    own = mia_tab.emulation
    assert own.states == emu.root / "users" / mia.id / "states" and own.saves == emu.root / "users" / mia.id / "saves"
    assert own.roms == emu.roms and own.cores == emu.cores and own.config == emu.config  # the games are everybody's
    game = mia_tab.roms["snes"][0]
    assert not savestates.slots(admin_tab.emulation, game)[0].empty
    assert all(s.empty for s in savestates.slots(own, game))  # none of the admin's
    text = retroarch.write_config(own).read_text()
    assert f'savestate_directory = "{own.states}"' in text and f'savefile_directory = "{own.saves}"' in text
    assert own.states.is_dir() and own.saves.is_dir()  # RetroArch finds them there
    (own.states / "Mario.state1").write_text("Mia's")
    assert savestates.slots(own, game)[0].path.read_text() == "Mia's"
    assert savestates.slots(admin_tab.emulation, game)[0].path.read_text() == "the admin's"


def test_settings_storage_follows_who_is_logged_in(qtbot, emu):
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg, mia = a_user()
    cfg["unlock"]["mount_point"] = str(emu.root.parent)
    users.enter(cfg, mia.id)
    tab = SettingsTab(cfg, lambda c: None, system=SystemControls())
    qtbot.addWidget(tab)
    assert tab.emulation_paths().states == emu.root / "users" / mia.id / "states"
    assert not tab.storage_page.can_delete()
    users.enter(cfg, "admin")
    assert tab.emulation_paths().states == emu.root / "states" and tab.storage_page.can_delete()


def test_steam_is_switched_to_the_account_of_who_logs_in(qtbot, tmp_path):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QWidget

    from gamingcrypt.app import MainWindow

    cfg, mia = a_user()
    cfg["steam"]["account"] = "111"  # the admin's
    users.enter(cfg, mia.id)
    cfg["steam"]["account"] = "222"  # Mia chose hers in Settings -> Games
    users.leave(cfg)
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    accounts = [SimpleNamespace(steam_id="111", persona="Papa", most_recent=True),
                SimpleNamespace(steam_id="222", persona="Mia", most_recent=False)]
    switched = []

    class Service:
        def accounts(self):
            return accounts

        def switch_account(self, account):
            switched.append(account.steam_id)
            for a in accounts:
                a.most_recent = a is account
            return True, "ok"

    def pages(config):
        games = QWidget()
        games.service = Service()
        return {"Games": games}

    window = MainWindow(cfg, lambda c: None, volume.factory, page_factory=pages)
    qtbot.addWidget(window)
    lock = window.stack.currentWidget()
    lock.user_buttons[mia.id].click()
    lock.input.secret_entered.emit("1111")
    qtbot.waitUntil(lambda: switched == ["222"], timeout=10000)
    window.panic_lock()
    lock = window.stack.currentWidget()
    lock.user_buttons["admin"].click()
    lock.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: switched == ["222", "111"], timeout=10000)
    window.panic_lock()  # the admin again: Steam is theirs already
    lock = window.stack.currentWidget()
    lock.user_buttons["admin"].click()
    lock.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    qtbot.wait(200)
    assert switched == ["222", "111"]


# --- favorites, play time and game settings are each user's own -----------------------------------

def test_game_profiles_are_per_user(qtbot, emu):
    from gamingcrypt import game_profiles
    from gamingcrypt.config import config_dir

    cfg, mia = a_user()
    assert game_profiles.path_for(None) == game_profiles.path_for(users.admin(cfg)) == config_dir() / "game-profiles.json"
    assert game_profiles.path_for(mia) == config_dir() / f"game-profiles-{mia.id}.json"
    admin_tab, mia_tab = games_tab(qtbot, emu, users.admin(cfg)), games_tab(qtbot, emu, mia)
    game = admin_tab.roms["snes"][0]
    admin_tab.profiles.set(game.appid, "favorite", True)
    admin_tab.profiles.set(game.appid, "fps", 30)
    assert admin_tab.profiles.is_favorite(game.appid) and not mia_tab.profiles.is_favorite(game.appid)
    assert mia_tab.profiles.get(game.appid) == {} and mia_tab.favorites() == []
    mia_tab.profiles.set(620, "favorite", True)
    assert mia_tab.favorites() == [620] and admin_tab.favorites() == [game.appid]
    assert game_profiles.for_user(mia).favorites() == [620]  # kept in her file
    # ... but the admin's age ratings count for everybody
    admin_tab.rating_profiles.set(game.appid, "rating", "6")
    from gamingcrypt import ratings

    assert ratings.age_of(game, mia_tab) == 6 and "rating" not in mia_tab.profiles.get(game.appid)


def test_play_time_of_emulated_games_is_per_user(qtbot, emu):
    cfg, mia = a_user()
    admin_tab, mia_tab = games_tab(qtbot, emu, users.admin(cfg)), games_tab(qtbot, emu, mia)
    assert admin_tab.play_log.path == emu.config / "playtime.json"  # the admin's: where it always was
    assert mia_tab.play_log.path == emu.root / "users" / mia.id / "playtime.json"
    game = admin_tab.roms["snes"][0]
    admin_tab.play_log.start(game)
    admin_tab.play_log.finish(game.appid)
    assert admin_tab.play_log.get(game.appid)[0] is not None and mia_tab.play_log.get(game.appid) == (None, 0)
    mia_tab.play_log.start(game)
    assert mia_tab.play_log.path.exists() and mia_tab.play_log.get(game.appid)[0] is not None


def test_the_app_uses_the_profiles_of_who_is_logged_in(qtbot, tmp_path):
    from gamingcrypt import game_profiles
    from gamingcrypt.app import MainWindow

    cfg, mia = a_user()
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    window = MainWindow(cfg, lambda c: None, volume.factory, page_factory=lambda c: {})
    qtbot.addWidget(window)
    assert window.game_profiles.path == game_profiles.path_for(None)
    lock = window.stack.currentWidget()
    lock.user_buttons[mia.id].click()
    lock.input.secret_entered.emit("1111")
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    assert window.game_profiles.path == game_profiles.path_for(mia)
    window.panic_lock()
    lock = window.stack.currentWidget()
    lock.user_buttons["admin"].click()
    lock.input.secret_entered.emit(ADMIN_CODE)
    qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
    assert window.game_profiles.path == game_profiles.path_for(None)


# --- what the admin locks for a user ---------------------------------------------------------------

def test_locking_tabs_for_a_user():
    cfg, mia = a_user()
    assert users.LOCKABLE == ("Movies", "Shows", "Music", "Pictures") and mia.locked == ()
    users.set_locked(cfg, mia.id, "Shows", True)
    users.set_locked(cfg, mia.id, "Movies", True)
    users.set_locked(cfg, mia.id, "Movies", True)
    assert users.get(cfg, mia.id).locked == ("Movies", "Shows") and users.admin(cfg).locked == ()
    users.set_locked(cfg, mia.id, "Movies", False)
    assert users.get(cfg, mia.id).locked == ("Shows",)
    for user_id, tab in (("admin", "Movies"), (mia.id, "Games"), (mia.id, "Settings")):
        with pytest.raises(users.UserError):
            users.set_locked(cfg, user_id, tab, True)
    assert users.persistable(cfg)["users"][0]["locked"] == ["Shows"]


def test_the_admin_locks_in_settings(qtbot, tab):
    add(qtbot, tab, "Mia", "pin", "1111")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    section, cfg = tab.users_section, tab.config
    mia = users.all_users(cfg)[1]
    locks = section.rows[mia.id]["locks"]
    assert list(locks) == ["Movies", "Shows", "Music", "Pictures"] and not any(b.isChecked() for b in locks.values())
    assert "locks" not in section.rows["admin"]
    locks["Movies"].click()
    assert users.get(cfg, mia.id).locked == ("Movies",) and tab._saved[-1]["users"][0]["locked"] == ["Movies"]
    locks = section.rows[mia.id]["locks"]  # (the list was drawn anew)
    assert locks["Movies"].isChecked() and locks["Movies"].text() == "🔒 Movies" and locks["Shows"].text() == "Shows"
    locks["Pictures"].click()
    section.rows[mia.id]["locks"]["Movies"].click()  # open again
    assert users.get(cfg, mia.id).locked == ("Pictures",)


def test_locked_tabs_are_not_there(qtbot):
    from gamingcrypt.ui.shell import TABS, Shell

    shell = Shell({}, locked=("Movies", "Shows", "Music", "Pictures", "Settings"))  # (Settings can't be locked)
    qtbot.addWidget(shell)
    shell.show()
    shown = [name for name in TABS if shell.tab_buttons[name].isVisibleTo(shell)]
    assert shown == ["Games", "Downloads", "Settings"]
    shell.show_tab("Movies")
    assert shell.current_tab == "Games"  # no way in
    walked = []
    for _ in range(4):
        shell.cycle_tab(1)  # the shoulder buttons skip them
        walked.append(shell.current_tab)
    assert walked == ["Downloads", "Settings", "Games", "Downloads"]
    shell.cycle_tab(-1)
    shell.cycle_tab(-1)
    assert shell.current_tab == "Settings"
    everything = Shell({})
    qtbot.addWidget(everything)
    everything.show()
    assert all(everything.tab_buttons[name].isVisibleTo(everything) for name in TABS)


def test_locked_movies_and_shows_are_not_even_looked_through(monkeypatch):
    from gamingcrypt import app
    from gamingcrypt.ui import games_tab, movies_tab, shows_tab

    made = []
    from types import SimpleNamespace

    monkeypatch.setattr(games_tab, "GamesTab", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(movies_tab, "MoviesTab", lambda *a, **k: made.append("Movies") or "movies")
    monkeypatch.setattr(shows_tab, "ShowsTab", lambda *a, **k: made.append("Shows") or "shows")
    monkeypatch.setattr("gamingcrypt.ui.downloads_tab.DownloadsTab", lambda service: "downloads")
    cfg, mia = a_user()
    assert set(app.default_pages(cfg)) == {"Games", "Downloads", "Movies", "Shows"}  # the admin: everything
    users.set_locked(cfg, mia.id, "Movies", True)
    users.enter(cfg, mia.id)
    made.clear()
    assert set(app.default_pages(cfg)) == {"Games", "Downloads", "Shows"} and made == ["Shows"]


# --- recently played is each user's own ------------------------------------------------------------

def test_steam_games_show_what_the_user_played_not_the_steam_account(qtbot, emu):
    from gamingcrypt import game_profiles
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab, last_played
    from gamingcrypt.ui.recent_page import recently_played
    from tests.fakes import FakeService

    cfg, mia = a_user()
    steam = [SteamGame(620, "Portal 2", installed=True, last_played=1700000000, playtime_minutes=600),
             SteamGame(400, "Portal", installed=True, last_played=1600000000, playtime_minutes=30)]
    game_profiles.for_user(mia).set(400, "last_played", 1710000000)
    game_profiles.for_user(mia).set(400, "minutes", 12)
    tab = GamesTab(FakeService(games=copy.deepcopy(steam)), user=mia)
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: len(tab.home.installed) == 2)
    mine = {g.appid: g for g in tab.service.load_library()}
    assert (mine[400].last_played, mine[400].playtime_minutes) == (1710000000, 12)
    assert (mine[620].last_played, mine[620].playtime_minutes) == (None, 0)  # never played by her
    assert [g.name for g in recently_played(list(mine.values()))] == ["Portal"]
    assert last_played(tab.home.installed).name == "Portal" and tab.home.continue_card.game.name == "Portal"
    admin_tab = GamesTab(FakeService(games=copy.deepcopy(steam)), user=users.admin(cfg))
    qtbot.addWidget(admin_tab)
    admin_tab.show()
    qtbot.waitUntil(lambda: len(admin_tab.home.installed) == 2)
    assert admin_tab.home.continue_card.game.name == "Portal 2"  # the admin: as Steam says, as ever


def test_the_app_keeps_a_users_steam_play_time(qtbot, tmp_path, monkeypatch):
    import time as time_module

    from gamingcrypt.app import MainWindow

    cfg, mia = a_user()
    window = MainWindow(cfg, lambda c: None, page_factory=lambda c: {})
    qtbot.addWidget(window)
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(time_module, "time", lambda: clock["now"])
    window.logged_in(users.admin(cfg), ADMIN_CODE)
    window.game_started(620)
    clock["now"] += 600
    window.game_ended(620)
    assert window.game_profiles.get(620) == {}  # the admin's: Steam's own numbers, nothing kept
    window.logged_in(mia, "1111")
    assert not window.own_steam_history(0x70000001) and window.own_steam_history(620)
    window.game_started(620)
    assert window.game_profiles.get(620)["last_played"] == 1_800_000_600
    clock["now"] += 25 * 60
    window.game_ended(620)
    assert window.game_profiles.get(620) == {"last_played": 1_800_002_100, "minutes": 25}
    window.game_started(620)
    clock["now"] += 5 * 60
    window.game_ended(620)
    assert window.game_profiles.get(620)["minutes"] == 30


def test_config_is_readable_by_its_owner_only(tmp_path):
    import os
    import stat

    from gamingcrypt.config import load_config, save_config

    path = tmp_path / "gamingcrypt" / "config.json"
    path.parent.mkdir()
    path.write_text("{}")
    os.chmod(path, 0o644)  # as older versions wrote it
    cfg, mia = a_user()
    save_config(users.persistable(cfg), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and not path.with_name("config.json.tmp").exists()
    assert users.get(load_config(path), mia.id).name == "Mia"
    volume = tmp_path / "games.vc"
    volume.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume)
    assert users.write_sidecar(cfg)
    assert stat.S_IMODE(Path(str(volume) + ".gamingcrypt.json").stat().st_mode) == 0o600


def test_ways_around_the_restrictions_are_the_admins(qtbot, tmp_path):
    """Desktop mode, SSH and the network share reach the whole drive and the settings."""
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg, mia = a_user()
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    window = MainWindow(cfg, lambda c: None, volume.factory, page_factory=lambda c: {})
    qtbot.addWidget(window)
    for who, code, allowed in ((mia.id, "1111", False), ("admin", ADMIN_CODE, True)):
        lock = window.stack.currentWidget()
        lock.user_buttons[who].click()
        lock.input.secret_entered.emit(code)
        qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
        assert window.shell.power_menu.desktop_button.isHidden() is not allowed
        assert window.shell.pages["Settings"].services_page.isHidden() is not allowed
        window.panic_lock()
    old = config()  # no users: nothing changes
    tab = SettingsTab(old, lambda c: None, system=SystemControls())
    qtbot.addWidget(tab)
    assert not tab.services_page.isHidden()


# --- settings that are a user's own, and those that aren't theirs at all ---------------------------

def test_a_user_has_no_games_security_or_system_settings(qtbot):
    from gamingcrypt.ui.settings_tab import SUB_TABS, SettingsTab

    cfg, mia = a_user()
    admin_tab = SettingsTab(cfg, lambda c: None, system=SystemControls())
    qtbot.addWidget(admin_tab)
    admin_tab.show()
    assert all(not admin_tab.sub_buttons[name].isHidden() for name in SUB_TABS)
    admin_tab.show_sub_tab("Security")
    assert admin_tab.current_sub_tab == "Security"
    users.enter(cfg, mia.id)
    tab = SettingsTab(cfg, lambda c: None, system=SystemControls())
    qtbot.addWidget(tab)
    tab.show()
    shown = [name for name in SUB_TABS if not tab.sub_buttons[name].isHidden()]
    assert shown == ["Device", "Network", "Controller", "Storage"] and tab.current_sub_tab == "Device"
    for name in ("Games", "Security", "System"):
        tab.show_sub_tab(name)
        assert tab.current_sub_tab == "Device"  # no way in


def test_sounds_rumble_and_animations_are_each_users_own():
    cfg, mia = a_user()
    users.enter(cfg, mia.id)
    cfg["appearance"].update(sounds=False, rumble=False, motion=False)
    users.leave(cfg)
    assert all(cfg["appearance"][key] is True for key in ("sounds", "rumble", "motion"))  # the admin's stay on
    users.enter(cfg, mia.id)
    assert not any(cfg["appearance"][key] for key in ("sounds", "rumble", "motion"))  # hers are still off


def test_look_overlay_and_display_settings_are_each_users_own():
    cfg, mia = a_user()
    cfg["appearance"].update(theme="dark", text_size="normal")
    cfg["overlay_bar"] = {"position": "top", "size": "small", "opacity": 30, "modules": ["fps"]}
    cfg["system"].update(gaming_refresh=60, volume_step=5, lock_after_sleep_min=10)
    users.enter(cfg, mia.id)
    admins_look = dict(DEFAULTS["appearance"], theme="dark", text_size="normal")
    assert cfg["appearance"] == admins_look  # she starts with what the admin has
    assert cfg["overlay_bar"]["position"] == "top" and cfg["system"]["gaming_refresh"] == 60
    cfg["appearance"]["theme"] = "light"
    cfg["appearance"]["text_size"] = "larger"
    cfg["overlay_bar"] = {"position": "bottom", "size": "large", "opacity": 80, "modules": ["fps", "battery"]}
    cfg["system"].update(gaming_refresh=40, gaming_resolution="960x600", volume_step=10)
    cfg["system"]["lock_after_sleep_min"] = 0  # the device's: for everybody
    written = users.persistable(cfg)
    assert written["appearance"] == admins_look  # the admin's, untouched
    assert written["overlay_bar"]["position"] == "top" and written["system"]["gaming_refresh"] == 60
    assert written["system"]["volume_step"] == 5 and written["system"]["lock_after_sleep_min"] == 0
    own = written["users"][0]
    assert own["appearance"] == dict(admins_look, theme="light", text_size="larger") and own["overlay_bar"]["size"] == "large"
    assert own["system"]["gaming_refresh"] == 40 and own["system"]["gaming_resolution"] == "960x600"
    assert "lock_after_sleep_min" not in own["system"] and "session" not in written and users.KEPT not in written
    users.leave(cfg)
    assert cfg["appearance"]["theme"] == "dark" and cfg["overlay_bar"]["position"] == "top"
    assert cfg["system"]["gaming_refresh"] == 60 and cfg["system"]["lock_after_sleep_min"] == 0
    cfg["appearance"]["theme"] = "light"  # the admin changes theirs: hers stays hers
    cfg["system"]["volume_step"] = 2
    users.enter(cfg, mia.id)
    assert cfg["appearance"] == dict(admins_look, theme="light", text_size="larger") and cfg["system"]["volume_step"] == 10
    assert cfg["overlay_bar"]["modules"] == ["fps", "battery"]
    users.enter(cfg, "admin")
    assert cfg["system"]["volume_step"] == 2 and users.persistable(cfg)["appearance"]["text_size"] == "normal"


def test_an_admin_without_overlay_settings_keeps_none(qtbot):
    cfg, mia = a_user()
    assert "overlay_bar" not in cfg
    users.enter(cfg, mia.id)
    assert users.persistable(cfg).get("overlay_bar") is None  # nothing invented for the admin
    cfg["overlay_bar"] = {"position": "top"}
    assert "overlay_bar" not in {k for k in users.persistable(cfg) if k != "users"}
    assert users.persistable(cfg)["users"][0]["overlay_bar"] == {"position": "top"}
    users.leave(cfg)
    assert "overlay_bar" not in cfg


def test_the_look_follows_who_logs_in(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui import theme

    cfg, mia = a_user()
    users.enter(cfg, mia.id)
    cfg["appearance"].update(theme="light", text_size="large")
    users.leave(cfg)
    volume_file = tmp_path / "x.vc"
    volume_file.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume_file)
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    before = (theme.current, theme.text_size)
    try:
        theme.apply("dark", QApplication.instance(), "normal")
        window = MainWindow(cfg, lambda c: None, volume.factory, page_factory=lambda c: {})
        qtbot.addWidget(window)
        lock = window.stack.currentWidget()
        lock.user_buttons[mia.id].click()
        lock.input.secret_entered.emit("1111")
        qtbot.waitUntil(lambda: window.screen_name == "shell", timeout=10000)
        assert (theme.current, theme.text_size) == ("light", "large")
        window.panic_lock()
        assert (theme.current, theme.text_size) == ("dark", "normal")  # the lock screen: as the admin has it
    finally:
        theme.apply(before[0], QApplication.instance(), before[1])


def test_own_resolution_restarts_gaming_mode_once(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.session import mode

    cfg, mia = a_user()
    monkeypatch.setattr(mode, "panel_size", lambda *a: (1280, 800))
    saved = []
    window = MainWindow(cfg, lambda c: saved.append(copy.deepcopy(c)), page_factory=lambda c: {})
    qtbot.addWidget(window)
    users.enter(cfg, mia.id)
    assert not window.own_resolution_differs()  # nothing chosen: as it is
    assert saved[-1]["system"]["gaming_resolution"] == "1280x800"  # what the admin has is noted for them
    cfg["system"]["gaming_resolution"] = "960x600"
    assert window.own_resolution_differs()
    assert mode.parse_display(mode.read_args()) == {"width": 960, "height": 600} and not mode.display_pending()
    assert not window.own_resolution_differs()  # after the restart: it's hers already
    cfg["system"]["gaming_resolution"] = "123x45"  # not one of the sizes: left alone
    assert not window.own_resolution_differs()
    users.enter(cfg, "admin")
    assert cfg["system"]["gaming_resolution"] == "1280x800" and window.own_resolution_differs()  # back to native
    assert mode.parse_display(mode.read_args()) == {}


def test_one_user_nothing_is_applied(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui import theme

    cfg = config()
    cfg["appearance"]["theme"] = "light"
    window = MainWindow(cfg, lambda c: None, page_factory=lambda c: {})
    qtbot.addWidget(window)
    called = []
    monkeypatch.setattr(theme, "apply", lambda *a, **k: called.append(a))
    monkeypatch.setattr(window, "own_resolution_differs", lambda: called.append("resolution"))
    window.apply_own_settings(login=True)
    assert called == []


def test_the_admin_chooses_a_users_steam_account(qtbot, tab):
    from types import SimpleNamespace

    add(qtbot, tab, "Mia", "pin", "1111")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview, timeout=10000)
    section, cfg = tab.users_section, tab.config
    mia = users.all_users(cfg)[1]
    assert "steam" not in section.rows[mia.id]  # no Steam account on the device: nothing to choose
    section._steam_accounts = [SimpleNamespace(steam_id="111", persona="Papa"), SimpleNamespace(steam_id="222", persona="Mia")]
    section.refresh()
    combo = section.rows[mia.id]["steam"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["Steam: as it is", "Steam: Papa", "Steam: Mia"]
    assert "steam" not in section.rows["admin"]  # the admin's own: Settings -> Games
    combo.setCurrentIndex(2)
    assert tab._saved[-1]["users"][0]["steam"]["account"] == "222"
    assert section.rows[mia.id]["steam"].currentData() == "222"
    users.enter(cfg, mia.id)
    assert cfg["steam"]["account"] == "222"
    users.leave(cfg)
