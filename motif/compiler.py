"""Compile a validated Scene into flat animation tracks for the browser player.

The scene format is written for *authors* (humans and AI models): "move c1 to
(3, 0) after the previous step". The player wants something dumber: for every
object, a list of segments "property p goes from a to b between t0 and t1".

Compilation is a small simulation:
  1. resolve when each action starts and ends (resolve_times)
  2. walk the actions in start order, tracking each object's current state,
     and emit segments with concrete from/to values
  3. pre-compute anything expensive (graph sample points, axes ticks)

The output is plain JSON, so it can also be cached in MongoDB (see db.py).
"""

from __future__ import annotations

import math
from typing import Any

from . import schema as S
from .expr import compile_expr

RENDERER_VERSION = "0.1.0"

# Properties `transform` may change, per object type.
COMMON_PROPS = {"x", "y", "opacity", "scale", "rotation"}
ANIMATABLE: dict[str, set[str]] = {
    "circle": COMMON_PROPS | {"r", "fill", "stroke", "stroke_width"},
    "rect": COMMON_PROPS | {"w", "h", "corner", "fill", "stroke", "stroke_width"},
    "dot": COMMON_PROPS | {"r", "fill"},
    "line": COMMON_PROPS | {"start", "end", "stroke", "stroke_width"},
    "arrow": COMMON_PROPS | {"start", "end", "stroke", "stroke_width"},
    "text": COMMON_PROPS | {"fill", "size", "text"},
    "axes": COMMON_PROPS | {"stroke", "stroke_width"},
    "graph": COMMON_PROPS | {"expr", "stroke", "stroke_width"},
}
COLOR_PROPS = {"fill", "stroke"}
POINT_PROPS = {"start", "end"}
STRING_PROPS = {"text", "expr"}
# Properties that change instantly instead of interpolating.
SNAP_PROPS = {"text"}


def resolve_times(timeline: list[Any]) -> list[tuple[float, float]]:
    """Return (start, end) in seconds for each action.

    Rules (deliberately simple so a model can predict them):
      * `at` given          -> starts at that absolute time
      * `with_previous`     -> starts when the previous action started
      * otherwise           -> starts once everything before it has finished
    """
    out: list[tuple[float, float]] = []
    frontier = 0.0  # end of everything so far
    prev_start = 0.0
    for a in timeline:
        if a.at is not None:
            start = a.at
        elif a.with_previous and out:
            start = prev_start
        else:
            start = frontier
        end = start + a.duration
        out.append((start, end))
        prev_start = start
        frontier = max(frontier, end)
    return out


def scene_duration(scene: S.Scene) -> float:
    times = resolve_times(scene.timeline)
    return max((e for _, e in times), default=0.0)


# --------------------------------------------------------------------- geometry


def graph_points(g: S.Graph, axes: S.Axes, expr: str | None = None) -> list[list[float]]:
    """Sample y = f(x) and map it into world coordinates on the given axes."""
    f = compile_expr(expr or g.expr)
    x0, x1 = g.domain or axes.x_range
    (ax0, ax1), (ay0, ay1) = axes.x_range, axes.y_range
    left, bottom = axes.x - axes.width / 2, axes.y - axes.height / 2
    sx, sy = axes.width / (ax1 - ax0), axes.height / (ay1 - ay0)
    # Values far outside the axes are clamped (the player clips to the axes box).
    lo, hi = ay0 - 2 * (ay1 - ay0), ay1 + 2 * (ay1 - ay0)
    pts: list[list[float]] = []
    last = 0.0
    for i in range(g.samples):
        xv = x0 + (x1 - x0) * i / (g.samples - 1)
        yv = f(xv)
        if not math.isfinite(yv):
            yv = last
        yv = min(max(yv, lo), hi)
        last = yv
        pts.append([round(left + (xv - ax0) * sx, 4), round(bottom + (yv - ay0) * sy, 4)])
    return pts


def axes_geometry(a: S.Axes) -> dict:
    """Axis lines and tick marks, in world coordinates."""
    (x0, x1), (y0, y1) = a.x_range, a.y_range
    left, bottom = a.x - a.width / 2, a.y - a.height / 2
    sx, sy = a.width / (x1 - x0), a.height / (y1 - y0)

    def wx(v: float) -> float:
        return left + (v - x0) * sx

    def wy(v: float) -> float:
        return bottom + (v - y0) * sy

    # The x axis sits at y=0 if that is in range, otherwise along the bottom.
    y_axis_at = 0 if x0 <= 0 <= x1 else x0
    x_axis_at = 0 if y0 <= 0 <= y1 else y0
    lines = [
        [wx(x0), wy(x_axis_at), wx(x1), wy(x_axis_at)],
        [wx(y_axis_at), wy(y0), wx(y_axis_at), wy(y1)],
    ]
    t = 0.08
    k = math.ceil(x0 / a.x_step)
    while k * a.x_step <= x1 + 1e-9:
        v = k * a.x_step
        if abs(v - y_axis_at) > 1e-9:
            lines.append([wx(v), wy(x_axis_at) - t, wx(v), wy(x_axis_at) + t])
        k += 1
    k = math.ceil(y0 / a.y_step)
    while k * a.y_step <= y1 + 1e-9:
        v = k * a.y_step
        if abs(v - x_axis_at) > 1e-9:
            lines.append([wx(y_axis_at) - t, wy(v), wx(y_axis_at) + t, wy(v)])
        k += 1
    return {
        "lines": [[round(c, 4) for c in ln] for ln in lines],
        "box": [left, bottom, a.width, a.height],
    }


