"""Owns the controller profile and the background remapper."""

from __future__ import annotations

from typing import Callable

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import Profile, default_profile
from gamingcrypt.input.remapper import Remapper


class InputService:
    def __init__(self, config: dict, save: Callable[[dict], None],
                 finder: Callable[[], list[e.DeviceInfo]] | None = None,
                 remapper_factory: Callable[[e.DeviceInfo, Profile], Remapper] | None = None):
        self.config = config
        self.save = save
        self.finder = finder
        # every controller connected (one over Bluetooth too) feeds the virtual one, each with its
        # own profile - and later ones are found while it runs
        self.remapper_factory = remapper_factory or (
            lambda info, profile: Remapper(info, profile, find=self.devices, profile_for=self.profile))
        self.remapper: Remapper | None = None
        self.error = ""
        config.setdefault("input", {"enabled": False, "profiles": {}})
        self.cfg = config["input"]
        self.cfg.setdefault("profiles", {})

    def devices(self) -> list[e.DeviceInfo]:
        """Every controller connected (the built-in one first)."""
        return self.finder() if self.finder is not None else e.find_gamepads()

    def device(self) -> e.DeviceInfo | None:
        pads = self.devices()
        return pads[0] if pads else None

    def profile(self, device: e.DeviceInfo) -> Profile:
        data = self.cfg["profiles"].get(device.key)
        return Profile.from_dict(data) if data else default_profile(device.keys, device.axes, device.vendor)

    def save_profile(self, device: e.DeviceInfo, profile: Profile) -> None:
        self.cfg["profiles"][device.key] = profile.to_dict()
        self.save(self.config)
        if self.running:
            self.stop()
            self.start()

    def reset_profile(self, device: e.DeviceInfo) -> Profile:
        self.cfg["profiles"].pop(device.key, None)
        self.save(self.config)
        return self.profile(device)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled"))

    @property
    def running(self) -> bool:
        return self.remapper is not None and self.remapper.running

    def set_enabled(self, enabled: bool) -> bool:
        self.cfg["enabled"] = enabled
        self.save(self.config)
        if enabled:
            return self.start()
        self.stop()
        return True

    def start(self) -> bool:
        """Start the virtual controller if enabled and a controller is connected."""
        self.error = ""
        if not self.enabled or self.running:
            return self.running
        device = self.device()
        if device is None:
            self.error = "No controller found"
            return False
        self.remapper = self.remapper_factory(device, self.profile(device))
        if not self.remapper.start():
            self.error = self.remapper.error or "could not start"
            self.remapper = None
            return False
        return True

    def stop(self) -> None:
        if self.remapper is not None:
            self.remapper.stop()
            self.remapper = None

    def divert(self, target) -> None:
        """target(events): the controller goes there instead of to the game (the on-screen keyboard
        over it) - None: to the game again. Without the mapping the game reads the real one itself."""
        if self.remapper is not None:
            self.remapper.divert = target

    def pause(self) -> bool:
        """While calibrating/mapping we need the raw controller. Returns whether it was running."""
        was_running = self.running
        self.stop()
        return was_running

    def resume(self, was_running: bool) -> None:
        if was_running:
            self.start()

    def game_env(self) -> dict[str, str]:
        """For games that pick a controller themselves (Wine's SDL): skip the grabbed real one - it
        gives them nothing, and as the first one found it's often their "player 1" (GTA's GInput)."""
        if not self.running:
            return {}
        hidden = []
        for info in getattr(self.remapper, "infos", None) or [self.remapper.info]:  # (all read now)
            try:
                vendor, product = int(info.vendor, 16), int(info.product, 16)
            except ValueError:
                continue
            if (vendor, product) == (e.VIRTUAL_VENDOR, e.VIRTUAL_PRODUCT):
                continue  # the same id: skipping it would hide the virtual one too
            if (entry := f"0x{vendor:04x}/0x{product:04x}") not in hidden:
                hidden.append(entry)
        return {"SDL_GAMECONTROLLER_IGNORE_DEVICES": ",".join(hidden)} if hidden else {}
