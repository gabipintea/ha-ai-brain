"""One physical device exposed twice (for example through Matter and HomeKit): find the twin entities and treat them as one (pure logic).

Home Assistant keeps two separate devices for it, but the device registry gives both the same manufacturer and serial number.
Two entities are twins when their devices share manufacturer + serial, they are the same kind of entity, and they live on
different devices (several entities on one device, such as a blind and its battery, are never twins).
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from ha_ai_brain.domain.models import EntityState, Transition

MIN_SERIAL_LENGTH = 6  # shorter values are usually placeholders ("1", "0000")
ECHO_SECONDS = 10.0  # a twin that reports the same change within this window is the same movement
_SWITCHABLE = frozenset({"light", "switch"})


@dataclass(frozen=True)
class EntityFacts:
    """What the device / entity registries say about one entity."""

    entity_id: str
    device_id: str
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    platform: str = ""
    area_id: str | None = None
    disabled: bool = False
    hidden: bool = False
    registry_id: str = ""


@dataclass
class TwinGroup:
    group_id: str
    canonical: str
    members: list[str]
    manufacturer: str
    model: str
    serial_hint: str  # last characters only; the full serial is not needed on screen
    platforms: list[str] = field(default_factory=list)
    why_canonical: str = ""
    moved_together: int = 0  # movements reported by both entities within ECHO_SECONDS
    twin_changes: int = 0  # distinct movements of the device in the mined window

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TwinMap:
    """entity -> canonical entity for every twin group; an empty map changes nothing."""

    def __init__(self, groups: list[TwinGroup] | None = None) -> None:
        self.groups = groups or []
        self._canonical: dict[str, str] = {}
        self._group_of: dict[str, TwinGroup] = {}
        for g in self.groups:
            for m in g.members:
                self._canonical[m] = g.canonical
                self._group_of[m] = g

    def __bool__(self) -> bool:
        return bool(self.groups)

    def canonical(self, entity_id: str) -> str:
        return self._canonical.get(entity_id, entity_id)

    def group_of(self, entity_id: str) -> TwinGroup | None:
        return self._group_of.get(entity_id)

    def are_twins(self, a: str, b: str) -> bool:
        return a != b and a in self._canonical and self._canonical.get(a) == self._canonical.get(b)

    def same_or_twin(self, a: str, b: str) -> bool:
        return a == b or self.are_twins(a, b)


def _kind(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0]
    return "switchable" if domain in _SWITCHABLE else domain


def group_id_for(members: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:10]


def _usable_serial(serial: str) -> bool:
    s = serial.strip().lower()
    return len(s) >= MIN_SERIAL_LENGTH and len(set(s)) > 1


def _features(state: EntityState | None) -> int:
    try:
        return bin(int(((state.attributes if state else {}) or {}).get("supported_features") or 0)).count("1")
    except (TypeError, ValueError):
        return 0


def _score(facts: EntityFacts, state: EntityState | None, area_ids: dict[str, str | None]) -> tuple[int, int, int, int, str]:
    """Higher is better: usable now, richer controls, has a place, visible; the entity id only breaks ties (stable)."""
    live = 0 if state is None or state.state in ("unavailable", "unknown") else 1
    placed = 1 if (facts.area_id or area_ids.get(facts.entity_id)) else 0
    visible = 0 if (facts.disabled or facts.hidden) else 1
    return (live, _features(state), placed, visible, facts.entity_id)


def _why(best: EntityFacts, others: list[EntityFacts], states: dict[str, EntityState], area_ids: dict[str, str | None]) -> str:
    b = _score(best, states.get(best.entity_id), area_ids)
    reasons: list[str] = []
    for o in others:
        s = _score(o, states.get(o.entity_id), area_ids)
        if b[0] != s[0]:
            reasons.append("it is reachable while the other is not")
        elif b[1] != s[1]:
            reasons.append("it supports more controls")
        elif b[2] != s[2]:
            reasons.append("it has an area assigned")
        elif b[3] != s[3]:
            reasons.append("the other one is hidden or disabled")
    return reasons[0] if reasons else "no difference found; chosen by entity id"


def build_twin_map(
    facts: list[EntityFacts],
    states: dict[str, EntityState] | None = None,
    splits: set[str] | None = None,
) -> TwinMap:
    """Group entities by (manufacturer, serial, kind). `splits` are group ids the homeowner said are not twins."""
    states = states or {}
    area_ids: dict[str, str | None] = {f.entity_id: f.area_id for f in facts}
    buckets: dict[tuple[str, str, str], list[EntityFacts]] = defaultdict(list)
    for f in facts:
        if not f.manufacturer.strip() or not _usable_serial(f.serial) or not f.device_id:
            continue
        if states and f.entity_id not in states:
            continue  # not present in Home Assistant right now
        buckets[(f.manufacturer.strip().lower(), f.serial.strip().lower(), _kind(f.entity_id))].append(f)

    groups: list[TwinGroup] = []
    for (_, _, _), members in buckets.items():
        if len({m.device_id for m in members}) < 2:
            continue  # one device with several entities: not a twin
        ids = sorted(m.entity_id for m in members)
        gid = group_id_for(ids)
        if splits and gid in splits:
            continue
        best = max(members, key=lambda m: _score(m, states.get(m.entity_id), area_ids))
        others = [m for m in members if m is not best]
        groups.append(
            TwinGroup(
                group_id=gid,
                canonical=best.entity_id,
                members=ids,
                manufacturer=best.manufacturer,
                model=best.model,
                serial_hint=best.serial.strip()[-4:],
                platforms=sorted({m.platform for m in members if m.platform}),
                why_canonical=_why(best, others, states, area_ids),
            )
        )
    groups.sort(key=lambda g: g.canonical)
    return TwinMap(groups)


def canonicalize_transitions(transitions: list[Transition], twins: TwinMap) -> list[Transition]:
    """
    Rewrite twin entities onto their canonical entity and drop echoes (the twin reporting the same change a moment later), so the
    history looks like one device. Also fills the 'moved together' evidence on each group. Input is not modified.
    """
    if not twins:
        return transitions
    for g in twins.groups:
        g.moved_together = g.twin_changes = 0
    by_key: dict[tuple[str, str], list[float]] = defaultdict(list)  # (canonical entity, new_state) -> times already kept
    out: list[Transition] = []
    for t in sorted(transitions, key=lambda t: t.ts):
        canon = twins.canonical(t.entity_id)
        if canon == t.entity_id and twins.group_of(t.entity_id) is None:
            out.append(t)
            continue
        group = twins.group_of(t.entity_id)
        ts = t.ts.timestamp()
        times = by_key[(canon, t.new_state)]
        idx = bisect_left(times, ts - ECHO_SECONDS)
        echo = idx < len(times) and times[idx] <= ts + ECHO_SECONDS
        if echo:
            if group is not None:
                group.moved_together += 1  # this movement was reported by both entities
            continue
        if group is not None:
            group.twin_changes += 1  # distinct movements of the device
        times.append(ts)
        out.append(t if canon == t.entity_id else Transition(canon, t.ts, t.old_state, t.new_state, t.origin, t.user_id))
    return out


def reason_for_card(g: TwinGroup) -> str:
    names = " and ".join(g.platforms) if len(g.platforms) == 2 else ", ".join(g.platforms)
    via = f" through {names}" if names else ""
    return (
        f"Same {g.manufacturer} {g.model} (serial ending {g.serial_hint}) seen{via}. Its history is merged onto {g.canonical} "
        f"because {g.why_canonical}."
    ).replace("  ", " ")


def dump_splits(splits: set[str]) -> str:
    return json.dumps(sorted(splits))


def load_splits(raw: str | None) -> set[str]:
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()
