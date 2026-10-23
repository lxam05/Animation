# 01 — The idea

## The problem

Grant Sanderson (3Blue1Brown) built **Manim**, a Python library, to make his maths
animations. It's brilliant, and AI models can write Manim code, but it goes wrong
in predictable ways:

- **It's a full programming language.** Python lets you write anything, so a model
  can write anything, including code that crashes 40 lines in.
- **Errors show up late.** You only find out a coordinate was wrong or a method
  doesn't exist after you render. Rendering is slow.
- **Errors are written for humans.** A Python traceback doesn't tell a model
  *what to change*.
- **The API is huge.** Hundreds of classes and versions that changed over time.
  Models mix them up.

## The bet

Make a **small, declarative language designed for models to write**, not humans.

| Manim (imperative code) | Motif (declarative data) |
|---|---|
| `circle = Circle(radius=1)` then `self.play(Create(circle))` | `{"id": "c", "type": "circle", "r": 1}` plus `{"action": "create", "target": "c"}` |
| Errors at render time | Validated **before** rendering, in milliseconds |
| Python tracebacks | `objects[0].radius: unknown field 'radius'. Did you mean 'r'?` |
| Unlimited surface area | 8 object types, 7 actions |
| Pixels and frames | World units (16 x 9) and seconds |

The design principles, roughly in order of importance:

1. **Every mistake gets a fixable error message.** The validator is the heart of
   the project. It names the exact path, says what's wrong, and suggests the fix.
   The model gets those messages back and tries again (the *repair loop*).
2. **Small vocabulary.** Fewer things to get wrong. New features have to earn
   their place.
3. **Unknown keys are errors, not ignored.** If a model writes `"color"` instead
   of `"fill"`, silently ignoring it produces a wrong animation with no error.
   Rejecting it lets the repair loop catch it.
4. **Predictable timing.** An action starts after everything before it finishes,
   unless it says `with_previous` or `at`. A model can calculate any start time
   by reading top to bottom.
5. **Human-friendly numbers.** The origin is the centre, y goes up, and the screen
   is 16 x 9 units, so "slightly up and to the right" is `[2, 1]`, not `[1140, 280]`.
6. **It's just JSON.** That means it can be stored, queried, diffed, versioned,
   embedded and searched. That's where MongoDB comes in.

## Why MongoDB is a natural fit (not a bolted-on database)

A Motif scene **is** a document: nested objects, arrays of actions, optional
fields that vary by type. In a relational database you'd either shred it into
five tables (objects, actions, properties...) or store it as an opaque blob.
In MongoDB it's stored as-is **and** stays queryable:

```js
// every scene that morphs a graph
db.scenes.find({ "scene.timeline": { $elemMatch: { action: "transform", "to.expr": { $exists: true } } } })
```

Then Atlas adds the parts that make the AI loop better over time:

- **Vector Search** gives the model the most relevant working examples for
  each request (few-shot retrieval, also called RAG).
- **The generations log** records every attempt and error, and **aggregation
  pipelines** show which mistakes are most common, which tells you what to fix
  in the prompt or the language.
- **TTL indexes** keep a render cache that cleans itself up.
- **Change streams** (roadmap) can trigger a render worker whenever a new scene lands.

The full walkthrough is in [02-atlas-and-mongodb.md](02-atlas-and-mongodb.md).

## The loop

```
 "show a sine wave turning into a cosine"
          │
          ▼
 ┌─────────────────────┐   $vectorSearch    ┌──────────────────┐
 │ embed the request   │ ─────────────────► │ Atlas: scenes    │
 └─────────────────────┘  3 closest scenes  └──────────────────┘
          │
          ▼
 ┌─────────────────────┐
 │ model writes JSON   │ ◄──────────────┐
 └─────────────────────┘                │ errors as text
          │                             │
          ▼                             │
 ┌─────────────────────┐   not ok       │
 │ validator.py        │ ───────────────┘   (up to 3 repairs)
 └─────────────────────┘
          │ ok
          ▼
 save scene + log generation (Atlas) ──► compile ──► HTML player
```

## What's deliberately *not* in v0.1

- LaTeX maths typesetting (Manim's killer feature; see the roadmap)
- Groups and nested objects
- Shape-to-shape morphing (only graph-to-graph and property changes)
- Video export (the player has a hook for it; see the roadmap)
- Camera moves

Leaving these out keeps the first version small enough to finish and learn from.
