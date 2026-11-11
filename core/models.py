"""
Data models, factory defaults, presets, validation, and fan curve math
for TianBei MACO (ITE IT8613E) fan control.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Tuple


class FanMode:
    AUTO = "auto"      # 1. 原厂默认自动 (Hardware SmartGuardian)
    FULL = "full"      # 2. 全速运转 (Manual 100% PWM=255)
    CURVE = "curve"    # 3. 自定义温控曲线 (Software Closed-Loop via hwmon)

    ALL = (AUTO, FULL, CURVE)

    LABELS = {
        AUTO: "原厂默认自动",
        FULL: "全速运转",
        CURVE: "自定义温控曲线",
    }


# Exact factory BIOS Setup defaults verified from factory_initial_setup.bin
# and OemSmartFanPei + hwmon it8613 readback.
FACTORY_SMART_FAN = {
    "point1_temp_mc": 25000,       # Fan Off Temp: 25 °C
    "point1_hyst_mc": 24000,       # Hysteresis Temp: 24 °C (Delta = 1 °C)
    "point2_temp_mc": 35000,       # Fan Start Temp: 35 °C
    "point3_temp_mc": 95000,       # Full Speed Temp: 95 °C
    "start_pwm": 70,               # Start PWM (shared register 0x6B)
    "slope": 24,                   # Slope = 3 << 3 = 24 (3.0 PWM/°C)
    "auto_channels_temp": 3,       # temp3 (CPU diode/PECI)
}

TEMP_MIN_C = 20
TEMP_MAX_C = 100
CRITICAL_MIN_C = 80
CRITICAL_MAX_C = 100
DEFAULT_CRITICAL_C = 90
MIN_CURVE_POINTS = 2
MAX_CURVE_POINTS = 8


@dataclass
class CurvePoint:
    """Single temperature-to-fan-speed control point."""
    temp_c: int
    speed_pct: int

    def to_dict(self) -> Dict[str, int]:
        return {"temp_c": int(self.temp_c), "speed_pct": int(self.speed_pct)}

    @classmethod
    def from_any(cls, item: Any) -> "CurvePoint":
        if isinstance(item, CurvePoint):
            return cls(int(item.temp_c), int(item.speed_pct))
        if isinstance(item, dict):
            return cls(int(item["temp_c"]), int(item["speed_pct"]))
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return cls(int(item[0]), int(item[1]))
        raise ValueError(f"无效的曲线节点格式: {item!r}")


CURVE_PRESETS: Dict[str, Tuple[str, List[CurvePoint]]] = {
    "silent": (
        "静音优先",
        [
            CurvePoint(35, 20),
            CurvePoint(55, 32),
            CurvePoint(70, 50),
            CurvePoint(82, 76),
            CurvePoint(92, 100),
        ],
    ),
    "balanced": (
        "均衡推荐",
        [
            CurvePoint(35, 28),
            CurvePoint(50, 42),
            CurvePoint(65, 62),
            CurvePoint(78, 84),
            CurvePoint(88, 100),
        ],
    ),
    "performance": (
        "性能激进",
        [
            CurvePoint(30, 35),
            CurvePoint(45, 55),
            CurvePoint(60, 75),
            CurvePoint(72, 92),
            CurvePoint(82, 100),
        ],
    ),
}


@dataclass
class FanConfig:
    """Persistent user configuration for TianBei Fan Control."""
    mode: str = FanMode.AUTO
    sensor_source: str = "k10temp"   # "k10temp" | "it8613_temp3"
    hysteresis_c: int = 3
    poll_interval_s: float = 1.0
    critical_temp_c: int = DEFAULT_CRITICAL_C
    points: List[CurvePoint] = field(
        default_factory=lambda: [CurvePoint(p.temp_c, p.speed_pct) for p in CURVE_PRESETS["balanced"][1]]
    )

    def normalized(self) -> "FanConfig":
        mode = self.mode if self.mode in FanMode.ALL else FanMode.AUTO
        sensor = self.sensor_source if self.sensor_source in ("k10temp", "it8613_temp3") else "k10temp"
        hyst = max(1, min(10, int(self.hysteresis_c)))
        poll = max(0.5, min(5.0, round(float(self.poll_interval_s), 1)))
        crit = max(CRITICAL_MIN_C, min(CRITICAL_MAX_C, int(self.critical_temp_c)))
        pts = validate_and_normalize_points(self.points)
        return FanConfig(
            mode=mode,
            sensor_source=sensor,
            hysteresis_c=hyst,
            poll_interval_s=poll,
            critical_temp_c=crit,
            points=pts,
        )

    def to_dict(self) -> Dict[str, Any]:
        c = self.normalized()
        return {
            "mode": c.mode,
            "sensor_source": c.sensor_source,
            "hysteresis_c": c.hysteresis_c,
            "poll_interval_s": c.poll_interval_s,
            "critical_temp_c": c.critical_temp_c,
            "points": [p.to_dict() for p in c.points],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FanConfig":
        if not isinstance(data, dict):
            return cls()
        raw_pts = data.get("points")
        pts = (
            validate_and_normalize_points(raw_pts)
            if isinstance(raw_pts, list) and len(raw_pts) >= MIN_CURVE_POINTS
            else [CurvePoint(p.temp_c, p.speed_pct) for p in CURVE_PRESETS["balanced"][1]]
        )
        return cls(
            mode=str(data.get("mode", FanMode.AUTO)),
            sensor_source=str(data.get("sensor_source", "k10temp")),
            hysteresis_c=int(data.get("hysteresis_c", 3)),
            poll_interval_s=float(data.get("poll_interval_s", 1.0)),
            critical_temp_c=int(data.get("critical_temp_c", DEFAULT_CRITICAL_C)),
            points=pts,
        ).normalized()


def validate_and_normalize_points(raw_points: List[Any]) -> List[CurvePoint]:
    """
    Clamp, sort, deduplicate temperatures, and enforce monotonic curve points.
    """
    if not raw_points or len(raw_points) < MIN_CURVE_POINTS:
        raise ValueError(f"温控曲线至少需要 {MIN_CURVE_POINTS} 个控制点")
    if len(raw_points) > MAX_CURVE_POINTS:
        raw_points = raw_points[:MAX_CURVE_POINTS]

    parsed = []
    for item in raw_points:
        pt = CurvePoint.from_any(item)
        t = max(TEMP_MIN_C, min(TEMP_MAX_C, int(pt.temp_c)))
        s = max(0, min(100, int(pt.speed_pct)))
        parsed.append(CurvePoint(t, s))

    parsed.sort(key=lambda p: (p.temp_c, p.speed_pct))

    # Enforce strictly increasing temperatures while preserving user-chosen percentages
    normalized: List[CurvePoint] = []
    for idx, pt in enumerate(parsed):
        t = pt.temp_c
        s = pt.speed_pct
        if normalized:
            prev = normalized[-1]
            if t <= prev.temp_c:
                t = min(TEMP_MAX_C, prev.temp_c + 1)
        # Reserve room for trailing points if near 100°C
        remaining = len(parsed) - idx - 1
        max_allowed_t = TEMP_MAX_C - remaining
        t = min(t, max_allowed_t)
        if normalized and t <= normalized[-1].temp_c:
            raise ValueError("控制点温度必须严格递增且留出间隔")
        normalized.append(CurvePoint(t, s))

    return normalized


def interpolate_curve_pct(
    temp_c: float,
    points: List[CurvePoint],
    critical_temp_c: int = DEFAULT_CRITICAL_C,
) -> float:
    """
    Compute target fan speed percentage using piecewise-linear interpolation
    and a mandatory critical high-temperature failsafe override.
    """
    if temp_c >= critical_temp_c:
        return 100.0
    if not points:
        return 100.0
    if temp_c <= points[0].temp_c:
        return float(points[0].speed_pct)
    if temp_c >= points[-1].temp_c:
        return float(points[-1].speed_pct)

    for i in range(len(points) - 1):
        p1, p2 = points[i], points[i + 1]
        if p1.temp_c <= temp_c <= p2.temp_c:
            dt = p2.temp_c - p1.temp_c
            if dt <= 0:
                return float(p2.speed_pct)
            ratio = (temp_c - p1.temp_c) / dt
            return p1.speed_pct + ratio * (p2.speed_pct - p1.speed_pct)
    return float(points[-1].speed_pct)


def pct_to_pwm(pct: float) -> int:
    """Convert percentage [0, 100] to 8-bit PWM [0, 255]."""
    clamped = max(0.0, min(100.0, float(pct)))
    return int(round(clamped * 255.0 / 100.0))


def pwm_to_pct(pwm: int) -> int:
    """Convert 8-bit PWM [0, 255] to rounded percentage [0, 100]."""
    clamped = max(0, min(255, int(pwm)))
    return int(round(clamped * 100.0 / 255.0))


def factory_preview_points() -> List[CurvePoint]:
    """
    Approximate visualization curve for the hardware SmartGuardian factory defaults:
    Off=25°C (0%), Start=35°C (StartPWM=70 -> ~27%), Slope=3.0 PWM/°C -> Full@95°C (100%).
    """
    start_t = FACTORY_SMART_FAN["point2_temp_mc"] // 1000
    full_t = FACTORY_SMART_FAN["point3_temp_mc"] // 1000
    off_t = FACTORY_SMART_FAN["point1_temp_mc"] // 1000
    start_pwm = FACTORY_SMART_FAN["start_pwm"]
    slope_per_c = FACTORY_SMART_FAN["slope"] / 8.0

    pts = [
        CurvePoint(TEMP_MIN_C, 0),
        CurvePoint(off_t, 0),
        CurvePoint(start_t, pwm_to_pct(start_pwm)),
    ]
    for sample_t in (55, 75):
        if start_t < sample_t < full_t:
            pwm_val = min(255, int(round(start_pwm + (sample_t - start_t) * slope_per_c)))
            pts.append(CurvePoint(sample_t, pwm_to_pct(pwm_val)))
    pts.append(CurvePoint(full_t, 100))
    pts.append(CurvePoint(TEMP_MAX_C, 100))
    return pts
