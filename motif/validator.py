"""Validate a Motif scene and explain problems in a way an AI model can fix.

This is the most important file for the "language for AI" idea. A model will
get things wrong; what matters is that every mistake comes back as a short,
specific, actionable message:

    error  timeline[3].target  unknown object 'circel'. Did you mean 'circle1'?

Those messages are fed straight back to the model in the repair loop
(see generate.py), and stored in MongoDB so we can see which mistakes are
common (see docs/02-atlas-and-mongodb.md, "generations" collection).

Two layers of checking:
  1. structure  - Pydantic: right fields, right types, no unknown keys
  2. semantics  - things a schema can't express: ids exist, expressions parse,
                  two actions don't fight over the same property, etc.
"""

from __future__ import annotations

import difflib
import json

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from . import schema as S
from .compiler import ANIMATABLE, COLOR_PROPS, POINT_PROPS, STRING_PROPS, resolve_times
from .expr import ExprError, compile_expr

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
VIEW_X, VIEW_Y = 8.0, 4.5
MAX_DURATION = 120


@dataclass
class Issue:
    level: Literal["error", "warning"]
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:7} {self.path or '(scene)'}: {self.message}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    scene: S.Scene | None = None

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors and self.scene is not None

    def for_model(self) -> str:
        """Compact text for the repair prompt."""
        return "\n".join(str(i) for i in self.issues) or "no issues"

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [asdict(i) for i in self.issues]}