# ---------------------------------------------------------------------- compile


def _initial_state(o: Any) -> dict:
    st: dict[str, Any] = {
        "x": o.x, "y": o.y, "scale": o.scale, "rotation": o.rotation,
        "opacity": o.opacity if o.visible else 0.0,
        "draw": 1.0,
    }
    for p in ANIMATABLE[o.type] - COMMON_PROPS:
        if p == "expr":
            continue
        v = getattr(o, p)
        st[p] = list(v) if isinstance(v, tuple) else v
    return st


def compile_scene(scene: S.Scene) -> dict:
    objs = {o.id: o for o in scene.objects}
    axes_by_id = {o.id: o for o in scene.objects if o.type == "axes"}
    state = {oid: _initial_state(o) for oid, o in objs.items()}
    shown = {oid: o.opacity for oid, o in objs.items()}  # opacity to fade back in to
    segs: dict[str, list] = {oid: [] for oid in objs}
    points: dict[str, list] = {}

    for o in scene.objects:
        if o.type == "graph":
            points[o.id] = graph_points(o, axes_by_id[o.axes])
            state[o.id]["points"] = points[o.id]

    def seg(oid: str, prop: str, t0: float, t1: float, b: Any, ease: str) -> None:
        a = state[oid].get(prop)
        segs[oid].append([prop, round(t0, 4), round(t1, 4), a, b, ease])
        state[oid][prop] = b

    times = resolve_times(scene.timeline)
    order = sorted(range(len(scene.timeline)), key=lambda i: times[i][0])

    for i in order:
        act = scene.timeline[i]
        t0, t1 = times[i]
        if act.action == "wait":
            continue
        oid, ease = act.target, act.ease
        o = objs[oid]
        if act.action == "create":
            if o.type == "text":
                seg(oid, "opacity", t0, t0, 0.0, "linear")
                seg(oid, "opacity", t0, t1, shown[oid], ease)
            else:
                seg(oid, "opacity", t0, t0, shown[oid], "linear")
                seg(oid, "draw", t0, t0, 0.0, "linear")
                seg(oid, "draw", t0, t1, 1.0, ease)
        elif act.action == "fade_in":
            seg(oid, "draw", t0, t0, 1.0, "linear")
            seg(oid, "opacity", t0, t1, shown[oid], ease)
        elif act.action == "fade_out":
            seg(oid, "opacity", t0, t1, 0.0, ease)
        elif act.action == "move":
            seg(oid, "x", t0, t1, act.to[0], ease)
            seg(oid, "y", t0, t1, act.to[1], ease)
        elif act.action == "highlight":
            s = state[oid]["scale"]
            mid = (t0 + t1) / 2
            seg(oid, "scale", t0, mid, s * act.factor, "out")
            seg(oid, "scale", mid, t1, s, "in")
        elif act.action == "transform":
            for prop, val in act.to.items():
                if prop == "expr":
                    new_pts = graph_points(o, axes_by_id[o.axes], str(val))
                    seg(oid, "points", t0, t1, new_pts, ease)
                elif prop in SNAP_PROPS:
                    seg(oid, prop, t0, t0, val, "linear")
                else:
                    if prop == "opacity":
                        shown[oid] = float(val)
                    seg(oid, prop, t0, t1, list(val) if isinstance(val, (list, tuple)) else val, ease)

    out_objects = []
    for o in sorted(scene.objects, key=lambda o: o.z):
        init = _initial_state(o)
        if o.type == "graph":
            init["points"] = points[o.id]
        # The player draws each object's geometry, then translates it by
        # (x, y) - origin and rotates/scales it around `pivot`.
        #   circle/rect/dot/text: geometry centred on 0, origin 0, pivot 0
        #   line/arrow/graph:     geometry in absolute coords, x/y are offsets
        #   axes:                 geometry in absolute coords, x/y is the centre
        geom: dict[str, Any] = {}
        pivot = [0.0, 0.0]
        origin = [0.0, 0.0]
        if o.type in ("line", "arrow"):
            pivot = [(o.start[0] + o.end[0]) / 2, (o.start[1] + o.end[1]) / 2]
            if o.type == "arrow":
                geom["head"] = o.head
        elif o.type == "text":
            geom.update(weight=o.weight, font=o.font)
        elif o.type == "axes":
            geom.update(axes_geometry(o))
            pivot = origin = [o.x, o.y]
        elif o.type == "graph":
            ax = axes_by_id[o.axes]
            geom["clip"] = axes_geometry(ax)["box"]
            pivot = [ax.x, ax.y]
        geom["origin"] = origin
        out_objects.append({
            "id": o.id, "type": o.type, "geom": geom, "pivot": pivot,
            "init": init, "segs": segs[o.id],
        })

    return {
        "renderer": RENDERER_VERSION,
        "title": scene.meta.title,
        "canvas": scene.canvas.model_dump(),
        "duration": round(scene_duration(scene), 4),
        "objects": out_objects,
    }
