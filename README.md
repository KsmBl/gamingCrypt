# 🔒 GamingCrypt

A fullscreen **touch UI for Linux gaming handhelds** whose games live on a
**VeraCrypt-encrypted drive**. On start you unlock the drive with a **PIN,
password or swipe pattern**, and then you land in a console-style launcher with
your Steam library.

| Lock screen | Pattern setup | Games |
|---|---|---|
| ![lock](docs/screenshots/lock.png) | ![pattern](docs/screenshots/pattern.png) | ![games](docs/screenshots/games.png) |

| Steam library | Game page | Settings |
|---|---|---|
| ![steam](docs/screenshots/steam.png) | ![detail](docs/screenshots/detail.png) | ![settings](docs/screenshots/settings.png) |

## Features

- **Unlock screen**: PIN pad, password with on-screen keyboard, a 3×3 swipe pattern, or a 5×5 tap pattern
  - Mounts your VeraCrypt volume (device or file container); the password goes to VeraCrypt over stdin
- **First-start setup**: pick your volume and unlock method, enter the value twice, and GamingCrypt re-keys the volume
- **Settings → Reset authentication method**: switch between PIN, password, swipe pattern and 5×5 pattern at any time
- **Tabs**: Games, Movies, Series, Music, Pictures, Settings (the media tabs show *coming soon*)
- **Games**
  - Search your installed games
  - **Steam** card with your whole library (installed, plus every owned game when a Web API key is set)
  - Sort by **name, release date, playtime, price or latest update**, ascending or descending
  - Game page: **Play** or **Download**, plus **Options → Uninstall** (tap twice to confirm)
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

Uninstall with `./install.sh --uninstall` (your config and cache are kept).

Run `gamingcrypt --windowed` to try it in a window instead of fullscreen.

## Unlock methods and your VeraCrypt password

The secret you enter **is** the VeraCrypt password:

| Method   | VeraCrypt password                                                        |
|----------|---------------------------------------------------------------------------|
| PIN      | the digits, e.g. `482916` (at least 4)                                    |
| Password | the text as typed                                                         |
| Swipe pattern | the touched dots numbered 1–9 row by row, e.g. an "L" `1→4→7→8→9` = `14789` |
| 5×5 Pattern | the tapped dots numbered 1–25 row by row **in tap order**, joined with `-`, repeats allowed, e.g. `1-7-13-25` (at least 4 taps) |

The first-start wizard (and *Settings → Reset authentication method*) asks for the
current password, then for the new method and value, and changes the volume's
password for you. Your volume keeps working with plain VeraCrypt using that string.

> ⚠️ A 4-digit PIN or a short pattern is much weaker than a long passphrase. The
> volume is only as strong as the secret you choose.

## Steam library

Installed games are read straight from Steam's library folders, including
libraries on the encrypted drive. To also list games you **own but haven't
installed** (and to get playtime from Steam), add a
[Steam Web API key](https://steamcommunity.com/dev/apikey) and your SteamID64 to
`~/.config/gamingcrypt/config.json`:

```json
{
  "steam": {
    "api_key": "YOUR_KEY",
    "steam_id": "7656119xxxxxxxxxx",
    "country": "de"
  }
}
```

Prices, release dates and latest-update dates come from the public store API.
They load in the background, stay within Steam's rate limits, and are cached in
`~/.cache/gamingcrypt`. Play, download, uninstall and store actions go through
the Steam client (`steam://` URIs).

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
| `steam.root` | Steam directory (empty = auto-detect, Flatpak included) |
| `steam.api_key`, `steam.steam_id` | optional, for the full library |
| `steam.command` | command used for `steam://` URIs (empty = auto-detect) |

## Security notes

- The password is sent to VeraCrypt over **stdin**, so it never shows up in the process list. VeraCrypt has no stdin option for the *new* password when you change it, so during a password change (a few seconds) the new secret is briefly visible in the process list.
- sudo access is **not** granted to `veracrypt` itself, because that would amount to root access. It goes only to `/usr/local/lib/gamingcrypt/veracrypt-helper`, which:
  - accepts only mount, list and change-password with a fixed set of arguments
  - always mounts with `nosuid,nodev`
  - only allows mount points below `/mnt`, `/media`, `/run/media` or your home directory

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
- Gamepad navigation
- More settings

## License

MIT
