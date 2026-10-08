"""The performance overlay over games as a bar (Settings → Device → In-game bar): where, how
big, how see-through, and what's on it - written as mangoapp's (MangoHud's) config.

The quick menu switches it on and off (gamescope_ctl.apply_overlay); this decides what it
looks like. Every module is written as on or off, so MangoHud's own defaults never add one.
"""

from __future__ import annotations

# module -> (label, MangoHud keys)
MODULES = {
    "fps": ("FPS", ("fps",)),
    "frametime": ("Frame time", ("frametime",)),
    "cpu": ("CPU", ("cpu_stats", "cpu_temp")),
    "gpu": ("GPU", ("gpu_stats", "gpu_temp")),
    "ram": ("RAM", ("ram",)),
    "battery": ("Battery", ("battery",)),
    "power": ("Power draw", ("battery_watt",)),
    "time": ("Time", ("time",)),
}
POSITIONS = {"bottom": ("Bottom", "bottom-center"), "top": ("Top", "top-center")}
SIZES = {"small": ("Small", 18), "medium": ("Medium", 24), "large": ("Large", 32)}
DEFAULT = {"position": "bottom", "size": "medium", "opacity": 50,
           "modules": ["fps", "frametime", "cpu", "gpu", "ram", "battery"]}


def settings_of(config: dict) -> dict:
    """The bar's settings from the config, completed with the defaults (and only known values)."""
    own = config.get("overlay_bar") if isinstance(config.get("overlay_bar"), dict) else {}
    found = {**DEFAULT, **own}
    if found["position"] not in POSITIONS:
        found["position"] = DEFAULT["position"]
    if found["size"] not in SIZES:
        found["size"] = DEFAULT["size"]
    try:
        found["opacity"] = max(0, min(100, int(found["opacity"])))
    except (TypeError, ValueError):
        found["opacity"] = DEFAULT["opacity"]
    found["modules"] = [m for m in MODULES if m in (found.get("modules") or [])]
    return found


def mangohud_config(settings: dict) -> str:
    """The config text for mangoapp: a horizontal bar across the screen."""
    s = settings_of({"overlay_bar": settings})
    lines = ["horizontal", "horizontal_stretch", "frame_timing=0", "round_corners=0", "hud_no_margin",
             f"position={POSITIONS[s['position']][1]}", f"font_size={SIZES[s['size']][1]}",
             f"background_alpha={s['opacity'] / 100:.2f}", "time_format=%H:%M"]
    for module, (_label, keys) in MODULES.items():
        on = 1 if module in s["modules"] else 0
        lines += [f"{key}={on}" for key in keys]
    return "\n".join(lines) + "\n"
