# 🔒 GamingCrypt

**A console-style launcher for Linux gaming handhelds, with your games on an encrypted drive.**

Unlock with a PIN, password or pattern, and you land in a fullscreen launcher for your
Steam library, emulated games, Windows and Linux games, movies and shows. It works with
touch and controller, and can boot the device straight into a SteamOS-like gaming mode.

| Games | Game page | Quick menu |
|---|---|---|
| ![games](docs/screenshots/games.png) | ![detail](docs/screenshots/detail.png) | ![quickmenu](docs/screenshots/quickmenu.png) |

| Movies | Shows | Lock screen |
|---|---|---|
| ![movies](docs/screenshots/movies.png) | ![shows](docs/screenshots/shows.png) | ![lock](docs/screenshots/lock.png) |

<details>
<summary>More screenshots</summary>

| Steam library | Movie page | Show page |
|---|---|---|
| ![steam](docs/screenshots/steam.png) | ![movie](docs/screenshots/movie.png) | ![show](docs/screenshots/show.png) |

| Episodes | Settings | Light theme |
|---|---|---|
| ![episodes](docs/screenshots/episodes.png) | ![settings](docs/screenshots/settings.png) | ![light](docs/screenshots/games-light.png) |

| 5×5 pattern | Swipe pattern | First start |
|---|---|---|
| ![grid5](docs/screenshots/grid5.png) | ![pattern](docs/screenshots/pattern.png) | ![create](docs/screenshots/create.png) |

</details>

## Features

- 🔐 **Encrypted game drive**: a VeraCrypt container or partition, unlocked with a PIN, password,
  swipe pattern or 5×5 tap pattern. First start can create the container for you.
- 🎮 **Steam**: your whole library, downloads and uninstalls without Steam's dialogs, a download
  queue, Proton per game, store search, and several Steam accounts.
- 👾 **Emulation**: from NES to PS2, GameCube and Switch, through RetroArch and Eden. Cores and
  covers are downloaded for you; shaders, upscaling and save states are included.
- 🪟 **Windows and Linux games** outside Steam: copy the game folder onto the drive, pick its start
  file, and play it with Proton, Wine or natively.
- 🖼️ **Wrong or missing picture?** Hold it to pick another one from Steam's store or the box art of the system.
- 🎬 **Movies and shows** with covers, descriptions and cast looked up automatically; resume
  where you stopped and watched marks; episodes are grouped into seasons.
- 📶 **Upload over Wi-Fi**: add ROMs, games and videos from a browser (QR code) or a network share.
- 🖧 **Services**: switch on SSH, or share your whole drive in the network while it's unlocked.
- 🕹️ **Controller first**: console-style D-pad navigation, stick and trigger calibration, button
  remapping, and a quick menu (volume, brightness, refresh rate, FPS limit, force quit) during games.
- ⚙️ **Device settings**: resolution, refresh rate, brightness, power limit (TDP), audio devices.
- 🌗 Dark and light theme.

## Requirements

- Linux with Python 3.10 or newer
- [VeraCrypt](https://veracrypt.fr)
- Steam (native or Flatpak)
- For gaming mode: [gamescope](https://github.com/ValveSoftware/gamescope) and LightDM

## Install

```sh
git clone https://github.com/KsmBl/gamingCrypt.git
cd gamingCrypt
./install.sh
```

Then start **GamingCrypt** from your app menu or run `gamingcrypt`. The first start walks you
through choosing or creating an encrypted volume and setting your unlock method.

| Option | What it does |
|---|---|
| `./install.sh --session` | Boot straight into gaming mode (GamingCrypt on gamescope). **⏻ → Desktop mode** switches to your desktop. |
| `./install.sh --autostart` | Start GamingCrypt after you log in |
| `./install.sh --uninstall` | Remove GamingCrypt (your settings are kept) |

To update, run `git pull && ./install.sh`.

The installer asks for sudo once. It sets up a small helper that can only mount and manage
VeraCrypt volumes, so unlocking needs no password prompt, and it allows the virtual controller.

## Security

- Your PIN, password or pattern is strengthened with **scrypt** and a random salt before it
  reaches VeraCrypt, which makes every guess slow. A short PIN is still only a short PIN, so
  use a long password or pattern if the drive needs real protection.
- ⚠️ **Back up `~/.config/gamingcrypt/config.json`.** It holds the salt, and without it the
  volume can't be opened. Container files also keep a copy next to them
  (`<container>.gamingcrypt.json`).
- To open the drive with plain VeraCrypt on another PC, run `gamingcrypt --volume-password`
  to get the real VeraCrypt password.

## Troubleshooting

- `gamingcrypt --diagnose` shows which Steam folders, libraries and account were found.
- `gamingcrypt --windowed` runs it in a window instead of fullscreen.
- The log is in `~/.cache/gamingcrypt/gamingcrypt.log`.
- To see your games that aren't installed, add a [Steam Web API key](https://steamcommunity.com/dev/apikey)
  in **Settings → Steam**.

## Development

```sh
python -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

Screenshots are made with `.venv/bin/python docs/screenshots.py` (sample data, no device needed).

## License

[MIT](LICENSE)
