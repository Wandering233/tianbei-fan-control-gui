"""
Atomic JSON configuration persistence for TianBei Fan Control.
"""

import json
import os
import tempfile
from typing import Optional

from .models import FanConfig

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/tianbei-fan-control")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")


def load_config(path: Optional[str] = None) -> FanConfig:
    """Load and validate user configuration from disk, returning defaults on miss."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(cfg_path):
        return FanConfig()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return FanConfig.from_dict(raw)
    except (OSError, ValueError, TypeError):
        return FanConfig()


def save_config(cfg: FanConfig, path: Optional[str] = None, uid: Optional[int] = None, gid: Optional[int] = None) -> None:
    """Atomically write normalized configuration JSON to disk."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    cfg_dir = os.path.dirname(os.path.abspath(cfg_path))
    os.makedirs(cfg_dir, exist_ok=True)
    if uid is not None and gid is not None and os.geteuid() == 0:
        try:
            os.chown(cfg_dir, uid, gid)
        except OSError:
            pass

    payload = json.dumps(cfg.normalized().to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".json", dir=cfg_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.chmod(tmp_path, 0o644)
        if uid is not None and gid is not None and os.geteuid() == 0:
            os.chown(tmp_path, uid, gid)
        os.replace(tmp_path, cfg_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
