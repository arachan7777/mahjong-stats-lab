"""Stage 8 chronology prototype. Reuses the approved physical replay and reach history.
No scoring or base-dontsuka definitions are changed here.
"""
from dataclasses import dataclass, field, asdict
from dontsuka_v026_6_core import Inventory, state, require
from dontsuka_v026_7_core import History

TENPAI = frozenset(("riichi", "damaten", "open"))
STABLE = frozenset(("haipai", "discard", "ankan", "shominkan", "daiminkan"))
TERMINAL = frozenset(("ron", "tsumo", "ryukyoku"))

@dataclass
class Interval:
    kyoku_id: int
    player_id: int
    start_event_id: int
    start_event_order: int
    start_reason: str
    start_known: bool
    initial: bool
    end_event_id: int | None = None
    end_event_order: int | None = None
    end_reason: str = ""
    draw_count: int = 0
    first_hit_event_id: int | None = None
    first_hit_draw_number: int | None = None
    first_target_hits: dict = field(default_factory=dict)
    states: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.kyoku_id}:{self.player_id}:{self.start_event_id}"

    def start_key(self):
        # All initial 13-tile hands are a common logical instant.
        return (0, 0) if self.initial else (1, self.start_event_order)

    def export(self):
        return dict(asdict(self), interval_id=self.key)

def relation(a, b):
    if a is None or b is None or not a.start_known or not b.start_known:
        return "undetermined"
    x, y = a.start_key(), b.start_key()
    return "self_earlier" if x < y else "self_later" if x > y else "simultaneous"

def rate(n, d):
    require(0 <= n <= d, "rate bound")
    return "" if not d else f"{100*n/d:.9f}"

