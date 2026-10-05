"""Controller layout per emulated system: which console button each Xbox button is.

RetroArch maps the Xbox controller to its "RetroPad" (SNES naming: B bottom, A right,
Y left, X top), and every core maps the RetroPad to its console. The defaults below
describe that; a changed layout is written as RetroArch remap file for the core
(<config>/remaps/<core>/<core>.rmp) before each launch.
"""

from __future__ import annotations

from pathlib import Path

# Xbox button (controller test ids) -> RetroPad button RetroArch's Xbox profile gives it
XBOX_RETROPAD = {"a": "b", "b": "a", "x": "y", "y": "x", "lb": "l", "rb": "r", "lt": "l2", "rt": "r2",
                 "back": "select", "start": "start", "l3": "l3", "r3": "r3"}
RETROPAD_IDS = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6, "right": 7, "a": 8,
                "x": 9, "l": 10, "r": 11, "l2": 12, "r2": 13, "l3": 14, "r3": 15}

# console button -> RetroPad button (how the cores map it)
CONSOLES: dict[str, dict[str, str]] = {
    "nes": {"B": "b", "A": "a", "Turbo B": "y", "Turbo A": "x", "Select": "select", "Start": "start"},
    "snes": {"B": "b", "A": "a", "Y": "y", "X": "x", "L": "l", "R": "r", "Select": "select", "Start": "start"},
    "n64": {"A": "b", "B": "y", "Z": "l2", "L": "l", "R": "r", "Start": "start", "C-Down": "a", "C-Left": "x",
            "C-buttons (stick)": "r3"},
    "gb": {"B": "b", "A": "a", "Select": "select", "Start": "start"},
    "gbc": {"B": "b", "A": "a", "Select": "select", "Start": "start"},
    "gba": {"B": "b", "A": "a", "L": "l", "R": "r", "Select": "select", "Start": "start"},
    "nds": {"B": "b", "A": "a", "Y": "y", "X": "x", "L": "l", "R": "r", "Select": "select", "Start": "start",
            "Touch / Mic": "r3"},
    "gc": {"A": "b", "B": "y", "X": "a", "Y": "x", "Z": "r", "L": "l2", "R": "r2", "Start": "start"},
    "mastersystem": {"1": "b", "2": "a", "Pause": "start"},
    "megadrive": {"A": "y", "B": "b", "C": "a", "X": "l", "Y": "x", "Z": "r", "Mode": "select", "Start": "start"},
    "gamegear": {"1": "b", "2": "a", "Start": "start"},
    "segacd": {"A": "y", "B": "b", "C": "a", "X": "l", "Y": "x", "Z": "r", "Mode": "select", "Start": "start"},
    "saturn": {"A": "b", "B": "a", "C": "r2", "X": "y", "Y": "x", "Z": "l2", "L": "l", "R": "r",
               "Start": "start"},
    "dreamcast": {"A": "b", "B": "a", "X": "y", "Y": "x", "L trigger": "l2", "R trigger": "r2",
                  "Start": "start"},
    "psx": {"Cross": "b", "Circle": "a", "Square": "y", "Triangle": "x", "L1": "l", "R1": "r", "L2": "l2",
            "R2": "r2", "L3": "l3", "R3": "r3", "Select": "select", "Start": "start"},
    "psp": {"Cross": "b", "Circle": "a", "Square": "y", "Triangle": "x", "L": "l", "R": "r", "Select": "select",
            "Start": "start"},
    "pce": {"II": "b", "I": "a", "Select": "select", "Run": "start"},
    "atari2600": {"Fire": "b", "Select": "select", "Reset": "start"},
    "arcade": {"Button 1": "b", "Button 2": "a", "Button 3": "y", "Button 4": "x", "Button 5": "l",
               "Button 6": "r", "Coin": "select", "Start": "start"},
}
GENERIC = {"B": "b", "A": "a", "Y": "y", "X": "x", "L": "l", "R": "r", "L2": "l2", "R2": "r2", "L3": "l3",
           "R3": "r3", "Select": "select", "Start": "start"}
