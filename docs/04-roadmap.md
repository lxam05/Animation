# 04 — Roadmap

Each phase is a self-contained milestone, and each one leans on a new part of Atlas.

## Phase 0 — Foundations ✅ (done in the first session)

- [x] Language v0.1: 8 object types, 7 actions, Pydantic schema
- [x] Validator with model-friendly errors, suggestions and aliases
- [x] Compiler and self-contained HTML/SVG player
- [x] 6 example scenes
- [~] Atlas layer (written, not yet run or reviewed): collections, `$jsonSchema` validator, indexes, TTL cache, vector index
- [x] Generate → validate → repair loop, with every attempt logged to Atlas
- [x] CLI and 24 tests (offline; no database needed)
- [ ] **Atlas layer reviewed with Liam and run against his cluster** (not done yet)

## Phase 1 — Make it real (next)

- [ ] On Liam's existing Atlas account: review each step, then run `atlas-setup`, `seed` and `search` (docs/02 §7)
- [ ] First real `motif generate` runs, then look at `generations` in Compass
- [ ] Write 15–25 more example scenes. The library is the model's memory, and
      variety matters more than polish. Ideas: Pythagoras, unit circle, derivative
      as tangent slope, sorting bars, a simple network diagram, a countdown.
- [ ] `motif eval`: a fixed list of ~20 prompts, run them all, and record the success
      rate in a new `eval_runs` collection. Run it before and after every change.

## Phase 2 — The language grows (driven by data)

Use `motif stats` and the eval set to decide what to add. Likely candidates:

- [ ] `group` objects (move several things together)
- [ ] `label` on axes (tick numbers)
- [ ] LaTeX via KaTeX in the player (`"type": "math", "tex": "e^{i\\pi}+1=0"`)
- [ ] Shape morphing (`morph` from one object into another)
- [ ] `trace` (a dot leaves a path), `follow` (move along a graph)
- [ ] Camera: `zoom`, `pan`
- [ ] Bump to v0.2 with a migration function (MongoDB can migrate stored scenes with an `updateMany` aggregation-pipeline update)

## Phase 3 — Video and a render worker

- [ ] `motif export scene.json -o scene.mp4`: Playwright steps `window.motif.seek(t)`
      frame by frame, then ffmpeg encodes the video
- [ ] Render worker that uses a **change stream** on `scenes` to render new scenes automatically
- [ ] Store videos outside the document (object storage or GridFS) and keep the URL in `renders`

## Phase 4 — A web app

- [ ] Small FastAPI backend plus a web page: prompt box, live player, JSON editor
      with inline validation errors, and "remix" (new scene with `parent_id`)
- [ ] Gallery with search: Atlas Search (keyword) plus Vector Search (meaning)
- [ ] Thumbs up/down on results, stored on the scene; well-rated generated
      scenes get promoted to `is_example: true`, so **the library improves itself**
- [ ] Atlas Charts dashboard on `generations`

## Stretch ideas

- Expose Motif as an **MCP server** so any AI assistant can make animations
- A fine-tuning dataset exported from successful `generations`
- Compile Motif to Manim Python for print-quality renders
