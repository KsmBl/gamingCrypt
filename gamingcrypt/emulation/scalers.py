"""Upscaling of emulated games with the classic pixel-art algorithms (a game's Options).

2D consoles: the algorithm draws the whole picture at 2x / 3x / 4x the console's size (RetroArch
slang shaders), then it's scaled to the screen. 3D consoles: Resolution is the core's internal
resolution, the algorithm smooths the textures - when the core has it (read from the cores).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gamingcrypt.emulation import retroarch

# the consoles' picture size
NATIVE = {"nes": (256, 240), "snes": (256, 224), "n64": (320, 240), "gb": (160, 144), "gbc": (160, 144),
          "gba": (240, 160), "nds": (256, 384), "gc": (640, 528), "mastersystem": (256, 192),
          "megadrive": (320, 224), "gamegear": (160, 144), "segacd": (320, 224), "saturn": (320, 224),
          "dreamcast": (640, 480), "psx": (320, 240), "ps2": (640, 448), "psp": (480, 272), "pce": (256, 224),
          "atari2600": (160, 192), "arcade": (320, 240)}


@dataclass(frozen=True)
class Scaler:
    id: str
    name: str
    factors: tuple[int, ...]  # what it can draw at (2D)
    passes: dict = field(default_factory=dict, compare=False)  # factor -> [pass settings] (paths in the pack)
    textures: dict = field(default_factory=dict, compare=False)  # factor -> {name: {"": path, …}}
    values: dict = field(default_factory=dict, compare=False)  # parameters


def _pass(shader: str, scale: float = 1.0, **extra) -> dict[str, str]:
    settings = {"shader": shader, "filter_linear": "false", "scale_type": "source", "scale": f"{scale:g}"}
    settings.update({k: str(v) for k, v in extra.items()})
    return settings


def _twice(one: list[dict]) -> list[dict]:
    """A 2x algorithm drawn twice: 4x."""
    second = [dict(p) for p in one]
    for settings in second:
        settings.pop("alias", None)
    return one + second


_SAI = "edge-smoothing/eagle/shaders/"
SCALERS: tuple[Scaler, ...] = (
    Scaler("supereagle", "SuperEagle", (2, 4), {
        2: [_pass(_SAI + "supereagle.slang", 2)],
        4: _twice([_pass(_SAI + "supereagle.slang", 2)])}),
    Scaler("super2xsai", "Super 2xSaI", (2, 4), {
        2: [_pass(_SAI + "super-2xsai.slang", 2, wrap_mode="clamp_to_edge", srgb_framebuffer="true")],
        4: _twice([_pass(_SAI + "super-2xsai.slang", 2, wrap_mode="clamp_to_edge", srgb_framebuffer="true")])}),
    Scaler("hq", "HQx", (2, 3, 4), {
        n: [_pass("stock.slang", alias="hqx_refpass"), _pass("edge-smoothing/hqx/shaders/pass1.slang"),
            _pass(f"edge-smoothing/hqx/shaders/hq{n}x.slang", n, wrap_mode="clamp_to_edge", srgb_framebuffer="true")]
        for n in (2, 3, 4)},
        {n: {"LUT": {"": f"edge-smoothing/hqx/resources/hq{n}x.png", "_linear": "false"}} for n in (2, 3, 4)}),
    Scaler("scale", "ScaleNx", (2, 3, 4), {
        2: [_pass("edge-smoothing/scalenx/shaders/scale2x.slang", 2)],
        3: [_pass("edge-smoothing/scalenx/shaders/scale3x.slang", 3)],
        4: _twice([_pass("edge-smoothing/scalenx/shaders/scale2x.slang", 2)])}),
    Scaler("xbr", "xBR", (2, 3, 4), {
        n: [_pass("edge-smoothing/xbr/shaders/support/linearize.slang", alias="XbrSource"),
            _pass("edge-smoothing/xbr/shaders/xbr-lv2-multipass/xbr-lv2-pass0.slang"),
            _pass("edge-smoothing/xbr/shaders/xbr-lv2-multipass/xbr-lv2-pass1.slang", n),
            _pass("edge-smoothing/xbr/shaders/support/delinearize.slang")]
        for n in (2, 3, 4)}, values={"SMALL_DETAILS": "1.0", "WP4": "0.8", "KA": "0.35"}),
    Scaler("xbrz", "xBRZ", (2, 3, 4), {
        n: [_pass("edge-smoothing/xbrz/shaders/xbrz-freescale.slang", n)] for n in (2, 3, 4)}),
)
BY_ID = {s.id: s for s in SCALERS}
TO_SCREEN = _pass("interpolation/shaders/bicubic.slang", scale_type="viewport")  # the rest of the way


def factor(resolution: str | None) -> int:
    """"2x" -> 2; None (native) -> 1."""
    try:
        return int(str(resolution).rstrip("x")) if resolution else 1
    except ValueError:
        return 1


# --- 3D consoles: the algorithm on the textures (the cores' own options) ----------------------

def _n64(key: str):
    def values(scaler: str, n: int) -> dict[str, str] | None:
        mode = {"super2xsai": "X2SAI", "hq": "HQ4X" if n >= 4 else "HQ2X",
                "xbrz": f"{min(max(n, 2), 6)}xBRZ"}.get(scaler)
        return {key: mode} if mode else None
    return values


TEXTURES = {
    "mupen64plus_next": ({"super2xsai", "hq", "xbrz"}, _n64("mupen64plus-txEnhancementMode"), "None"),
    "parallel_n64": ({"super2xsai", "hq", "xbrz"}, _n64("parallel-n64-gliden64-txEnhancementMode"), "None"),
    "swanstation": ({"xbr"}, lambda s, n: {"swanstation_GPU_TextureFilter": "xBR"}, "Nearest"),
    "mednafen_psx_hw": ({"xbr"}, lambda s, n: {"beetle_psx_hw_filter": "xBR"}, "nearest"),
    "flycast": ({"xbrz"}, lambda s, n: {"reicast_texupscale": "2" if n <= 2 else "4"}, "1"),
    "ppsspp": ({"xbrz"}, lambda s, n: {"ppsspp_texture_scaling_type": "xbrz",
                                       "ppsspp_texture_scaling_level": f"{min(max(n, 2), 5)}x"}, None),
}
TEXTURE_OFF = {"mupen64plus_next": {"mupen64plus-txEnhancementMode": "None"},
               "parallel_n64": {"parallel-n64-gliden64-txEnhancementMode": "None"},
               "swanstation": {"swanstation_GPU_TextureFilter": "Nearest"},
               "mednafen_psx_hw": {"beetle_psx_hw_filter": "nearest"},
               "flycast": {"reicast_texupscale": "1"},
               "ppsspp": {"ppsspp_texture_scaling_level": "disabled"}}


def is_3d(core: str) -> bool:
    """A core that renders 3D at an internal resolution of its own (Resolution = that one)."""
    return core in retroarch.UPSCALE


def choices(core: str) -> list[str]:
    """The algorithms this core can use: all on 2D consoles, the texture ones on 3D ones."""
    if is_3d(core):
        return [s.id for s in SCALERS if s.id in TEXTURES.get(core, (set(),))[0]]
    return [s.id for s in SCALERS]


def resolutions(core: str, scaler: str | None) -> list[str]:
    """What Resolution offers: the core's internal ones (3D), the algorithm's factors (2D)."""
    if is_3d(core):
        return retroarch.scales(core)
    if scaler in BY_ID:
        return [f"{n}x" for n in BY_ID[scaler].factors]
    return ["1x"]


def fit_resolution(core: str, scaler: str | None, resolution: str | None) -> str | None:
    """A 2D algorithm needs a factor it has (the nearest one, at least 2x)."""
    if is_3d(core) or scaler not in BY_ID:
        return resolution if is_3d(core) else None
    wanted = max(factor(resolution), 2)
    return f"{min(BY_ID[scaler].factors, key=lambda n: (abs(n - wanted), n))}x"


def texture_options(core: str, scaler: str | None, resolution: str | None) -> dict[str, str]:
    """3D cores: the algorithm as the core's texture option (or the core's own "off")."""
    if core not in TEXTURES:
        return {}
    supported, values, _off = TEXTURES[core]
    if scaler in supported:
        return values(scaler, max(factor(resolution), 2)) or dict(TEXTURE_OFF[core])
    return dict(TEXTURE_OFF[core])


def preset(scaler: str | None, resolution: str | None, root) -> tuple[list[dict], dict, dict]:
    """2D: the algorithm's passes at the factor (paths made absolute) - [] without one."""
    from pathlib import Path

    s = BY_ID.get(scaler or "")
    n = factor(resolution)
    if s is None or n not in s.passes:
        return [], {}, {}
    root = Path(root)
    passes = [{**p, "shader": str(root / p["shader"])} for p in s.passes[n]]
    textures = {name: {**t, "": str(root / t[""])} for name, t in s.textures.get(n, {}).items()}
    return passes, textures, dict(s.values)


# --- what it comes to -------------------------------------------------------------------------

def describe(system_id: str, core: str, scaler: str | None, resolution: str | None,
             screen: tuple[int, int] = (1280, 800)) -> str:
    """The info under the choices: the resolution it renders at, and the rest of the way."""
    w, h = NATIVE.get(system_id, (320, 240))
    n = factor(resolution)
    sw, sh = screen
    rest = f"then scaled to the screen ({sw}×{sh})"
    if is_3d(core):
        base = f"Renders at {w * n}×{h * n}" + (f" ({n}x the console's {w}×{h})" if n > 1 else " (the console's own)")
        name = BY_ID[scaler].name if scaler in BY_ID and scaler in choices(core) else None
        textures = f", textures smoothed with {name}" if name else ""
        return f"{base}{textures} - {rest}"
    if scaler in BY_ID:
        return f"{BY_ID[scaler].name} {n}x: {w}×{h} drawn at {w * n}×{h * n}, {rest}"
    return f"The console's {w}×{h}, {rest}"