def _path(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


# Names models commonly reach for, mapped to what Motif calls them.
ALIASES: dict[str, list[str]] = {
    "radius": ["r"], "width": ["w"], "height": ["h"], "color": ["fill", "stroke"],
    "colour": ["fill", "stroke"], "position": ["x", "y"], "pos": ["x", "y"], "center": ["x", "y"],
    "from": ["start"], "to": ["end"], "label": ["text"], "content": ["text"],
    "font_size": ["size"], "fontSize": ["size"], "angle": ["rotation"], "rotate": ["rotation"],
    "function": ["expr"], "equation": ["expr"], "formula": ["expr"], "time": ["at"],
    "start_time": ["at"], "delay": ["at"], "parallel": ["with_previous"], "easing": ["ease"],
    "border_radius": ["corner"], "radius_corner": ["corner"], "thickness": ["stroke_width"],
    "line_width": ["stroke_width"], "name": ["id"], "kind": ["type"], "shape": ["type"],
}


def _suggest(word: str, options: list[str]) -> str:
    alias = [o for o in ALIASES.get(word, []) if o in options]
    if alias:
        return " Did you mean " + " / ".join(f"'{a}'" for a in alias) + "?"
    m = difflib.get_close_matches(word, options, n=1, cutoff=0.5)
    return f" Did you mean '{m[0]}'?" if m else ""


# Fields per object/action type, used to suggest fixes for unknown keys.
_FIELDS: dict[str, list[str]] = {}
for _model in (S.Circle, S.Rect, S.Dot, S.Line, S.Arrow, S.Text, S.Axes, S.Graph,
               S.Create, S.FadeIn, S.FadeOut, S.Move, S.Transform, S.Highlight, S.Wait,
               S.Scene, S.Meta, S.Canvas):
    _FIELDS[_model.__name__] = list(_model.model_fields)


def _structural_issues(exc: ValidationError, raw: dict) -> list[Issue]:
    issues = []
    for err in exc.errors():
        loc = tuple(err["loc"])
        # Pydantic puts the union tag in the location, e.g. objects.0.circle.r;
        # strip it so the path matches the user's JSON.
        clean = tuple(p for p in loc if p not in S.OBJECT_TYPES + S.ACTION_TYPES)
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            bad = str(clean[-1])
            model = next((m for m in _model_for(loc)), None)
            hint = _suggest(bad, _FIELDS.get(model, [])) if model else ""
            msg = f"unknown field '{bad}'.{hint}"
        elif err["type"] == "union_tag_invalid":
            kind = "type" if "objects" in loc else "action"
            opts = S.OBJECT_TYPES if kind == "type" else S.ACTION_TYPES
            got = err.get("input", {}).get(kind) if isinstance(err.get("input"), dict) else None
            msg = f"unknown {kind} '{got}'. Must be one of: {', '.join(opts)}.{_suggest(str(got), opts)}"
        elif err["type"] == "union_tag_not_found":
            kind = "type" if "objects" in loc else "action"
            msg = f"missing '{kind}' field"
        issues.append(Issue("error", _path(clean), msg))
    return issues


_TAG_TO_MODEL = {
    "circle": "Circle", "rect": "Rect", "dot": "Dot", "line": "Line", "arrow": "Arrow",
    "text": "Text", "axes": "Axes", "graph": "Graph", "create": "Create",
    "fade_in": "FadeIn", "fade_out": "FadeOut", "move": "Move", "transform": "Transform",
    "highlight": "Highlight", "wait": "Wait",
}


def _model_for(loc: tuple):
    for p in reversed(loc[:-1]):
        if p in _TAG_TO_MODEL:
            yield _TAG_TO_MODEL[p]
            return
    if loc and loc[0] == "meta":
        yield "Meta"
    elif loc and loc[0] == "canvas":
        yield "Canvas"
    else:
        yield "Scene"


def _semantic_issues(scene: S.Scene) -> list[Issue]:
    issues: list[Issue] = []
    err = lambda p, m: issues.append(Issue("error", p, m))  # noqa: E731
    warn = lambda p, m: issues.append(Issue("warning", p, m))  # noqa: E731

    # --- objects
    ids: dict[str, Any] = {}
    for i, o in enumerate(scene.objects):
        p = f"objects[{i}]"
        if o.id in ids:
            err(f"{p}.id", f"duplicate id '{o.id}'. Every object needs a unique id.")
        ids[o.id] = o
        for c in ("fill", "stroke"):
            v = getattr(o, c, None)
            if v is not None and not HEX.match(v):
                err(f"{p}.{c}", f"colour '{v}' must be a 6-digit hex string like '#58c4dd'")
        if o.type == "axes":
            if o.x_range[0] >= o.x_range[1] or o.y_range[0] >= o.y_range[1]:
                err(p, "x_range and y_range must be [min, max] with min < max")
        if o.type in ("circle", "rect", "dot", "text", "axes") and (abs(o.x) > VIEW_X or abs(o.y) > VIEW_Y):
            warn(p, f"'{o.id}' starts off screen at ({o.x}, {o.y}); visible area is x -8..8, y -4.5..4.5")
    if not scene.objects:
        err("objects", "a scene needs at least one object")
    if HEX.match(scene.canvas.background) is None:
        err("canvas.background", "background must be a hex colour like '#0f1117'")

    axes_ids = [k for k, o in ids.items() if o.type == "axes"]
    for i, o in enumerate(scene.objects):
        if o.type != "graph":
            continue
        p = f"objects[{i}]"
        if o.axes not in ids or ids[o.axes].type != "axes":
            err(f"{p}.axes", f"'{o.axes}' is not an axes object.{_suggest(o.axes, axes_ids)}")
        try:
            compile_expr(o.expr)
        except ExprError as exc:
            err(f"{p}.expr", str(exc))

    # --- timeline
    if not scene.timeline:
        err("timeline", "the timeline is empty, so nothing will animate")
        return issues

    id_list = list(ids)
    times = resolve_times(scene.timeline)
    shown_ever: set[str] = {k for k, o in ids.items() if o.visible}
    busy: dict[tuple[str, str], tuple[float, float, int]] = {}  # (obj, prop) -> last use

    for i, a in enumerate(scene.timeline):
        p = f"timeline[{i}]"
        t0, t1 = times[i]
        if a.action == "wait":
            continue
        if a.target not in ids:
            err(f"{p}.target", f"unknown object '{a.target}'.{_suggest(a.target, id_list)}")
            continue
        o = ids[a.target]

        props: set[str] = set()
        if a.action in ("create", "fade_in"):
            props = {"opacity", "draw"}
            shown_ever.add(o.id)
        elif a.action == "fade_out":
            props = {"opacity"}
        elif a.action == "move":
            props = {"x", "y"}
        elif a.action == "highlight":
            props = {"scale"}
        elif a.action == "transform":
            if not a.to:
                err(f"{p}.to", "transform needs at least one property in 'to'")
            allowed = ANIMATABLE[o.type]
            for k, v in a.to.items():
                kp = f"{p}.to.{k}"
                if k not in allowed:
                    err(kp, f"'{k}' can't be animated on a {o.type}. Allowed: "
                            f"{', '.join(sorted(allowed))}.{_suggest(k, sorted(allowed))}")
                    continue
                if k in COLOR_PROPS and not (isinstance(v, str) and HEX.match(v)):
                    err(kp, "colour must be a hex string like '#ff0000'")
                elif k in POINT_PROPS and not (isinstance(v, (list, tuple)) and len(v) == 2):
                    err(kp, "must be a point [x, y]")
                elif k in STRING_PROPS and not isinstance(v, str):
                    err(kp, "must be a string")
                elif k == "expr":
                    try:
                        compile_expr(str(v))
                    except ExprError as exc:
                        err(kp, str(exc))
                elif k not in COLOR_PROPS | POINT_PROPS | STRING_PROPS and not isinstance(v, (int, float)):
                    err(kp, "must be a number")
                if k == "expr":
                    props.add("points")
                else:
                    props.add(k)
            if a.action == "transform" and o.id not in shown_ever:
                warn(p, f"'{o.id}' is transformed before it appears; add a create/fade_in first")
        if a.action in ("move", "highlight", "fade_out") and o.id not in shown_ever:
            warn(p, f"'{o.id}' is not visible yet at t={t0:g}s; add a create or fade_in before this")
        if a.action == "move" and (abs(a.to[0]) > VIEW_X or abs(a.to[1]) > VIEW_Y) and o.type not in ("line", "arrow", "graph"):
            warn(f"{p}.to", f"moves '{o.id}' off screen to {list(a.to)}")

        # Two actions animating the same property of the same object at the same
        # time would fight each other. This is the classic timing bug.
        for prop in props:
            key = (o.id, prop)
            if key in busy:
                b0, b1, j = busy[key]
                if t0 < b1 - 1e-6 and b0 < t1 - 1e-6 and t1 > t0:
                    err(p, f"overlaps timeline[{j}] ({b0:g}-{b1:g}s): both animate '{prop}' of "
                           f"'{o.id}'. Remove with_previous/at or change the timing.")
            if t1 > t0:
                busy[key] = (t0, t1, i)

    for oid, o in ids.items():
        if oid not in shown_ever:
            warn("objects", f"'{oid}' is never shown (no create/fade_in and visible=false)")

    total = max(e for _, e in times)
    if total <= 0:
        err("timeline", "total duration is 0 seconds")
    elif total > MAX_DURATION:
        warn("timeline", f"scene is {total:g}s long; keep scenes under {MAX_DURATION}s")
    return issues


def validate(data: str | dict) -> Report:
    """Validate JSON text or an already-parsed dict."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            return Report([Issue("error", "", f"invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}")])
    if not isinstance(data, dict):
        return Report([Issue("error", "", "a scene must be a JSON object")])
    try:
        scene = S.Scene.model_validate(data)
    except ValidationError as exc:
        return Report(_structural_issues(exc, data))
    return Report(_semantic_issues(scene), scene)


def extract_json(text: str) -> str:
    """Pull a JSON object out of a model reply (handles ```json fences and chatter)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


