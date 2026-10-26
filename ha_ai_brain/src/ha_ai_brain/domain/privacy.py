"""Reversible scrubbing of personal identifiers before a prompt leaves for a cloud LLM provider."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

_PROTECTED = re.compile(
    r"\bnotify\.mobile_app_[a-z0-9_]+\b"
    r"|\b(?:person|device_tracker)\.[a-z0-9_]+\b"
    r"|\bmobile_app_[a-z0-9_]+\b"
)
_FULL_PROTECTED = re.compile(r"(?:notify\.mobile_app_[a-z0-9_]+|(?:person|device_tracker)\.[a-z0-9_]+)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")
_SENSITIVE_KEYS = frozenset(
    {"latitude", "longitude", "gps_accuracy", "ip_address", "ip", "mac", "mac_address", "bssid", "ssid", "entity_picture", "address"}
)


class PrivacyScrubber:
    """
    Per-request scrubber: people, phones and trackers get stable aliases (restored in the model's answer),
    while e-mails, IP / MAC addresses and coordinates are removed. Entity ids of actuators and sensors are
    kept because the model needs them to propose valid actions.
    """

    def __init__(self) -> None:
        self._fwd: dict[str, str] = {}
        self._rev: dict[str, str] = {}
        self._obj_alias: dict[tuple[str, str], str] = {}
        self._counters: Counter[str] = Counter()

    def _alias(self, token: str) -> str:
        if token in self._fwd:
            return self._fwd[token]
        dom, dot, obj = token.partition(".")
        if not dot:
            dom, obj = "notify", token
        group = "mobile_app" if obj.startswith("mobile_app_") else dom
        key = (group, obj)
        if key not in self._obj_alias:
            self._counters[group] += 1
            n = self._counters[group]
            self._obj_alias[key] = {"person": f"p{n}", "device_tracker": f"d{n}", "mobile_app": f"mobile_app_n{n}"}[group]
        alias = f"{dom}.{self._obj_alias[key]}" if dot else self._obj_alias[key]
        self._fwd[token] = alias
        self._rev[alias] = token
        return alias

    def scrub_text(self, text: str) -> str:
        text = _PROTECTED.sub(lambda m: self._alias(m.group(0)), text)
        text = _EMAIL.sub("[email]", text)
        text = _MAC.sub("[mac]", text)
        return _IPV4.sub("[ip]", text)

    def scrub_obj(self, obj: Any, protected: bool = False) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                key = self.scrub_text(k) if isinstance(k, str) else k
                lowered = str(k).lower()
                if lowered in _SENSITIVE_KEYS:
                    out[key] = "[redacted]"
                elif protected and lowered in ("friendly_name", "name", "source"):
                    out[key] = "[redacted]"
                else:
                    child_protected = protected or (isinstance(k, str) and bool(_FULL_PROTECTED.fullmatch(k)))
                    out[key] = self.scrub_obj(v, child_protected)
            return out
        if isinstance(obj, list):
            return [self.scrub_obj(v, protected) for v in obj]
        if isinstance(obj, str):
            return self.scrub_text(obj)
        return obj

    def scrub_prompt(self, prompt: str) -> str:
        try:
            return json.dumps(self.scrub_obj(json.loads(prompt)), separators=(",", ":"), ensure_ascii=False)
        except (ValueError, TypeError):
            return self.scrub_text(prompt)

    def restore(self, obj: Any) -> Any:
        if not self._rev:
            return obj
        pattern = re.compile("|".join(re.escape(a) for a in sorted(self._rev, key=len, reverse=True)))

        def fix(text: str) -> str:
            return pattern.sub(lambda m: self._rev[m.group(0)], text)

        def walk(o: Any) -> Any:
            if isinstance(o, dict):
                return {(fix(k) if isinstance(k, str) else k): walk(v) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v) for v in o]
            if isinstance(o, str):
                return fix(o)
            return o

        return walk(obj)
