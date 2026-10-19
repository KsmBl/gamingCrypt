# 🔒 GamingCrypt

**A console-style launcher for Linux gaming handhelds, with your games on an encrypted drive.**

Unlock with a PIN, password or pattern, and you land in a fullscreen launcher for your
Steam library, emulated games, Windows and Linux games, Minecraft, movies and shows. It works with
touch and controller, and can boot the device straight into a SteamOS-like gaming mode.

| Games | Game page | Quick menu |
|---|---|---|
| ![games](docs/screenshots/games.png) | ![detail](docs/screenshots/detail.png) | ![quickmenu](docs/screenshots/quickmenu.png) |

| Movies | Shows | Lock screen |
|---|---|---|
| ![movies](docs/screenshots/movies.png) | ![shows](docs/screenshots/shows.png) | ![lock](docs/screenshots/lock.png) |

| Minecraft | Minecraft instance | On-screen keyboard |
|---|---|---|
| ![minecraft](docs/screenshots/minecraft.png) | ![minecraft-instance](docs/screenshots/minecraft-instance.png) | ![keyboard](docs/screenshots/keyboard.png) |

| Light theme | Game page | Quick menu |
|---|---|---|
| ![games-light](docs/screenshots/games-light.png) | ![detail-light](docs/screenshots/detail-light.png) | ![quickmenu-light](docs/screenshots/quickmenu-light.png) |

<details>
<summary>More screenshots</summary>

| Steam library | Movie page | Show page |
|---|---|---|
| ![steam](docs/screenshots/steam.png) | ![movie](docs/screenshots/movie.png) | ![show](docs/screenshots/show.png) |

| Episodes | Settings | First start |
|---|---|---|
| ![episodes](docs/screenshots/episodes.png) | ![settings](docs/screenshots/settings.png) | ![create](docs/screenshots/create.png) |

| 5×5 pattern | Swipe pattern | PIN, light |
|---|---|---|
| ![grid5](docs/screenshots/grid5.png) | ![pattern](docs/screenshots/pattern.png) | ![pin-light](docs/screenshots/pin-light.png) |

| Steam library, light | Settings, light | |
|---|---|---|
| ![steam-light](docs/screenshots/steam-light.png) | ![settings-light](docs/screenshots/settings-light.png) | |

</details>

## Features

- 🔐 **Encrypted game drive**: a VeraCrypt container or partition, unlocked with a PIN, password,
  swipe pattern or 5×5 tap pattern. First start can create the container for you.
- 👥 **Users**: an admin and as many users as you add, each with a code of their own that
  unlocks the same drive - chosen on the lock screen. Every user has their own Steam account
  and settings, favorites, play time, per-game settings, emulator saves and save states - and
  their own look (theme, text size), performance overlay, resolution and refresh rate. Only the
  admin can delete games, sees the Games, Security and System settings, and can lock Movies,
  Shows, Music and Pictures for a user.
- 🔞 **Age ratings**: give a user an age and they see only the games rated for it (USK from the
  Steam store, ESRB for emulated games); the admin can rate any game by hand.
- 🎮 **Steam**: your whole library, downloads and uninstalls without Steam's dialogs, a download
  queue, Proton per game, store search, and several Steam accounts.
- 🔎 **Filters**: all installed games by genre, platform and release year, sorted by name, date or last played.
- ▶️ **Continue playing**: after a start you're on the main page with the game played last
  highlighted - one press to play on.
- 👾 **Emulation**: from NES to PS2, Sega 32X, GameCube, Wii, Wii U, 3DS and Switch, through RetroArch and
  Eden. Cores, covers and Dolphin's system files are downloaded for you; shaders and upscaling are
  included. Wii U games as `.wua` (or `.wud` / `.wux` with your console's keys in
  `bios/Cemu/keys.txt`) - they can't be saved as states. They're played with a Wii U Pro
  Controller; a game that needs the GamePad's screen or touch gets the GamePad in its ⚙ Options.
