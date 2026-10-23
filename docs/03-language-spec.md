# 03 — Motif language spec (v0.1)

The source of truth is [`motif/schema.py`](../motif/schema.py); this page explains it.
`python -m motif schema` prints the machine-readable JSON Schema.

## A whole scene

```json
{
  "motif": "0.1",
  "meta": { "title": "Hello, circle", "description": "One sentence about what happens.", "tags": ["basics"] },
  "canvas": { "background": "#0f1117", "fps": 60 },
  "objects": [
    { "id": "c", "type": "circle", "r": 1.2, "fill": "#58c4dd" },
    { "id": "label", "type": "text", "text": "Hello", "y": -2.6 }
  ],
  "timeline": [
    { "action": "create",  "target": "c", "duration": 1.2 },
    { "action": "fade_in", "target": "label", "with_previous": true },
    { "action": "move",    "target": "c", "to": [3, 0] }
  ]
}
```

`canvas` and `motif` are optional. `meta.description` matters: it's what Vector Search matches against.

## Coordinates

- World units, **origin at the centre**, **y points up**.
- Visible area: x from **-8 to 8**, y from **-4.5 to 4.5** (16:9).
- Rotation is in **degrees, counter-clockwise**.
- Colours are 6-digit hex: `#58c4dd` blue, `#83c167` green, `#fc6255` red,
  `#ffff00` yellow, `#ffffff` white (Manim's palette).

## Objects

Every object has `id` (unique, starting with a letter or underscore) and `type`.

**Common fields:** `x`, `y`, `opacity` (0–1, the opacity when shown), `scale`,
`rotation`, `z` (draw order), and `visible` (default **false**).

> Objects are **hidden until a `create` or `fade_in`**, like adding mobjects in
> Manim. Use `"visible": true` for things present from the first frame
> (a background grid, for example).

| type | fields | what x, y mean |
|---|---|---|
| `circle` | `r`, `fill`, `stroke`, `stroke_width` | centre |
| `rect` | `w`, `h`, `corner`, `fill`, `stroke`, `stroke_width` | centre |
| `dot` | `r` (0.08), `fill` | centre |
| `line` | `start [x,y]`, `end [x,y]`, `stroke`, `stroke_width` | offset added to start/end |
| `arrow` | as line, plus `head` (arrowhead length) | offset |
| `text` | `text`, `size` (0.5), `fill`, `weight` (normal/bold), `font` (sans/serif/mono) | centre |
| `axes` | `width`, `height`, `x_range`, `y_range`, `x_step`, `y_step`, `stroke` | centre of the axes box |
| `graph` | `axes` (an axes id), `expr`, `domain`, `samples`, `stroke`, `stroke_width` | offset |

### Graph expressions

A function of `x`: `"sin(2*x) / 2"`, `"x**2 - 1"`, `"exp(-x**2)"`.
`^` is accepted as power. Allowed: `+ - * / ** %`, `pi e tau`,
`sin cos tan asin acos atan sinh cosh tanh exp log sqrt abs floor ceil min max`.
Values outside the axes' `y_range` are clipped to the axes box.

## Actions (the timeline)

Every action has `action`, `duration` (seconds) and `ease`
(`smooth` default, `linear`, `in`, `out`, `in_out`).

| action | fields | effect |
|---|---|---|
| `create` | `target` | strokes trace on, then fill appears (text fades in) |
| `fade_in` | `target` | opacity 0 → the object's opacity (default 0.5 s) |
| `fade_out` | `target` | opacity → 0 (default 0.5 s) |
| `move` | `target`, `to [x,y]` | animate x and y |
| `transform` | `target`, `to {prop: value}` | animate any listed property (see below) |
| `highlight` | `target`, `factor` (1.2) | scale pulse out and back (0.6 s) |
| `wait` | — | nothing; just takes time |

### What `transform` can change

| type | properties |
|---|---|
| all | `x y opacity scale rotation` |
| circle | `r fill stroke stroke_width` |
| rect | `w h corner fill stroke stroke_width` |
| dot | `r fill` |
| line, arrow | `start end stroke stroke_width` |
| text | `fill size text` (text swaps instantly) |
| axes | `stroke stroke_width` |
| graph | `expr stroke stroke_width` (changing `expr` **morphs the curve**) |

### Timing rules

1. By default an action **starts after everything before it has finished**.
2. `"with_previous": true` starts it **at the same time as the previous action**.
3. `"at": 2.5` starts it at an absolute time.

So you can always work out start times by reading top to bottom. The validator
rejects two actions that animate **the same property of the same object at the
same time**, such as two overlapping `move`s.

## Validation messages

Every issue is `level path: message`, with a suggested fix where one exists:

```
error   objects[0].radius: unknown field 'radius'. Did you mean 'r'?
error   timeline[3].target: unknown object 'circel'. Did you mean 'circle1'?
error   timeline[5]: overlaps timeline[4] (2-3s): both animate 'x' of 'dot'. Remove with_previous/at or change the timing.
warning timeline[1]: 'c' is not visible yet at t=0s; add a create or fade_in before this
```

Errors come in two rounds: structural errors (wrong fields and types) are
reported first, and semantic checks (ids, timing, expressions) run once the
structure is valid. Warnings don't block rendering.

## Rendering

`compiler.py` simulates the timeline and produces per-object segments
(`property, t0, t1, from, to, ease`). `render.py` embeds them in one HTML file
with an SVG player (`player.js`): play/pause, scrub, space bar, looping.
`window.motif.seek(t)` lets a headless browser capture exact frames for video export.
