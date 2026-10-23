# Handoff / working agreement for Claude sessions

Read this first. It is the source of truth for how to work on this repo.

## Who this is for

Liam's **personal learning project**. The goal is for Liam to **learn MongoDB and
Atlas deeply**, not just to have working code. Treat every session as pair
programming with a teacher's hat on.

## Working agreement (updated session 2: Liam is brand new to MongoDB)

1. **Claude makes the technical and data-model decisions**, and always explains
   them in plain, beginner-friendly language: what it is, why this choice, what
   the alternative was. Assume no prior database knowledge. Record decisions in
   `docs/00-mongodb-from-zero.md` §8.
2. **Never create Atlas accounts, projects, clusters, users, or API keys.** Liam
   has an account. Anything in the Atlas website is done by Liam, with clear
   step-by-step instructions saying what each thing is.
3. **Narrate as you go.** Before running or asking Liam to run a command that
   touches his cluster, say in one or two sentences what it will do in MongoDB
   terms and what he should expect to see (e.g. in Atlas Data Explorer).
   Never write to or delete from his cluster without his OK for that step.
4. Point Liam to where he can *see* each result (Data Explorer, Compass), so
   he builds a mental picture, not just working code.
5. Keep `docs/00-mongodb-from-zero.md` (beginner primer) and
   `docs/02-atlas-and-mongodb.md` (deeper guide) up to date with every MongoDB
   concept the project uses.
6. Never commit secrets. `.env` is git-ignored; `.env.example` holds placeholders.

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

Session 2: Liam asked Claude to make the decisions (recorded in docs/00 §8) and
explain everything. Atlas setup is done and **`db.py`/`embeddings.py` now run
for real**: `motif ping`, `atlas-setup`, `seed` (6 examples with 1024-dim
embeddings) and `search` all work against Liam's M0 cluster.

- Voyage free tier (no payment method) = **3 requests/minute**. `seed` now embeds
  all scenes in one batched request; more than 3 quick searches in a row get a 429.
- Run commands with `.venv/bin/motif` (no global `python` on this machine).
- `search -k` defaults to 5.

**Next step: `motif generate` (needs `ANTHROPIC_API_KEY`), then `motif stats`,
showing Liam the `generations` documents in Data Explorer.**

## Conventions

- Python ≥3.10, Pydantic v2, PyMongo ≥4.7, no other heavy dependencies.
- Unknown fields in scenes are errors (`extra="forbid"`). Keep it that way.
- Any change to the language must update `schema.py`, `validator.py`,
  `compiler.py` (`ANIMATABLE`), `prompt.py` (`LANGUAGE_GUIDE`),
  `docs/03-language-spec.md`, and add a test.
- Examples in `examples/` must validate with **no warnings** (enforced by a test).
- Roadmap: `docs/04-roadmap.md`.
