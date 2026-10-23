"""Prompts that teach the model the Motif language.

The model sees three things:
  1. LANGUAGE_GUIDE - a compact, example-driven description of the format
  2. a few retrieved example scenes (from Atlas Vector Search) that are close
     to what the user asked for
  3. on a repair turn, the validator's error list
"""

from __future__ import annotations

import json

LANGUAGE_GUIDE = """\
You write animations in Motif, a JSON scene language for motion graphics.
Reply with ONE JSON object and nothing else.

## Shape of a scene
{"motif": "0.1",
 "meta": {"title": "...", "description": "one sentence", "tags": ["..."]},
 "canvas": {"background": "#0f1117"},            (optional)
 "objects": [ ... ],
 "timeline": [ ... ]}

## Coordinates
World units, origin at the centre, y points UP. Visible area: x from -8 to 8, y from -4.5 to 4.5.

## Objects (every object needs a unique "id" and a "type")
Common optional fields: x, y, opacity (0-1), scale, rotation (degrees, CCW), z (draw order), visible (default false).
Objects are HIDDEN until a create or fade_in action, unless "visible": true.
- circle: r, fill, stroke, stroke_width
- rect:   w, h, corner (corner radius), fill, stroke, stroke_width       (x, y = centre)
- dot:    r, fill
- line:   start [x,y], end [x,y], stroke, stroke_width                  (x, y = offset)
- arrow:  start, end, head (arrowhead length), stroke, stroke_width
- text:   text, size (font size in world units, ~0.5), fill, weight ("normal"|"bold"), font ("sans"|"serif"|"mono")
- axes:   width, height, x_range [min,max], y_range [min,max], x_step, y_step, stroke   (x, y = centre of the box)
- graph:  axes (id of an axes object), expr (in x, e.g. "sin(2*x)/2"), domain [min,max], stroke
  expr may use x, pi, e, + - * / ** and sin cos tan exp log sqrt abs min max.
Colours are 6-digit hex strings: "#58c4dd" blue, "#83c167" green, "#fc6255" red, "#ffff00" yellow, "#ffffff" white.

## Actions (the timeline)
Every action has: action, duration (seconds), ease ("smooth" default, "linear", "in", "out", "in_out").
Timing: an action starts after EVERYTHING before it has finished, unless
  "with_previous": true  -> starts at the same time as the previous action
  "at": 2.5              -> starts at an absolute time
- create     {target}           draw the object in (strokes trace on, fill appears)
- fade_in    {target}
- fade_out   {target}
- move       {target, to: [x, y]}
- transform  {target, to: {prop: value, ...}}   animate properties, e.g. {"r": 2, "fill": "#ff0000"}.
             On a graph, {"expr": "cos(x)"} morphs the curve. On text, {"text": "..."} swaps the words.
- highlight  {target, factor}   quick pulse (scale up and back)
- wait       {duration}

## Rules
- Only use the fields listed above. Unknown fields are errors.
- Never animate the same property of the same object twice at the same time.
- Keep important things inside the visible area and leave margins around text.
- Prefer clear, paced storytelling: introduce things one at a time, then animate them.
"""


def system_prompt() -> str:
    return LANGUAGE_GUIDE


def examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["Here are working example scenes similar to the request. Match their style and correctness.\n"]
    for ex in examples:
        parts.append(f"### Example: {ex['title']}\n```json\n{json.dumps(ex['scene'], separators=(',', ':'))}\n```\n")
    return "\n".join(parts)


def user_prompt(request: str, examples: list[dict]) -> str:
    return f"{examples_block(examples)}\nWrite a Motif scene for this request:\n{request}"


def repair_prompt(errors_text: str) -> str:
    return (
        "That scene has problems. Fix ALL of the errors below (warnings are optional) "
        "and reply with the complete corrected JSON only.\n\n" + errors_text
    )
