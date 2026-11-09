<div align="center">

# 🔒 GamingCrypt

**A console-style launcher for Linux gaming handhelds, with your whole game collection on an encrypted drive.**

Unlock with a PIN, pattern or password and you're in a fullscreen launcher for Steam, emulators,
Windows and Linux games, Minecraft, movies and shows, all usable with a controller or touch.

[![License: MIT](https://img.shields.io/badge/license-MIT-38bdf8.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-38bdf8.svg)
![Linux](https://img.shields.io/badge/platform-Linux-38bdf8.svg)
![Encrypted with VeraCrypt](https://img.shields.io/badge/encrypted-VeraCrypt-38bdf8.svg)

<img src="docs/screenshots/games.png" alt="The GamingCrypt game list" width="820">

[Features](#-features) · [Screenshots](#-screenshots) · [Install](#-install) · [Adding games](#-adding-games) · [Security](#-security) · [Help](#-troubleshooting)

</div>

---

## ✨ Why GamingCrypt?

Handhelds get lost, borrowed and stolen. GamingCrypt keeps your games, saves, accounts and media
inside a **VeraCrypt** volume. Without your code it's just random data. With it, you go straight to a
launcher that feels like a console.

<table>
<tr>
<td width="33%" valign="top">

### 🔐 Locked by default
PIN, swipe pattern, 5×5 tap pattern or password. A panic lock closes everything at once.

</td>
<td width="33%" valign="top">

### 🎮 Everything in one place
Steam, 25 emulated systems, Windows and Linux games, Minecraft, movies and shows, all in one list.

</td>
<td width="33%" valign="top">

### 🕹️ Made for controllers
D-pad navigation, a quick menu during games, an on-screen keyboard and a full touch interface.

</td>
</tr>
<tr>
<td valign="top">

### 👥 For the whole family
Each user has their own code, saves, Steam account and settings. Age ratings hide what isn't for them.

</td>
<td valign="top">

### 🔌 Games on a stick
USB sticks, external drives and SD cards show up in your library, and they're encrypted too.

</td>
<td valign="top">

### 🖥️ Boots like a console
An optional gaming mode starts GamingCrypt on gamescope right after boot, like SteamOS.

</td>
</tr>
</table>

## 📸 Screenshots

| Your games | A game's page | The quick menu |
|:---:|:---:|:---:|
| ![Games](docs/screenshots/games.png) | ![Game page](docs/screenshots/detail.png) | ![Quick menu](docs/screenshots/quickmenu.png) |
| **Unlocking** | **Movies** | **Shows** |
| ![Lock screen](docs/screenshots/lock.png) | ![Movies](docs/screenshots/movies.png) | ![Shows](docs/screenshots/shows.png) |
| **Minecraft** | **A Minecraft instance** | **On-screen keyboard** |
| ![Minecraft](docs/screenshots/minecraft.png) | ![Minecraft instance](docs/screenshots/minecraft-instance.png) | ![Keyboard](docs/screenshots/keyboard.png) |

<details>
<summary><b>☀️ Light theme</b></summary>
<br>

| Games | Game page | Quick menu |
|:---:|:---:|:---:|
| ![Games, light](docs/screenshots/games-light.png) | ![Game page, light](docs/screenshots/detail-light.png) | ![Quick menu, light](docs/screenshots/quickmenu-light.png) |
| **Steam library** | **Settings** | **PIN** |
| ![Steam, light](docs/screenshots/steam-light.png) | ![Settings, light](docs/screenshots/settings-light.png) | ![PIN, light](docs/screenshots/pin-light.png) |

</details>

<details>
<summary><b>🖼️ More screenshots</b></summary>
<br>

| Steam library | Movie page | Show page |
|:---:|:---:|:---:|
| ![Steam](docs/screenshots/steam.png) | ![Movie](docs/screenshots/movie.png) | ![Show](docs/screenshots/show.png) |
| **Episodes** | **Settings** | **First start** |
| ![Episodes](docs/screenshots/episodes.png) | ![Settings](docs/screenshots/settings.png) | ![First start](docs/screenshots/create.png) |
| **5×5 tap pattern** | **Swipe pattern** | |
| ![5×5 pattern](docs/screenshots/grid5.png) | ![Swipe pattern](docs/screenshots/pattern.png) | |

</details>

## 🚀 Features

### 🎮 Games

- **One library for everything**: Steam, emulated, Windows, Linux and Minecraft games side by side.
  Filter by genre, platform and year, sort by name, date or last played, and search.
- **Continue playing**: the game you played last waits at the top. One press and you're back in.
- **Game pages** show the cover blurred in the background and the facts as chips (genre, year,
  play time, where it's stored). Nothing unknown is shown.
- **Wrong or missing picture?** Hold the cover, or use *Options → Change picture*, to pick another.
- **Not recognised?** If a file is patched, translated or renamed, pick the right game from a list
  and it gets its cover, genre and year.

### 🟦 Steam

- Your whole library, plus a download queue and uninstalls without Steam's own dialogs.
- Proton per game, store search and **several Steam accounts**.
- To see games you own but haven't installed, add a [Steam Web API key](https://steamcommunity.com/dev/apikey)
  in *Settings → Steam*.

### 👾 Emulation

- **25 systems**, from the NES to the PS2: GameCube, Wii, Wii U, 3DS, Switch, Dreamcast, Saturn,
  PSP, arcade and more, through RetroArch and Eden.
- **Set up for you**: cores, covers and Dolphin's system files are downloaded automatically. Shaders and
  upscaling are included.
- **Save states**: nine slots per game, each with a picture of the moment, the date, and how long
  you'd played. The newest three are on the game's page, one press to continue. Delete single states
  on the game's *Saves* page.
- **Speed slider** from 0.1× to 10×, and **60 FPS for PAL games** so 50 Hz games don't stutter.
- **Console language** for every system that has one, so games show their text in your language.
- The game is **paused** while the quick menu is open.

<details>
<summary>Wii U notes</summary>

Wii U games work as `.wua`, or as `.wud` / `.wux` with your console's keys in `bios/Cemu/keys.txt`.
They can't be saved as states. They're played with a Wii U Pro Controller. A game that needs the GamePad's
screen or touch gets the GamePad in its ⚙ Options.

</details>

### 🪟 Windows and Linux games

- Copy a game folder onto the drive, pick its start file and play it with **Proton, Wine or natively**.
- Each user gets their own saves and settings (their own Wine prefix).
- The quick menu's **speed slider** works here too, like a speedhack, without restarting the game.

### 🧱 Minecraft (Java Edition)

- **Sign in by QR code** with your phone. There's nothing to type on the handheld.
- Instances with their own worlds, settings and Minecraft version.
- **Played with the controller**: Fabric with Controlify and Sodium, on by default.
- **🧩 Mods** from Modrinth, searched and installed with the controller.
- Uses [portablemc](https://github.com/theorzr/portablemc), which sets itself up.

### 🔌 USB sticks, drives and SD cards

- **Plug it in and its games are in your list**, with a small stick, drive or SD card badge on
  their covers. It's mounted and opened the moment it's connected.
- **Encrypted with your code**: formatting puts a VeraCrypt container on it that opens with the same
  code as your drive, for every user. You choose a name and how much of the stick to encrypt.
- **Move games** to a stick and back with *⚙ Options → Move to…* or in *Settings → Storage*, with
  progress shown. The copy is written in full before the original is deleted, so pulling the stick
  out halfway loses nothing.
- **Unplugged games stay visible** (greyed out) so you know where they are. Each user can switch this
  on or off. The list of what's on which stick is kept on the encrypted drive.
- **Every stick gets its own library page**, and there's an "On a USB stick / SD card" filter.
- **Health checks**: slow sticks, read-only SD cards and damaged sticks are pointed out. A damaged stick
  can be repaired without deleting anything.
- Saves, save states, covers and settings always stay on the encrypted drive.

### 🎬 Movies and shows

- Covers, descriptions and cast are looked up automatically.
- Resume where you stopped, with watched marks. Episodes are grouped into seasons.

### 👥 Users and age ratings

- An **admin** and as many users as you like. Each user has their own code to unlock the same drive.
- Each user has their own Steam account, favorites, play time, saves, save states, theme,
  text size, resolution and performance overlay.
- **Age ratings**: give a user an age and they only see games rated for it (USK from Steam,
  ESRB for emulated games). The admin can rate any game by hand.
- Only the admin can delete or move games, see system settings, and lock media tabs for a user.

### 💾 Saves

- *Options → Saves* shows how big each user's saves are and when they last changed.
- **Back up, restore or delete** saves. Anything that's replaced is backed up first.
- The admin can copy saves from one user to another.

### 🕹️ Controller and device

- **Quick menu** during games: volume, brightness, refresh rate, FPS limit, TDP, Bluetooth, speed and force quit.
- **On-screen keyboard** on a button combination (Guide + X by default). It also types **into games**,
  with Esc, Tab, Ctrl, Alt, arrows and F-keys for PC games.
- Stick and trigger calibration, button remapping, and your own buttons for the quick menu, lock and keyboard.
- Resolution, refresh rate (changed while you play), brightness, power limit and audio devices.

### 📶 Getting things onto it

- **Upload over Wi-Fi** from a browser (scan the QR code) or a network share.
- **SSH**, or share the whole drive on your network while it's unlocked.

### 🌗 Look and feel

- Dark and light theme in a handheld style, with 45° cut corners and a highlight that runs along them.
- Animated tabs, covers that fly onto their page, and a start screen with the game's art.
- Quiet menu sounds and short rumbles. Each can be switched off in *Settings → Device → Appearance*.

## 📦 Install

**You need:**

- Linux with Python 3.10 or newer
- [VeraCrypt](https://veracrypt.fr)
- Steam (native or Flatpak)
- *For gaming mode:* [gamescope](https://github.com/ValveSoftware/gamescope) and LightDM

**Then run:**

```sh
git clone https://github.com/KsmBl/gamingCrypt.git
cd gamingCrypt
./install.sh
```

Start **GamingCrypt** from your app menu or run `gamingcrypt`. The first start helps you
create or choose an encrypted volume and set up how you unlock it.

The installer asks for `sudo` once, to set up a small helper. The helper can only mount and manage
VeraCrypt volumes, so unlocking never asks for a password. It also allows the virtual controller.

| Option | What it does |
|---|---|
| `./install.sh --session` | Boot straight into gaming mode. **⏻ → Desktop mode** takes you to your desktop. |
| `./install.sh --autostart` | Start GamingCrypt when you log in |
| `./install.sh --boot-setup` | Ask the boot questions again (GRUB menu, second OS) |
| `./install.sh --no-sudo` | Skip the VeraCrypt helper (only if VeraCrypt works without root for you) |
| `./install.sh --uninstall` | Remove GamingCrypt. Your settings are kept. |

**Updating:** `git pull && ./install.sh`. After each update, GamingCrypt shows what's new.

## 📂 Adding games

Put your games in these folders on the unlocked drive, or on a USB stick or SD card:

```text
📁 Emulation/
   📁 roms/
      📁 snes/        Super Mario World.sfc
      📁 gba/         …
      📁 ps2/         …            (one folder per system)
   📁 bios/           BIOS files and keys
📁 Windows Games/
   📁 Some Game/      (the whole game folder)
📁 Linux Games/
📁 Movies/
📁 Shows/
```

On a stick, `roms/<system>` works as well as `Emulation/roms/<system>`. You can also use **⬆ Add ROMs** / **⬆ Add games** on a
library page to upload over Wi-Fi, or move games in *Settings → Storage*.

<details>
<summary>System folder names</summary>

`nes` · `snes` · `n64` · `gb` · `gbc` · `gba` · `nds` · `3ds` · `gc` · `wii` · `wiiu` · `switch` ·
`mastersystem` · `megadrive` · `32x` · `gamegear` · `segacd` · `saturn` · `dreamcast` ·
`psx` · `ps2` · `psp` · `pce` · `atari2600` · `arcade`

</details>

## 🛡️ Security

- Your PIN, pattern or password is strengthened with **scrypt** and a random salt before it reaches
  VeraCrypt, so every guess is slow. A short PIN is still a short PIN: use a long password or pattern if
  the drive needs real protection.
- Encrypted sticks use the same key derivation, so every user's code opens them. Changing your code
  updates every stick that's plugged in. A stick that wasn't plugged in is unlocked once with the old code
  in *Settings → Storage*.
- > ⚠️ **Back up `~/.config/gamingcrypt/config.json`.** It holds the salt, and without it the volume
  > can't be opened. Container files also keep a copy next to them (`<container>.gamingcrypt.json`).
- To open the drive or a stick with plain VeraCrypt on another PC, run `gamingcrypt --volume-password`
  to get the real VeraCrypt password.

## 🩺 Troubleshooting

| Problem | Try this |
|---|---|
| Steam games or accounts missing | `gamingcrypt --diagnose` shows which Steam folders, libraries and accounts were found |
| Want to see it in a window | `gamingcrypt --windowed` |
| Something went wrong | The log is in `~/.cache/gamingcrypt/gamingcrypt.log` |
| Uninstalled Steam games don't show | Add a Steam Web API key in *Settings → Steam* |

## 🛠️ Development

```sh
python -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

The screenshots are made with `.venv/bin/python docs/screenshots.py`, using sample data, so no device is needed.

## 📄 License

[MIT](LICENSE). The bundled Chakra Petch font is under the [SIL Open Font License](gamingcrypt/ui/fonts/OFL.txt).
