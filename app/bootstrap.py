from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_CONFIG, CONFIG_PATH, CUSTOM_CSS_PATH, save_config


def ensure_first_run_files(project_root: Path) -> None:
    """
    Ensure ./config.yaml and ./custom.css exist.
    - config.yaml is generated with defaults
    - custom.css is generated (empty + comments)
    """
    config_path = project_root / CONFIG_PATH
    if not config_path.exists():
        save_config(DEFAULT_CONFIG, config_path)

    custom_css_path = project_root / CUSTOM_CSS_PATH
    if not custom_css_path.exists():
        custom_css_path.write_text(
            "/* custom.css\n"
            "   This file overrides the embedded default.css.\n"
            "   Example:\n"
            "   :root { --font-size: 34px; }\n"
            "   .title { display: none; }\n"
            "*/\n",
            encoding="utf-8",
        )


