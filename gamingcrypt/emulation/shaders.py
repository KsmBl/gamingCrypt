"""Shaders for emulated games: a few of RetroArch's slang shaders (package libretro-shaders-slang)
that can be ticked together - GamingCrypt chains the ticked ones into one preset.

A combination per system (config "shaders"), a game can have its own (its profile's "shaders":
a list, [] = none; no entry = the system's).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SHADER_DIRS = (Path("/usr/share/libretro/shaders/shaders_slang"),
               Path.home() / ".config" / "retroarch" / "shaders" / "shaders_slang")  # RetroArch's own download
MISSING = "The shaders aren't installed - run ./install.sh (or: sudo pacman -S libretro-shaders-slang)"


@dataclass(frozen=True)
class Shader:
    id: str
    name: str
    description: str
    preset: str  # in the slang shaders' folder
    group: str  # "color", "3d", "upscale", "screen"

    @property
    def final(self) -> bool:
        """An upscaler or a screen effect: it draws the final picture - one of them at a time
        (a CRT effect on an already upscaled picture draws its lines at the wrong size)."""
        return self.group in FINAL


GROUPS = {"color": "Colors", "3d": "3D games", "upscale": "Upscalers", "screen": "Screen effects"}
FINAL = {"upscale", "screen"}  # one of these at a time
# in the order they're chained: colors first, the upscaler or screen effect last
SHADERS: tuple[Shader, ...] = (
    Shader("handheld_colors", "Handheld colors", "The softer colors of a Game Boy Advance / Color screen",
           "handheld/color-mod/gba-color.slangp", "color"),
    Shader("ntsc", "TV signal (NTSC)", "Colors bleed a little, as over a TV cable - blends dithering",
           "ntsc/ntsc-adaptive.slangp", "color"),
    Shader("fxaa", "Smooth 3D edges (FXAA)", "Fewer jagged edges in 3D games",
           "anti-aliasing/fxaa.slangp", "3d"),
    Shader("sharpen", "Sharpen", "Crisper details, for blurry games", "sharpen/adaptive-sharpen.slangp", "3d"),
    Shader("sharp_pixels", "Sharp pixels", "Every pixel the same size and crisp, without shimmering",
           "pixel-art-scaling/sharp-bilinear-simple.slangp", "upscale"),
    Shader("xbrz", "Smooth pixel art (xBRZ)", "Rounds the stairs of pixel art", "edge-smoothing/xbrz/xbrz-freescale.slangp",
           "upscale"),
    Shader("scalefx", "Smooth pixel art (ScaleFX)", "Rounder, cleaner pixel art - needs more power",
           "edge-smoothing/scalefx/scalefx.slangp", "upscale"),
    Shader("scanlines", "Scanlines", "Dark lines between the rows, as on an old TV", "scanlines/scanline.slangp", "screen"),
    Shader("crt", "CRT TV", "Scanlines, glow and the color mask of a tube TV", "crt/crt-easymode.slangp", "screen"),
    Shader("crt_curved", "Curved CRT TV", "A tube TV with its curved glass", "crt/crt-geom.slangp", "screen"),
    Shader("lcd", "LCD grid", "The pixel grid of a handheld's screen", "handheld/lcd-grid-v2.slangp", "screen"),
    Shader("gameboy", "Game Boy screen", "The green screen of the first Game Boy", "handheld/gameboy.slangp", "screen"),
)
BY_ID = {s.id: s for s in SHADERS}


def folder(dirs=SHADER_DIRS) -> Path | None:
    """Where the slang shaders are (None: not installed)."""
    return next((Path(d) for d in dirs if (Path(d) / "stock.slang").is_file()), None)


def clean(ids) -> list[str]:
    """Known ids, in chain order, one upscaler or screen effect at most (the last one given)."""
    given = [i for i in ids or () if i in BY_ID]
    finals = [i for i in given if BY_ID[i].final]
    return [s.id for s in SHADERS if s.id in given and (not s.final or s.id == finals[-1])]


def toggle(ids, shader_id: str, on: bool) -> list[str]:
    """Tick / untick one; ticking an upscaler or screen effect unticks the one there was."""
    chosen = [i for i in clean(ids) if i != shader_id]
    if on:
        if BY_ID[shader_id].final:
            chosen = [i for i in chosen if not BY_ID[i].final]
        chosen.append(shader_id)
    return clean(chosen)


def describe(ids) -> str:
    ids = clean(ids)
    return " + ".join(BY_ID[i].name for i in ids) if ids else "None"


# --- the choices ---------------------------------------------------------------------------

def system_shaders(config: dict, system_id: str) -> list[str]:
    return clean(config.get("shaders", {}).get(system_id, []))


def set_system_shaders(config: dict, system_id: str, ids) -> None:
    table = config.setdefault("shaders", {})
    if clean(ids):
        table[system_id] = clean(ids)
    else:
        table.pop(system_id, None)


def own_shaders(profile: dict) -> list[str] | None:
    """The game's own combination (None: the system's)."""
    own = profile.get("shaders")
    return clean(own) if isinstance(own, list) else None


def for_game(config: dict, profile: dict, system_id: str) -> list[str]:
    own = own_shaders(profile)
    return own if own is not None else system_shaders(config, system_id)


# --- one preset from several ----------------------------------------------------------------

PASS_KEY = re.compile(r"^(shader|filter_linear|wrap_mode|mipmap_input|alias|float_framebuffer|srgb_framebuffer|"
                      r"frame_count_mod|scale_type_x|scale_type_y|scale_type|scale_x|scale_y|scale)(\d+)$")
TEXTURE_SUFFIXES = ("_linear", "_wrap_mode", "_mipmap")


@dataclass
class Preset:
    passes: list[dict[str, str]] = field(default_factory=list)  # shader paths absolute
    textures: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> {"": path, "_linear": …}
    values: dict[str, str] = field(default_factory=dict)  # parameters


def _lines(path: Path) -> tuple[list[str], dict[str, str]]:
    references, values = [], {}
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#reference"):
            references.append(line[len("#reference"):].strip().strip('"'))
            continue
        if not line or line.startswith(("#", "//")) or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        values[key] = value.split("#")[0].strip().strip('"') if not value.startswith('"') else value.strip('"')
    return references, values


def read_preset(path: Path, depth: int = 0) -> Preset:
    """A .slangp - with the presets it refers to (#reference) - paths made absolute."""
    path = Path(path)
    references, values = _lines(path)
    preset = Preset()
    if depth < 8:
        for ref in references:
            inner = read_preset((path.parent / ref).resolve(), depth + 1)
            preset.passes += inner.passes
            preset.textures.update(inner.textures)
            preset.values.update(inner.values)
    count = int(values.pop("shaders", 0) or 0)
    if count:
        preset.passes = [{} for _ in range(count)]
    names = [n for n in values.pop("textures", "").split(";") if n]
    for name in names:
        preset.textures[name] = {"": str((path.parent / values.pop(name, "")).resolve())}
        for suffix in TEXTURE_SUFFIXES:
            if name + suffix in values:
                preset.textures[name][suffix] = values.pop(name + suffix)
    values.pop("parameters", None)
    for key, value in values.items():
        match = PASS_KEY.match(key)
        if match and int(match.group(2)) < len(preset.passes):
            name, index = match.group(1), int(match.group(2))
            if name == "shader":
                value = str((path.parent / value).resolve())
            preset.passes[index][name] = value
        elif not match:
            preset.values[key] = value
    return preset


def combine(presets: list[Preset]) -> str:
    """One preset: the passes one after another, every texture and parameter."""
    passes, textures, values = [], {}, {}
    for preset in presets:
        passes += preset.passes
        textures.update(preset.textures)
        values.update(preset.values)
    lines = [f"shaders = {len(passes)}"]
    for index, settings in enumerate(passes):
        lines.append("")
        lines += [f'{key}{index} = "{value}"' for key, value in settings.items()]
    if textures:
        lines += ["", f'textures = "{";".join(textures)}"']
        for name, settings in textures.items():
            lines += [f'{name}{suffix} = "{value}"' for suffix, value in settings.items()]
    if values:
        lines.append("")
        lines += [f'{key} = "{value}"' for key, value in values.items()]
    return "\n".join(lines) + "\n"


def write_preset(ids, target: Path, root: Path) -> Path | None:
    """The ticked shaders as one preset file (None: nothing ticked, or a preset is missing)."""
    ids = clean(ids)
    if not ids:
        return None
    try:
        presets = [read_preset(Path(root) / BY_ID[i].preset) for i in ids]
    except (OSError, ValueError):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(combine(presets))
    return target
