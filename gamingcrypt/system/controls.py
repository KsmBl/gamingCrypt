"""All system controls of the device, auto-detected."""

from __future__ import annotations

from dataclasses import dataclass

from gamingcrypt.system import audio, brightness, display, power


@dataclass
class SystemControls:
    display: display.DisplayBackend | None = None
    audio: audio.PulseAudio | None = None
    brightness: brightness.Brightness | None = None
    power: power.PowerControl | None = None

    @classmethod
    def detect(cls) -> "SystemControls":
        return cls(display.detect(), audio.detect(), brightness.detect(), power.detect())

    def find_mode(self, saved: dict) -> tuple[display.Output, display.Mode] | None:
        if self.display is None or not saved:
            return None
        for output in self.display.outputs():
            if output.name != saved.get("output"):
                continue
            for mode in output.modes:
                if (mode.width, mode.height) == (saved.get("width"), saved.get("height")) \
                        and round(mode.refresh) == round(float(saved.get("refresh", 0))):
                    return output, mode
        return None

    def apply_saved(self, system_cfg: dict) -> list[str]:
        """Re-apply what resets on reboot (resolution, power limit). Returns problems, if any."""
        problems = []
        saved_mode = system_cfg.get("display")
        if saved_mode:
            found = self.find_mode(saved_mode)
            if found is None:
                problems.append("saved display mode is not available")
            elif found[0].current != found[1]:
                ok, msg = self.display.set_mode(*found)
                if not ok:
                    problems.append(f"display: {msg}")
        watts = system_cfg.get("power_limit_w")
        if watts and self.power is not None:
            current = self.power.read()
            if current is None or current.current_w != watts:
                ok, msg = self.power.set(watts)
                if not ok:
                    problems.append(f"power limit: {msg}")
        return problems
