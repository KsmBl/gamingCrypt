# 🔒 GamingCrypt

A fullscreen **touch UI for Linux gaming handhelds** whose games live on a
**VeraCrypt-encrypted drive**. On start you unlock the drive with a **PIN,
password or swipe pattern**, and then you land in a console-style launcher with
your Steam library.

| Lock screen | 5×5 Pattern | Swipe pattern setup |
|---|---|---|
| ![lock](docs/screenshots/lock.png) | ![grid5](docs/screenshots/grid5.png) | ![pattern](docs/screenshots/pattern.png) |

| New container | Games | |
|---|---|---|
| ![create](docs/screenshots/create.png) | ![games](docs/screenshots/games.png) | |

| Steam library | Game page | Settings |
|---|---|---|
| ![steam](docs/screenshots/steam.png) | ![detail](docs/screenshots/detail.png) | ![settings](docs/screenshots/settings.png) |

## Features

- **Unlock screen**: PIN pad, password with on-screen keyboard, a 3×3 swipe pattern, or a 5×5 tap pattern
  - Mounts your VeraCrypt volume (device or file container); the password goes to VeraCrypt over stdin
- **First-start setup**: pick an existing volume, or **create a new encrypted container**, then choose your unlock method
- **Key derivation**: every secret is hardened with scrypt and a per-volume salt before it reaches VeraCrypt
- **Settings → Reset authentication method**: switch between PIN, password, swipe pattern and 5×5 pattern at any time
- **Tabs**: Games, Movies, Series, Music, Pictures, Settings (the media tabs show *coming soon*)
- **Downloads tab**: every queued, running and paused Steam download with progress, and a count in the tab bar
- **Device settings**: resolution, refresh rate, brightness, max power consumption (TDP), audio output and input device and their volume
- **Controller**: calibrate the analog sticks and triggers and map every button; games get a virtual Xbox controller with your setup
- **Games**
  - Search your installed games
  - **Steam** card with your whole library (installed, plus every owned game when a Web API key is set)
  - Sort by **name, release date, playtime, price or latest update**, ascending or descending
  - Game page: **Play** or **Download**, plus **Options → Uninstall** (tap twice to confirm, no Steam popup)
  - **Downloads without opening Steam**: owned games are queued straight onto the encrypted drive while Steam runs minimised, with progress shown in GamingCrypt
  - **Store**: search the Steam store, install free or owned games, or open a paid game's purchase page in Steam
- Built for touch: big targets, kinetic flick scrolling, an on-screen keyboard and double-tap confirmation for destructive actions

## Install

