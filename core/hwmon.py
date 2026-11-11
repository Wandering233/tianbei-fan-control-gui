"""
Standard Linux hwmon discovery, telemetry reading, and IT8613E fan control.
Uses only kernel hwmon sysfs nodes exposed by the it87 (IT8613E) and k10temp drivers.
"""

import glob
import os
from typing import Any, Dict, Optional, Tuple

from .models import FACTORY_SMART_FAN, FanMode, pwm_to_pct

HWMON_ROOT = "/sys/class/hwmon"
IT8613_NAMES = ("it8613", "it87")


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> Optional[int]:
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        return int(txt)
    except ValueError:
        return None


def _write_int(path: str, value: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{int(value)}\n")


def find_hwmon_by_names(names: Tuple[str, ...]) -> Optional[str]:
    """Locate the first /sys/class/hwmon/hwmon* directory matching any chip name."""
    for entry in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*"))):
        chip_name = _read_text(os.path.join(entry, "name"))
        if chip_name and chip_name.lower() in names:
            return entry
    return None


def find_it8613_hwmon() -> Optional[str]:
    """Locate the IT8613E hwmon directory if the it87 driver is loaded."""
    return find_hwmon_by_names(IT8613_NAMES)


def find_k10temp_hwmon() -> Optional[str]:
    """Locate AMD Ryzen k10temp hwmon directory."""
    return find_hwmon_by_names(("k10temp",))


def read_cpu_temp_c(source: str = "k10temp") -> Optional[float]:
    """Read temperature (°C) from preferred sensor with automatic cross-fallback."""
    order = [source, "it8613_temp3" if source == "k10temp" else "k10temp"]
    for src in order:
        if src == "k10temp":
            k_dir = find_k10temp_hwmon()
            if k_dir:
                mc = _read_int(os.path.join(k_dir, "temp1_input"))
                if mc is not None and -40000 < mc < 150000:
                    return mc / 1000.0
        elif src == "it8613_temp3":
            it_dir = find_it8613_hwmon()
            if it_dir:
                mc = _read_int(os.path.join(it_dir, "temp3_input"))
                if mc is not None and -40000 < mc < 150000:
                    return mc / 1000.0
    return None


def read_telemetry() -> Dict[str, Any]:
    """Read live temperatures, fan RPM, PWM, and SmartGuardian attributes."""
    k_dir = find_k10temp_hwmon()
    it_dir = find_it8613_hwmon()

    k10_mc = _read_int(os.path.join(k_dir, "temp1_input")) if k_dir else None
    k10_c = round(k10_mc / 1000.0, 1) if k10_mc is not None else None

    data: Dict[str, Any] = {
        "driver_loaded": it_dir is not None,
        "hwmon_path": it_dir,
        "k10temp_c": k10_c,
        "it8613_temp1_c": None,
        "it8613_temp2_c": None,
        "it8613_temp3_c": None,
        "fan_rpm": None,
        "pwm": None,
        "pwm_pct": None,
        "pwm_enable": None,
        "auto_start": None,
        "auto_slope": None,
        "auto_point1_c": None,
        "auto_point2_c": None,
        "auto_point3_c": None,
        "hw_inferred_mode": None,
    }

    if not it_dir:
        return data

    def _c(name: str) -> Optional[float]:
        v = _read_int(os.path.join(it_dir, name))
        return round(v / 1000.0, 1) if v is not None else None

    pwm_val = _read_int(os.path.join(it_dir, "pwm2"))
    pwm_en = _read_int(os.path.join(it_dir, "pwm2_enable"))

    data.update({
        "it8613_temp1_c": _c("temp1_input"),
        "it8613_temp2_c": _c("temp2_input"),
        "it8613_temp3_c": _c("temp3_input"),
        "fan_rpm": _read_int(os.path.join(it_dir, "fan2_input")),
        "pwm": pwm_val,
        "pwm_pct": pwm_to_pct(pwm_val) if pwm_val is not None else None,
        "pwm_enable": pwm_en,
        "auto_start": _read_int(os.path.join(it_dir, "pwm2_auto_start")),
        "auto_slope": _read_int(os.path.join(it_dir, "pwm2_auto_slope")),
        "auto_point1_c": _c("pwm2_auto_point1_temp"),
        "auto_point2_c": _c("pwm2_auto_point2_temp"),
        "auto_point3_c": _c("pwm2_auto_point3_temp"),
    })

    if pwm_en == 2:
        data["hw_inferred_mode"] = FanMode.AUTO
    elif pwm_en == 0 or (pwm_en == 1 and pwm_val is not None and pwm_val >= 254):
        data["hw_inferred_mode"] = FanMode.FULL
    elif pwm_en == 1:
        data["hw_inferred_mode"] = FanMode.CURVE

    return data


class It8613Controller:
    """Privileged sysfs writer for the IT8613E CPU fan channel (pwm2/fan2)."""

    def _require_hwmon(self) -> str:
        hwmon = find_it8613_hwmon()
        if not hwmon:
            raise RuntimeError("未检测到 it8613 hwmon 节点，请确认 it87 驱动已加载。")
        # Trigger driver register refresh before writing auto-mode points
        _read_int(os.path.join(hwmon, "pwm2_enable"))
        return hwmon

    def apply_factory_auto(self) -> None:
        """
        Restore factory BIOS SmartGuardian hardware automatic control.
        Writes shared register 0x6B (pwm2_auto_start=70) BEFORE setting
        pwm2_enable=2 so manual PWM residue does not lock the fan at high speed.
        """
        hwmon = self._require_hwmon()
        _write_int(os.path.join(hwmon, "pwm2_auto_point1_temp"), FACTORY_SMART_FAN["point1_temp_mc"])
        _write_int(os.path.join(hwmon, "pwm2_auto_point1_temp_hyst"), FACTORY_SMART_FAN["point1_hyst_mc"])
        _write_int(os.path.join(hwmon, "pwm2_auto_point2_temp"), FACTORY_SMART_FAN["point2_temp_mc"])
        _write_int(os.path.join(hwmon, "pwm2_auto_point3_temp"), FACTORY_SMART_FAN["point3_temp_mc"])
        _write_int(os.path.join(hwmon, "pwm2_auto_slope"), FACTORY_SMART_FAN["slope"])
        _write_int(os.path.join(hwmon, "pwm2_auto_start"), FACTORY_SMART_FAN["start_pwm"])
        _write_int(os.path.join(hwmon, "pwm2_enable"), 2)

    def apply_full_speed(self) -> None:
        """Lock fan to manual 100% duty cycle (PWM=255)."""
        self.apply_manual_pwm(255)

    def apply_manual_pwm(self, pwm: int) -> None:
        """Switch to manual mode (pwm2_enable=1) and set duty [0, 255]."""
        hwmon = self._require_hwmon()
        clamped = max(0, min(255, int(pwm)))
        cur_en = _read_int(os.path.join(hwmon, "pwm2_enable"))
        if cur_en != 1:
            _write_int(os.path.join(hwmon, "pwm2_enable"), 1)
        _write_int(os.path.join(hwmon, "pwm2"), clamped)
