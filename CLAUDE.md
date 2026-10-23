# Handoff / working agreement for Claude sessions

Read this first. It is the source of truth for how to work on this repo.

## Who this is for

Liam's **personal learning project**. The goal is for Liam to **learn MongoDB and
Atlas deeply**, not just to have working code. Treat every session as pair
programming with a teacher's hat on.

## Working agreement (non-negotiable)

1. **Never create Atlas accounts, projects, clusters, users, or API keys.** Liam
   has an Atlas account and does all Atlas-side actions himself. You explain what
   to click or run and why.
2. **Explain before you implement anything MongoDB-related.** For any new
   collection, field, index, query, pipeline, or Atlas feature, first explain:
   what it is, why we'd use it, the alternatives, and the trade-off. Then wait
   for Liam's go-ahead or his changes.
3. **Liam makes the data-model decisions.** Propose options; don't silently pick one.
4. **Prefer Liam writing MongoDB code**, with you reviewing, hinting, and
   explaining errors, unless he asks you to write it.
5. **Never run commands that write to or delete from his Atlas cluster** without
   explicit approval for that specific command.
6. Keep `docs/02-atlas-and-mongodb.md` up to date. It is Liam's study guide.
   Every MongoDB concept the project uses should be explained there.
7. Never commit secrets. `.env` is git-ignored; `.env.example` holds placeholders.

## What the project is

**Motif**: a small declarative JSON language for motion graphics, designed for AI
models to write (inspired by 3Blue1Brown's Manim). Pipeline: request → Atlas
Vector Search finds similar example scenes → LLM writes a scene → validator
returns fixable errors → repair loop → compile → self-contained HTML/SVG player.
See `docs/01-the-idea.md`.

## Current state (end of session 1, 2026-10-23)

Done and tested **offline** (24 tests pass, `python -m pytest`):
- `motif/schema.py`: language v0.1 (8 object types, 7 actions)
- `motif/validator.py`: model-friendly errors with suggestions
- `motif/compiler.py`, `render.py`, `player.js`: HTML player (visually checked
  in headless Chromium for all 6 examples)
- `motif/generate.py`: repair loop (tested with a fake LLM)
- `motif/cli.py`: validate, render, schema, atlas-setup, seed, search, generate, stats

**Written but NEVER run against a real MongoDB** (the dev sandbox couldn't reach
Docker Hub or Atlas):
- `motif/db.py`: collections, `$jsonSchema` validator, indexes, TTL, vector
  index, `$vectorSearch`, aggregation pipelines
- `motif/embeddings.py`: Voyage AI embeddings via `https://ai.mongodb.com/v1`

Liam paused before we touched Atlas so that he could review the MongoDB design
and take part in it. **Next session: walk through `db.py` with him section by
section (docs/02 is the guide), and let him decide what to keep, change, or
rewrite himself before anything runs against his cluster.**

## Conventions

- Python ≥3.10, Pydantic v2, PyMongo ≥4.7, no other heavy dependencies.
- Unknown fields in scenes are errors (`extra="forbid"`). Keep it that way.
- Any change to the language must update `schema.py`, `validator.py`,
  `compiler.py` (`ANIMATABLE`), `prompt.py` (`LANGUAGE_GUIDE`),
  `docs/03-language-spec.md`, and add a test.
- Examples in `examples/` must validate with **no warnings** (enforced by a test).
- Roadmap: `docs/04-roadmap.md`.
