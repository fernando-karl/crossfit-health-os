"""Shared UI labels used by landing demo and dashboard must exist in all locales."""
import json
from pathlib import Path

import pytest

I18N_DIR = Path(__file__).resolve().parents[1] / "app" / "i18n"

REQUIRED_SHARED_KEYS = [
    "shared.readiness",
    "shared.today_readiness",
    "shared.hrv",
    "shared.hrv_ms",
    "shared.sleep_label",
    "shared.recovery_source_pill",
    "shared.adapted_to_recovery",
    "shared.session_log",
    "shared.set_logged",
    "shared.phases.build",
    "shared.phases.deload",
    "shared.phases.intensity",
    "shared.phases.test",
    "shared.block_type.accumulation",
    "shared.block_type.deload",
]


def _flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(_flatten(val, path))
        else:
            out[path] = str(val)
    return out


@pytest.mark.parametrize("locale", ["en", "pt-BR"])
def test_shared_labels_present(locale: str):
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    flat = _flatten(data)
    missing = [k for k in REQUIRED_SHARED_KEYS if k not in flat]
    assert not missing, f"Missing in {locale}: {missing}"