- 🌐 **Console language** for every console that has one - GameCube, Wii, Wii U, DS, 3DS, PS2, PSP,
  Dreamcast and Switch (⚙ Options → 🌐 Language on the system's page): the games show their text in it -
  like the device's language until you choose one.
- 💾 **Save states**: nine slots per game in a 3 by 3 grid, each with a picture of the moment,
  the date and time it was saved and how long you had played up to it. States are only saved and
  loaded when you pick a slot - RetroArch never saves, loads or deletes one by itself.
- ⏸ **Paused** while the quick menu is open over an emulated game.
- ⏩ **Speed**: a slider in the quick menu, from 0.1x to 10x - the game goes on at it when you
  close the menu. RetroArch can't change it while a game runs, so the game starts again where you
  were (kept in a hidden state of its own, not one of the nine, gone again after two minutes); the
  menu says so before you close it. Should the game not come back, that state is put into a free
  slot and you're told which.
- 🇪🇺 **50 Hz games**: tick "60 FPS" in the quick menu and a PAL game runs in step with a 60 Hz
  screen (a fifth faster) instead of stuttering.
- ❓ **Not recognised?** A file with an unusual name (patched, translated, renamed) gets no cover,
  genre or year by itself: choose the game from a list on its page, and the filters find it.
- 🧱 **Minecraft** (Java Edition), playable with the controller: sign in with your Microsoft account
  by scanning a QR code with your phone (no typing on the handheld), make an instance (its own worlds
  and settings, the Minecraft version you choose) and press Play - Minecraft and its Java are
  downloaded the first time. With **Controller support** (on by default) it runs on Fabric with
  Controlify - menus, inventory, crafting and chat all with the controller - and Sodium for a smoother
  game; **🧩 Mods** in its Options adds any Fabric mod from Modrinth (searched with the controller) or
  removes one. Each user has their own account; everything stays on the encrypted drive. Installed
  and started by [portablemc](https://github.com/theorzr/portablemc), set up by itself.
- ⌨️ **On-screen keyboard on a button combination** (Guide + X on a controller, Windows + Volume Up on
  handhelds with a Windows key - set your own in Settings → Controller → Device buttons): in
  GamingCrypt it types into the text field; **in a game** it opens over the game and types into it
  (a virtual keyboard), steered with the controller - with Esc, Tab, Ctrl, Alt, arrows and F1 - F12 for PC
  games. While it's open the game doesn't get the controller.
- 🪟 **Windows and Linux games** outside Steam: copy the game folder onto the drive, pick its start
  file, and play it with Proton, Wine or natively.
- 🖼️ **Wrong or missing picture?** Hold it (or **Options → Change picture**) to pick another one, for games, movies and shows.
- 🎬 **Movies and shows** with covers, descriptions and cast looked up automatically; resume
  where you stopped and watched marks; episodes are grouped into seasons.
- 📶 **Upload over Wi-Fi**: add ROMs, games and videos from a browser (QR code) or a network share.
- 🖧 **Services**: switch on SSH, or share your whole drive in the network while it's unlocked.
- 🕹️ **Controller first**: console-style D-pad navigation, stick and trigger calibration, button
  remapping, your own buttons for the quick menu, lock and keyboard, and a quick menu (volume, brightness, refresh rate, FPS limit, Bluetooth, force quit)
  during games.
- 📺 **Refresh rate**: changed while you play - from the quick menu and from Settings (no
  restart) - on screens gamescope has other rates for (e.g. the Steam Deck); hidden on the others.
- ⚙️ **Device settings**: resolution, refresh rate, brightness, power limit (TDP), audio devices.
- 🌗 Dark and light theme, in a handheld look: corners cut at 45°, the controller's highlight
  lights up along the cuts, and hexagons fade in from the bottom right corner.

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

The bundled Chakra Petch font is under the [SIL Open Font License](gamingcrypt/ui/fonts/OFL.txt).
