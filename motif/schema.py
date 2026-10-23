"""The Motif scene format, defined as Pydantic models.

A Motif scene is one JSON document with three parts:

    canvas    -> how big the stage is, background colour, frame rate
    objects   -> everything that can appear on screen (circles, text, axes, graphs...)
    timeline  -> an ordered list of actions (create, move, transform, fade...)

The models here are the single source of truth for the format. They are used to:
  * parse and type-check a scene (see validator.py for the semantic checks)
  * export a JSON Schema that is shown to the AI model
  * keep the Python compiler honest about which fields exist

Coordinates are "world units": the origin is the centre of the screen, x goes right,
y goes UP (like maths, not like screen pixels). The visible area is 16 x 9 units,
so x runs from -8 to 8 and y from -4.5 to 4.5. Small numbers are much easier for a
language model to reason about than pixels.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

MOTIF_VERSION = "0.1"

Color = str  # "#rrggbb" hex string; checked in validator.py
Point = tuple[float, float]
Ease = Literal["linear", "smooth", "in", "out", "in_out"]


class _Strict(BaseModel):
    # Unknown keys are an error. Models love to invent fields ("color" instead of
    # "fill", "position" instead of x/y); rejecting them loudly lets the repair
    # loop fix the mistake instead of silently ignoring it.
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- canvas


class Canvas(_Strict):
    background: Color = "#0f1117"
    fps: int = Field(60, ge=1, le=120)
    # Width/height in world units are fixed at 16 x 9 in v0.1 (only aspect matters
    # for the browser player). Kept here so the format can grow.
    width: float = 16
    height: float = 9


class Meta(_Strict):
    title: str
    description: str = ""
    tags: list[str] = []


# -------------------------------------------------------------------------- objects


class _ObjectBase(_Strict):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_\-]*$")
    x: float = 0
    y: float = 0
    opacity: float = Field(1, ge=0, le=1)
    scale: float = Field(1, gt=0)
    rotation: float = 0  # degrees, counter-clockwise
    z: int = 0  # draw order: higher is on top
    # Objects are hidden until a `create` or `fade_in` action, like adding them to
    # the scene in Manim. Set visible=true to have something on screen from t=0.
    visible: bool = False


class Circle(_ObjectBase):
    type: Literal["circle"]
    r: float = Field(1, gt=0)
    fill: Optional[Color] = None
    stroke: Optional[Color] = "#58c4dd"
    stroke_width: float = 0.05


class Rect(_ObjectBase):
    type: Literal["rect"]
    w: float = Field(2, gt=0)
    h: float = Field(1, gt=0)
    corner: float = Field(0, ge=0)
    fill: Optional[Color] = None
    stroke: Optional[Color] = "#83c167"
    stroke_width: float = 0.05


class Dot(_ObjectBase):
    type: Literal["dot"]
    r: float = Field(0.08, gt=0)
    fill: Optional[Color] = "#ffffff"
    stroke: Optional[Color] = None
    stroke_width: float = 0.0


class Line(_ObjectBase):
    """A straight line. `start` and `end` are absolute world coordinates;
    x/y act as an extra offset, so `move` on a line slides the whole line."""

    type: Literal["line"]
    start: Point = (0, 0)
    end: Point = (1, 0)
    stroke: Optional[Color] = "#ffffff"
    stroke_width: float = 0.05


class Arrow(_ObjectBase):
    type: Literal["arrow"]
    start: Point = (0, 0)
    end: Point = (1, 0)
    stroke: Optional[Color] = "#ffffff"
    stroke_width: float = 0.05
    head: float = Field(0.25, gt=0)  # arrowhead length in world units


class Text(_ObjectBase):
    type: Literal["text"]
    text: str
    size: float = Field(0.5, gt=0)  # font size in world units
    fill: Optional[Color] = "#ffffff"
    weight: Literal["normal", "bold"] = "normal"
    font: Literal["sans", "serif", "mono"] = "sans"


class Axes(_ObjectBase):
    """A pair of axes. (x, y) is the centre of the axes box on screen."""

    type: Literal["axes"]
    width: float = Field(10, gt=0)
    height: float = Field(6, gt=0)
    x_range: Point = (-5, 5)
    y_range: Point = (-3, 3)
    x_step: float = Field(1, gt=0)
    y_step: float = Field(1, gt=0)
    stroke: Optional[Color] = "#888888"
    stroke_width: float = 0.03


class Graph(_ObjectBase):
    """y = expr(x), plotted on an Axes object. Expressions use `x` plus
    sin cos tan exp log sqrt abs, pi, e and + - * / ** (e.g. "sin(2*x) / 2")."""

    type: Literal["graph"]
    axes: str
    expr: str
    domain: Optional[Point] = None  # defaults to the axes x_range
    samples: int = Field(200, ge=10, le=2000)
    stroke: Optional[Color] = "#fc6255"
    stroke_width: float = 0.06


SceneObject = Annotated[
    Union[Circle, Rect, Dot, Line, Arrow, Text, Axes, Graph],
    Field(discriminator="type"),
]

OBJECT_TYPES = ["circle", "rect", "dot", "line", "arrow", "text", "axes", "graph"]


# -------------------------------------------------------------------------- actions


class _ActionBase(_Strict):
    # Timing: by default an action starts when the previous one ends.
    #   at=<seconds>        -> start at an absolute time instead
    #   with_previous=true  -> start at the same time as the previous action
    at: Optional[float] = Field(None, ge=0)
    with_previous: bool = False
    duration: float = Field(1, ge=0)
    ease: Ease = "smooth"


class _Targeted(_ActionBase):
    target: str


class Create(_Targeted):
    """Draw the object in (stroke traces on, then fill appears)."""

    action: Literal["create"]


class FadeIn(_Targeted):
    action: Literal["fade_in"]
    duration: float = Field(0.5, ge=0)


class FadeOut(_Targeted):
    action: Literal["fade_out"]
    duration: float = Field(0.5, ge=0)


class Move(_Targeted):
    action: Literal["move"]
    to: Point


class Transform(_Targeted):
    """Animate any properties to new values, e.g.
    {"action": "transform", "target": "c1", "to": {"r": 2, "fill": "#ff0000"}}.
    On a graph, changing "expr" morphs one curve into the other."""

    action: Literal["transform"]
    to: dict[str, Union[float, str, Point]]


class Highlight(_Targeted):
    """A quick pulse to draw attention. Ends where it started."""

    action: Literal["highlight"]
    duration: float = Field(0.6, ge=0)
    factor: float = Field(1.2, gt=0)


class Wait(_ActionBase):
    action: Literal["wait"]


Action = Annotated[
    Union[Create, FadeIn, FadeOut, Move, Transform, Highlight, Wait],
    Field(discriminator="action"),
]

ACTION_TYPES = ["create", "fade_in", "fade_out", "move", "transform", "highlight", "wait"]


# ---------------------------------------------------------------------------- scene


class Scene(_Strict):
    motif: Literal["0.1"] = "0.1"
    meta: Meta
    canvas: Canvas = Canvas()
    objects: list[SceneObject]
    timeline: list[Action]


def json_schema() -> dict:
    """JSON Schema for the whole format (shown to the model, used in docs)."""
    return Scene.model_json_schema()