class RoundTracker:
    def __init__(self, kyoku_id):
        self.kyoku_id = kyoku_id
        self.replay = Inventory()
        self.history = History()
        self.active = {}
        self.intervals = []
        self.uncertain = set()
        self.reach_markers = {}
        self.reach_records = []
        self.first_reach = None
        self.first_reach_states = {}
        self.finished = False
        self.last = None

    def _close(self, p, e, reason):
        a = self.active.pop(p, None)
        if a is not None:
            require(a.end_event_id is None, "double interval closure")
            a.end_event_id, a.end_event_order, a.end_reason = e["id"], e["event_order"], reason
        return a

    def _observe(self, p, e, reason, stable):
        typ, waits, eff = state(self.replay, p)
        if typ == "unknown":
            if stable:
                self._close(p, e, "abnormal_effective_tile_count")
                self.uncertain.add(p)
            return typ, waits, eff
        if typ not in TENPAI:
            if stable:
                self._close(p, e, "tenpai_broken")
                self.uncertain.discard(p)
            return typ, waits, eff
        a = self.active.get(p)
        if a is None:
            known = p not in self.uncertain and stable
            a = Interval(self.kyoku_id, p, e["id"], e["event_order"], reason, known, reason == "haipai")
            self.active[p] = a
            self.intervals.append(a)
        # Keep observed transitions rather than reconstructing them from the final type.
        if not a.states or a.states[-1]["state"] != typ or a.states[-1]["waits"] != list(waits):
            a.states.append(dict(event_id=e["id"], event_order=e["event_order"], state=typ, waits=list(waits), reason=reason))
        return typ, waits, eff

    def _draw_snapshot(self, e, hits):
        p = e["actor"]
        require(len(self.replay.hands) == 4, "four dealt hands")
        states = {}
        for q in self.replay.hands:
            typ, waits, eff = state(self.replay, q)
            if typ in TENPAI and q not in self.active:
                # A valid state without an observed stable onset is not a known onset.
                self._observe(q, e, "pre_draw_onset_unobserved", False)
            if typ == "unknown":
                self._close(q, e, "abnormal_pre_draw")
                self.uncertain.add(q)
            if typ == "not_tenpai" and q in self.active:
                self._close(q, e, "non_tenpai_pre_draw_observation")
                self.uncertain.discard(q)
            a = self.active.get(q) if typ in TENPAI else None
            if typ == "riichi":
                require(q in self.history.established, "riichi state without established reach")
            states[q] = dict(state=typ, waits=list(waits), effective=eff,
                             interval_id=a.key if a else "", start_event_id=a.start_event_id if a else "",
                             start_order=a.start_event_order if a else "", start_known=int(a.start_known) if a else "",
                             initial=int(a.initial) if a else "")
        a = self.active.get(p) if states[p]["state"] in TENPAI else None
        first = False
        first_targets = set()
        if a is not None:
            a.draw_count += 1
            if hits and a.first_hit_event_id is None:
                a.first_hit_event_id = e["id"]
                a.first_hit_draw_number = a.draw_count
                first = True
            for t in hits:
                if t not in a.first_target_hits:
                    a.first_target_hits[t] = dict(event_id=e["id"], draw_number=a.draw_count)
                    first_targets.add(t)
        pairs = []
        for t, target in states.items():
            if t == p:
                continue
            own = states[p]
            b = self.active.get(t) if target["state"] in TENPAI else None
            both = own["state"] in TENPAI and target["state"] in TENPAI
            rel = relation(a, b) if both else "not_both_tenpai"
            if "unknown" in (own["state"], target["state"]):
                rel = "undetermined_state"
            combo = f'{rel}:{own["state"]}:{target["state"]}' if rel in ("self_earlier", "self_later") else ""
            first_reach = self.first_reach
            own_first = bool(first_reach and first_reach["player_id"] == p)
            cl = ""
            if own_first:
                if target["state"] == "riichi":
                    tr = self.history.established.get(t)
                    if tr and tr[0] > first_reach["established_order"]:
                        cl = "chase_riichi"
                    else:
                        cl = "undetermined_reach_order"
                elif target["state"] in ("damaten", "open"):
                    if b is None or not b.start_known:
                        cl = "undetermined_tenpai_onset"
                    elif b.initial or b.start_event_order < first_reach["established_order"]:
                        cl = "prior_" + target["state"]
                    elif b.start_event_order > first_reach["established_order"]:
                        cl = "later_" + target["state"]
                    else:
                        cl = "simultaneous_reach_tenpai"
                elif target["state"] == "unknown":
                    cl = "undetermined_state"
            def reach_fields(q):
                x = self.history.established.get(q)
                m = self.reach_markers.get(q)
                # Declaration is not exposed to an earlier draw.
                return dict(marker_id=m["id"] if m else "", marker_order=m["event_order"] if m else "",
                            established_id=x[1] if x else "", established_order=x[0] if x else "")
            pairs.append(dict(target_id=t, self_info=own.copy(), target_info=target.copy(),
                              self_reach=reach_fields(p), target_reach=reach_fields(t),
                              first_reach_player=first_reach["player_id"] if first_reach else "",
                              first_reach_event=first_reach["established_event_id"] if first_reach else "",
                              first_reach_order=first_reach["established_order"] if first_reach else "",
                              self_first_reach=int(own_first), relation=rel, combination=combo,
                              first_reach_class=cl, target_at_first_reach=self.first_reach_states.get(t, {}).copy(),
                              is_opponent_dontsuka=int(t in hits), first_target_hit=int(t in first_targets)))
        return dict(draw_event_id=e["id"], event_order=e["event_order"], kyoku_id=self.kyoku_id,
                    player_id=p, draw_tile=e["tile"], rinshan=int(bool(e["rinshan"])),
                    self_info=states[p], is_dontsuka=int(bool(hits)), opponent_count=len(hits),
                    interval_draw_number=a.draw_count if a else "", first_hit=int(first), pairs=pairs)

    def feed(self, e, hits=()):
        k, p = e["type"], e.get("actor")
        hits = set(hits)
        if self.finished:
            require(k in TERMINAL or k == "dora_indicator", "hand-changing event after terminal")
            return None
        self.last = e
        if k in TERMINAL:
            for q in list(self.active):
                self._close(q, e, "round_end")
            self.finished = True
            return None
        result = self._draw_snapshot(e, hits) if k == "draw" else None
        self.replay.step(e)
        self.history.record(e)
        if k == "reach":
            require(p not in self.reach_markers, "duplicate reach marker")
            self.reach_markers[p] = dict(e)
        if k in STABLE:
            self._observe(p, e, k, True)
        # Ordinary 14-tile draw / chi / pon is not a stable observation.
        if k == "discard" and e["declaration"]:
            m = self.reach_markers.get(p)
            require(m is not None, "declaration without marker")
            r = dict(kyoku_id=self.kyoku_id, player_id=p, marker_event_id=m["id"],
                     marker_order=m["event_order"], declaration_event_id=e["id"],
                     declaration_order=e["event_order"], accepted=int(bool(m["accepted"])),
                     established_event_id=e["id"] if m["accepted"] else "",
                     established_order=e["event_order"] if m["accepted"] else "")
            self.reach_records.append(r)
            if m["accepted"] and self.first_reach is None:
                self.first_reach = r.copy()
                for q in self.replay.hands:
                    typ, _, _ = state(self.replay, q)
                    a = self.active.get(q)
                    self.first_reach_states[q] = dict(state=typ, interval_id=a.key if a else "",
                                                       start_known=int(a.start_known) if a else "")
        return result

    def finish(self):
        require(self.finished and not self.active, "round not terminated")
        return [a.export() for a in self.intervals]
