# Motif

A small motion-graphics language that AI models can write reliably, inspired by
3Blue1Brown's Manim and backed by **MongoDB Atlas**. It's a personal project for
learning MongoDB properly.

```json
{ "meta": {"title": "Sine becomes cosine"},
  "objects": [ {"id": "ax", "type": "axes"}, {"id": "f", "type": "graph", "axes": "ax", "expr": "sin(x)"} ],
  "timeline": [ {"action": "create", "target": "ax"}, {"action": "create", "target": "f"},
                {"action": "transform", "target": "f", "to": {"expr": "cos(x)"}} ] }
```

## Read these

1. [docs/01-the-idea.md](docs/01-the-idea.md): why a language for AI, and why MongoDB fits
2. [docs/02-atlas-and-mongodb.md](docs/02-atlas-and-mongodb.md): **the MongoDB study guide** (collections, indexes, Vector Search, pipelines)
3. [docs/03-language-spec.md](docs/03-language-spec.md): the language
4. [docs/04-roadmap.md](docs/04-roadmap.md): what's next
5. [CLAUDE.md](CLAUDE.md): handoff notes and working agreement for AI sessions

## Try it (no database needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest                                   # 24 tests
motif validate examples/vector-addition.json
motif render examples/sine-to-cosine.json --open   # opens the player in your browser
```

## With Atlas

Not run yet; we'll go through it together. See docs/02, section 7. Copy
`.env.example` to `.env`, fill it in, then `motif atlas-setup`, `motif seed`,
`motif search "..."` and `motif generate "..."`.

## Layout

```
motif/        schema · validator · compiler · render + player.js · db (Atlas) · embeddings · prompt · generate · cli
examples/     6 hand-written scenes (the AI's reference library)
tests/        offline tests
docs/         the idea, the Atlas guide, the spec, the roadmap
```