Requirements: Linux, Python ≥ 3.10, [VeraCrypt](https://veracrypt.fr), Steam (native or Flatpak).

```sh
git clone https://github.com/KsmBl/gamingCrypt.git
cd gamingCrypt
./install.sh              # add --autostart to launch it after login
```

The installer:

1. creates a virtualenv in `~/.local/share/gamingcrypt` and installs the app (PySide6, requests)
2. adds the `gamingcrypt` launcher to `~/.local/bin` and a desktop entry
3. installs a **restricted root helper** and a sudoers rule so the volume can be mounted without a password prompt (asks for sudo once)
4. allows the logged-in user to create the virtual controller (`/dev/uinput` udev rule)

Uninstall with `./install.sh --uninstall` (your config and cache are kept).

Run `gamingcrypt --windowed` to try it in a window instead of fullscreen.

## Unlock methods and key derivation

What you enter is first turned into a canonical secret:

| Method | Secret |
|---|---|
| PIN | the digits, e.g. `482916` (at least 4) |
| Password | the text as typed |
| Swipe pattern | the touched dots numbered 1–9 row by row, e.g. an "L" `1→4→7→8→9` = `14789` |
| 5×5 Pattern | the tapped dots numbered 1–25 row by row **in tap order**, joined with `-`, repeats allowed, e.g. `1-7-13-25` (at least 4 taps) |

**Every secret then goes through a key derivation function** before it reaches VeraCrypt:

```
VeraCrypt password = base64url( scrypt(secret, salt, N=2^18, r=8, p=1) )   # 43 chars
```

scrypt is memory-hard (about 256 MB and about 0.5 s per attempt), and the salt is
random per volume and new on every password change. An attacker can't take a
4-digit PIN and try it against the volume directly. Every guess costs a full scrypt
run plus VeraCrypt's own PBKDF2, and precomputed tables don't help.

> ⚠️ **Back up the salt.** It is in `~/.config/gamingcrypt/config.json` (`unlock.kdf`) and,
> for container files, in `<container>.gamingcrypt.json` next to the container. The salt
> isn't secret, but without it the volume can't be opened.
> To open the volume with plain VeraCrypt (on another PC, for example), run
> `gamingcrypt --volume-password`, enter your PIN or pattern in the format above,
> and use the printed password.
>
> A KDF makes every guess expensive, but it can't enlarge the key space. A 4-digit
> PIN still has only 10 000 possibilities. For real protection choose a long
> password, a long 5×5 pattern, or a longer PIN.

The first-start wizard and *Settings → Reset authentication method* ask for the
current secret, then for the new method and value, and re-key the volume. Volumes
set up before the KDF existed keep working: do a reset once to switch them to the KDF.

## Steam library

Installed games are read straight from Steam's library folders, including
libraries on the encrypted drive. Native, Flatpak and Snap Steam are detected
automatically.

To also list games you **own but haven't installed**, open **Settings → Steam → Set Steam API
key** and enter a [Steam Web API key](https://steamcommunity.com/dev/apikey) (any domain name
works). Your SteamID is detected from the account logged in to Steam. Without a key, only
installed games are shown, and the Steam page says so.

### Uninstalling without Steam's popup

*Options → Uninstall* (tap twice) uninstalls directly:
1. Steam is closed briefly if it's running.
2. GamingCrypt deletes the game folder, its manifest, workshop items, shader cache and
   unfinished downloads.
3. Steam is started minimised again.

- **Saves are kept:** the Proton prefix (`compatdata/<id>`), where many Windows games keep
  their save games, is not deleted.
- **Safe by design:** only the game's own folder under `steamapps/common` is ever deleted.
- **Turning it off:** `"steam": {"silent_uninstall": false}` uses Steam's dialog again.

### Steam windows

Some things still need a Steam window: buying, the first install of a free game, and
Steam's login. GamingCrypt minimises itself when it opens one, so the Steam window isn't
hidden behind it. Start GamingCrypt again (launcher icon or `gamingcrypt`) to bring it
back. A second start never opens a second copy.

### Several Steam accounts

If more than one Steam account has logged in on the device, *Settings → Steam* lists them all
with a **Switch** button:
1. GamingCrypt closes Steam.
2. It sets that account as Steam's auto-login account (`registry.vdf` and `loginusers.vdf`).
3. It starts Steam minimised again.

Notes:
- Switching skips the password prompt only if *Remember password* was ticked when that
  account logged in. Otherwise Steam asks once.
- The Steam page shows which account you're looking at. Owned games, the offline cache and
  playtime always belong to the active account.
- The API key works for any account whose game list is public. A private account only works
  with its own key.

If the library looks wrong, run `gamingcrypt --diagnose`. It prints:
- which Steam folder was found and every library folder in it, with its number of games
- whether the encrypted drive is mounted
- the detected account and whether an API key is set

### Encrypted drive as Steam library

After every unlock GamingCrypt checks that the mounted container is a Steam library folder.
If it isn't, it creates `steamapps` inside the container and adds the folder to Steam's
`libraryfolders.vdf` (both `config/` and `steamapps/`), labelled *GamingCrypt*:
- Steam rewrites these files when it exits, so a running Steam is closed first.
- Nothing is done unless the container is really mounted, so no game folder ever ends up
  on the unencrypted disk.
- Turn it off with `"steam": {"auto_library": false}`.

### Installing without opening Steam

**Download** (game page) and **Install** (store, for games you own) don't open Steam's install dialog:
1. GamingCrypt writes an install manifest (`appmanifest_<id>.acf`, *update required*) into the
   encrypted library, or into Steam's own folder if the drive isn't mounted.
2. It restarts Steam minimised (`steam -silent`); Steam picks up the manifest and downloads in the background.
3. The game page shows the progress and switches to **Play** when it's done.

Notes:
- Steam is restarted for this, so don't start a download while a game is running.
- Steam itself must be logged in.
- Free games that aren't in your account yet still go through Steam's dialog once,
  because that's what adds them to your account.
- Turn it off with `"steam": {"silent_install": false}` to always use Steam's dialog.

Prices, release dates and latest-update dates come from the public store API.
They load in the background, stay within Steam's rate limits, and are cached in
`~/.cache/gamingcrypt`. Play, download, uninstall and store actions go through
the Steam client (`steam://` URIs).

## Device settings

*Settings* controls the handheld itself. Each part picks the tool it finds and says
so when something isn't available:

| Setting | Uses |
|---|---|
| Resolution, refresh rate | `kscreen-doctor` (KDE), `wlr-randr` (Sway, Hyprland, other wlroots), `xrandr` (X11) |
| Brightness | `brightnessctl` (never below 5 %) |
| Max power (TDP) | AMD `power1_cap` (+ `ryzenadj` if installed) or Intel RAPL, set through the root helper |
| Audio output / input + volume | `pactl` (PipeWire or PulseAudio); switching also moves sound that's already playing |

- **New display mode:** has to be confirmed within 15 s, otherwise it reverts, like on a
  desktop. A mode that turns the screen black can't lock you out.
- **Power limit:** only values inside the range the hardware reports are accepted, and
  the root helper checks that again.
- **After a reboot:** the resolution and power limit you chose are re-applied when
  GamingCrypt starts.
- **Not supported:** gamescope (Steam's game mode) and GNOME can't be controlled this way yet.

## Controller: calibration and button mapping

*Settings → Controller* shows both sticks live: the raw position (grey) and what games
will get (blue).

**Calibrate sticks and triggers:**
1. Leave everything untouched. GamingCrypt measures the resting position and the noise,
   which sets the deadzone.
2. Rotate both sticks in full circles and press both triggers fully, which measures the
   range. You can still fine-tune the deadzone with a slider afterwards.

**Buttons:** tap *Remap* next to any button, D-pad direction or trigger, then press the
button (or push the stick or trigger) that should act as it. *Reset to defaults* undoes everything.

**Use my calibration and mapping** turns on the virtual controller:
- GamingCrypt takes the built-in controller exclusively and publishes a virtual Xbox 360
  controller (`uinput`) that Steam and every game understand.
- Profiles are stored per controller model.
- If Steam reads the built-in controller directly and inputs arrive twice, turn off Steam
  Input for it.
- `install.sh` allows the logged-in user to use `/dev/uinput`.

The controller code needs no compiled libraries (pure Python on the kernel's evdev and
uinput interfaces), so it also runs on read-only systems like SteamOS.

## Configuration

`~/.config/gamingcrypt/config.json` (created by the setup wizard):

| Key | Meaning |
|---|---|
| `fullscreen` | start in fullscreen (default `true`) |
| `unlock.method` | `pin`, `password`, `pattern` (3×3 swipe) or `grid5` (5×5 tap) |
| `unlock.volume` | VeraCrypt volume, e.g. `/dev/nvme0n1p3` or `~/games.vc` |
| `unlock.mount_point` | optional, e.g. `/mnt/games` (empty = VeraCrypt picks one) |
| `unlock.use_sudo` | mount through `sudo -n` + helper (default `true`) |
| `unlock.pim`, `unlock.keyfiles` | VeraCrypt PIM / keyfiles if your volume uses them |
| `unlock.kdf` | scrypt parameters and salt (written by the setup, **back it up**) |
| `steam.root` | Steam directory (empty = auto-detect, Flatpak included) |
| `steam.api_key` | Web API key for the full library (set it in Settings → Steam) |
| `steam.steam_id` | optional, overrides the detected SteamID64 |
| `steam.command` | command used for `steam://` URIs (empty = auto-detect) |
| `steam.auto_library` | add the unlocked container as Steam library (default `true`) |
| `system.display`, `system.power_limit_w` | display mode and power limit restored at start (set from Settings) |
| `input.enabled`, `input.profiles` | virtual controller on/off, mapping and calibration per controller (set from Settings) |
| `steam.silent_install` | download owned games without Steam's dialog (default `true`) |
| `steam.silent_uninstall` | uninstall without Steam's confirmation popup (default `true`) |

## Security notes

- The password is sent to VeraCrypt over **stdin**, so it never shows up in the process list. VeraCrypt has no stdin option for the *new* password when you change it, so during a password change (a few seconds) the new secret is briefly visible in the process list.
- sudo access is **not** granted to `veracrypt` itself, because that would amount to root access. It goes only to `/usr/local/lib/gamingcrypt/veracrypt-helper`, which:
  - accepts only mount, list, change-password and create, each with a fixed set of arguments
  - always mounts with `nosuid,nodev`
  - only allows mount points below `/mnt`, `/media`, `/run/media` or your home directory
  - sets the **power limit** only within the range the hardware reports
  - only **creates** new container *files* (never devices): the file must not exist yet, and the folder must belong to you and be below those same locations. Afterwards the container file and its fresh ext4 filesystem are handed over to your user so Steam can install into it
- After updating GamingCrypt, re-run `./install.sh` so the helper is updated too.

## Creating a new container

In the first-start setup choose **Create new encrypted container** and enter:
- the file location (default `~/GamingCrypt.vc`)
- the size in GB (free space is checked)
- the mount point (default `~/GamingCrypt`)
- quick format: on by default, fast. Turn it off for a full format, which is slow but also hides how much of the container is used.

Then pick your unlock method. The container is created as AES / SHA-512 / ext4 with
your KDF-derived password, and progress is shown live. While it is being created you can
only **cancel**. Cancelling (or closing the window) stops VeraCrypt, deletes the
unfinished file and takes you back to the form.

Next to the container GamingCrypt writes `<container>.gamingcrypt.json` with the unlock
method, mount point and KDF salt. None of these are secret. On start, an existing
container (the configured one, or `~/GamingCrypt.vc`) is recognised and you go straight
to the unlock screen. *Create new container* is never offered while a container exists.
If a container has no such file (one made with VeraCrypt directly, for example), setup
asks for its current password right away. After you unlock it,
GamingCrypt **adds it to Steam as a library folder automatically**.

To encrypt a whole partition or SD card, create the volume with VeraCrypt itself
and choose *Use existing VeraCrypt volume*.

## Development

```sh
python -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

The test suite covers the unlock backend (including a real VeraCrypt re-key
round trip when `veracrypt` is installed), the root helper, the Steam parsers
and API clients, sorting, and every UI page via pytest-qt.
`RUN_INSTALL_TEST=1` also runs a full user install of `install.sh` into a temporary HOME.

## Roadmap

- More game sources (Heroic/Epic/GOG, Lutris, emulators)
- Movies, Series, Music, Pictures
- Navigating the GamingCrypt UI with the gamepad
- More settings

## License

MIT
