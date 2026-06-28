"""
i18n: catalog-based translations for the web UI.

Two locales are supported: ``pt-BR`` (default) and ``en``. Catalogs live in
``backend/app/i18n/<locale>.json`` and are loaded once at import time. Strings
are looked up by dot-notation key (e.g. ``schedule.toast.macro_created``).
Missing keys fall back to the default locale, then to the key itself — UI
never shows ``KeyError``, just an obviously-untranslated key.

The same catalog is exposed to the JS layer by injecting ``window.I18N`` from
``base.html`` so client-side code can call ``t(key, vars)`` without a second
HTTP round-trip per page.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "pt-BR"
SUPPORTED_LOCALES = ("pt-BR", "en")
LOCALE_COOKIE = "lang"

_I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
_CATALOGS: Dict[str, Dict[str, Any]] = {}
_MTIMES: Dict[str, float] = {}
_LAST_CHECK: float = 0.0
_CHECK_INTERVAL_SECONDS = 5.0


def _load_catalogs() -> None:
    for locale in SUPPORTED_LOCALES:
        path = _I18N_DIR / f"{locale}.json"
        if not path.exists():
            logger.warning("i18n catalog missing: %s", path)
            _CATALOGS[locale] = {}
            _MTIMES[locale] = 0.0
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                _CATALOGS[locale] = json.load(f)
            _MTIMES[locale] = path.stat().st_mtime
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse i18n catalog %s: %s", path, exc)
            _CATALOGS[locale] = {}
            _MTIMES[locale] = 0.0


def _maybe_reload_catalogs() -> None:
    """Reload catalogs if any JSON file's mtime changed. Throttled to 5s."""
    global _LAST_CHECK
    now = time.monotonic()
    if now - _LAST_CHECK < _CHECK_INTERVAL_SECONDS:
        return
    _LAST_CHECK = now
    for locale in SUPPORTED_LOCALES:
        path = _I18N_DIR / f"{locale}.json"
        try:
            current_mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            continue
        if current_mtime != _MTIMES.get(locale):
            _load_catalogs()
            return


_load_catalogs()


def _resolve_dotted(catalog: Dict[str, Any], key: str) -> Optional[str]:
    cur: Any = catalog
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, str) else None


def get_catalog(locale: str) -> Dict[str, Any]:
    """Return the raw nested dict for a locale (used to inject into JS)."""
    _maybe_reload_catalogs()
    if locale not in _CATALOGS:
        locale = DEFAULT_LOCALE
    return _CATALOGS.get(locale, {})


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _safe_format(template: str, **vars: Any) -> str:
    """Substitute only the placeholders present in ``vars``; leave the rest."""
    if not vars:
        return template

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(vars[key]) if key in vars else match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, template)


def t(locale: str, key: str, **vars: Any) -> str:
    """Translate ``key`` for ``locale``, interpolating ``{var}`` placeholders.

    Falls back to the default locale, then to the key itself.
    """
    _maybe_reload_catalogs()
    candidates = [locale, DEFAULT_LOCALE] if locale != DEFAULT_LOCALE else [DEFAULT_LOCALE]
    for loc in candidates:
        value = _resolve_dotted(_CATALOGS.get(loc, {}), key)
        if value is not None:
            return _safe_format(value, **vars) if vars else value
    return key


def normalize_locale(raw: Optional[str]) -> Optional[str]:
    """Map an Accept-Language tag (e.g. ``pt``, ``pt_BR``, ``en-US``) to a supported locale."""
    if not raw:
        return None
    raw = raw.strip().replace("_", "-")
    # Exact match wins.
    for sup in SUPPORTED_LOCALES:
        if raw.lower() == sup.lower():
            return sup
    # Prefix match (e.g. "pt" → "pt-BR", "en-US" → "en").
    primary = raw.split("-", 1)[0].lower()
    for sup in SUPPORTED_LOCALES:
        if sup.split("-", 1)[0].lower() == primary:
            return sup
    return None


def parse_accept_language(header: str) -> Optional[str]:
    """Pick the highest-q-value tag from an Accept-Language header that we support."""
    if not header:
        return None
    candidates: list[tuple[float, str]] = []
    for part in header.split(","):
        if ";" in part:
            tag, _, qpart = part.partition(";")
            q = 1.0
            qval = qpart.strip()
            if qval.startswith("q="):
                try:
                    q = float(qval[2:])
                except ValueError:
                    q = 0.0
        else:
            tag, q = part, 1.0
        tag = tag.strip()
        normalized = normalize_locale(tag)
        if normalized:
            candidates.append((q, normalized))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


async def _user_locale(request: Request) -> Optional[str]:
    """Pull ``locale`` from the authenticated user, if any."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        # Web pages also send the JWT via cookie in this app — fall through.
        token = request.cookies.get("access_token")
    else:
        token = auth.split(" ", 1)[1]
    if not token:
        return None
    try:
        from jose import jwt

        from app.core.config import settings
        from app.db.models import User as UserDB
        from app.db.session import SessionLocal

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        with SessionLocal() as db:
            user = db.get(UserDB, int(user_id))
            return normalize_locale(user.locale) if user and user.locale else None
    except Exception:  # noqa: BLE001 — best-effort; never block a request on locale lookup
        return None


class LocaleMiddleware(BaseHTTPMiddleware):
    """Resolves ``request.state.locale`` once per request.

    Order: ``?lang=`` (also writes a cookie) → ``lang`` cookie →
    ``User.locale`` (if authenticated) → ``Accept-Language`` → default.
    """

    async def dispatch(self, request: Request, call_next):
        chosen: Optional[str] = None
        set_cookie = False

        qs_lang = request.query_params.get("lang")
        if qs_lang:
            normalized = normalize_locale(qs_lang)
            if normalized:
                chosen = normalized
                set_cookie = True

        if chosen is None:
            cookie_val = request.cookies.get(LOCALE_COOKIE)
            chosen = normalize_locale(cookie_val)

        if chosen is None:
            chosen = await _user_locale(request)

        if chosen is None:
            chosen = parse_accept_language(request.headers.get("accept-language", ""))

        if chosen is None:
            chosen = DEFAULT_LOCALE

        request.state.locale = chosen

        response: Response = await call_next(request)

        if set_cookie:
            response.set_cookie(
                LOCALE_COOKIE,
                chosen,
                max_age=60 * 60 * 24 * 365,
                samesite="lax",
                path="/",
            )
        return response