# RetroArch's core names (remap folder); the core's .info file wins when installed
CORE_NAMES = {"snes9x": "Snes9x", "bsnes": "bsnes", "mupen64plus_next": "Mupen64Plus-Next",
              "parallel_n64": "ParaLLEl N64", "gambatte": "Gambatte", "sameboy": "SameBoy", "mgba": "mGBA",
              "vba_next": "VBA Next", "melonds": "melonDS", "desmume": "DeSmuME", "dolphin": "dolphin-emu",
              "genesis_plus_gx": "Genesis Plus GX", "picodrive": "PicoDrive", "mednafen_saturn": "Beetle Saturn",
              "yabasanshiro": "YabaSanshiro", "flycast": "Flycast", "swanstation": "SwanStation",
              "mednafen_psx_hw": "Beetle PSX HW", "pcsx_rearmed": "PCSX-ReARMed", "ppsspp": "PPSSPP",
              "mednafen_pce_fast": "Beetle PCE Fast", "stella": "Stella", "fbneo": "FinalBurn Neo",
              "mame2003_plus": "MAME 2003-Plus", "mesen": "Mesen", "nestopia": "Nestopia", "fceumm": "FCEUmm"}
INFO_DIR = Path("/usr/share/libretro/info")


def console(system_id: str) -> dict[str, str]:
    return CONSOLES.get(system_id, GENERIC)


def labels(system_id: str, custom: dict[str, str] | None = None) -> dict[str, str]:
    """Xbox button -> console button name (for the schematic)."""
    by_retropad = {pad: name for name, pad in console(system_id).items()}
    result = {}
    for xbox, pad in XBOX_RETROPAD.items():
        name = (custom or {}).get(xbox) or by_retropad.get(pad)
        if name:
            result[xbox] = name
    return result


def core_name(core_file: str, info_dir: Path = INFO_DIR) -> str:
    """RetroArch's name for a core ("snes9x_libretro.so" -> "Snes9x")."""
    short = core_file.removesuffix(".so").removesuffix("_libretro")
    try:
        for line in (info_dir / f"{short}_libretro.info").read_text().splitlines():
            if line.startswith("corename"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return CORE_NAMES.get(short, short)


def remap_lines(system_id: str, custom: dict[str, str]) -> list[str]:
    """RetroArch remap: the button that is RetroPad <physical> now sends <id>."""
    pads = console(system_id)
    lines = ['input_remap_port_p1 = "0"']
    for xbox, physical in XBOX_RETROPAD.items():
        wanted = pads.get(custom.get(xbox, ""), physical)
        lines.append(f'input_player1_btn_{physical} = "{RETROPAD_IDS[wanted]}"')
    return lines


def write_remap(remap_dir: Path, core_file: str, system_id: str, custom: dict[str, str],
                info_dir: Path = INFO_DIR) -> Path | None:
    """The core's remap file - or none at all for the default layout (RetroArch's own)."""
    name = core_name(core_file, info_dir)
    path = remap_dir / name / f"{name}.rmp"
    if not custom:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(remap_lines(system_id, custom)) + "\n")
    return path


def load(config: dict, system_id: str) -> dict[str, str]:
    data = config.get("input", {}).get("layouts", {}).get(system_id, {})
    valid = set(console(system_id))
    return {k: v for k, v in data.items() if k in XBOX_RETROPAD and v in valid} if isinstance(data, dict) else {}


def save(config: dict, system_id: str, custom: dict[str, str]) -> None:
    layouts = config.setdefault("input", {}).setdefault("layouts", {})
    if custom:
        layouts[system_id] = dict(custom)
    else:
        layouts.pop(system_id, None)


XBOX_NAMES = {"a": "A", "b": "B", "x": "X", "y": "Y", "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
              "back": "View", "start": "Menu", "l3": "L3", "r3": "R3"}


class Store:
    """The layouts in the config: what the controls page and the controller test change."""

    def __init__(self, config: dict, save):
        self.config, self.save_config = config, save

    def choices(self, system: str) -> list[str]:
        return list(console(system))

    def get(self, system: str) -> dict:
        return load(self.config, system)

    def labels(self, system: str) -> dict[str, str]:
        return labels(system, load(self.config, system))

    def set(self, system: str, button: str, name: str | None) -> None:
        custom = load(self.config, system)
        if name is None or name == labels(system).get(button):
            custom.pop(button, None)  # the default again
        else:
            custom[button] = name
        save(self.config, system, custom)
        self.save_config(self.config)

    def reset(self, system: str) -> None:
        save(self.config, system, {})
        self.save_config(self.config)
