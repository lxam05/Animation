# 02 — How Motif uses MongoDB Atlas

This is the "why" behind every database decision in the project, written to
teach the concepts as much as to document the code. All of it lives in
[`motif/db.py`](../motif/db.py).

---

## 1. Quick vocabulary

| Term | Meaning | SQL-ish equivalent |
|---|---|---|
| **Cluster** | The MongoDB deployment Atlas runs for you (the free one is called **M0**) | A database server |
| **Database** | A namespace for collections (ours is `motif`) | A database / schema |
| **Collection** | A group of documents | A table, without fixed columns |
| **Document** | One JSON-like (BSON) record, up to 16 MB, can nest objects and arrays | A row, but nested |
| **Index** | A data structure that makes a query fast | An index |
| **Aggregation pipeline** | A list of stages that transform documents step by step | `SELECT ... GROUP BY ...` and much more |
| **Atlas Search / Vector Search** | Search indexes run by a separate Atlas process (`mongot`) next to the database | Elasticsearch / a vector database, built in |

---

## 2. The three collections

### `scenes`: the library and everything generated

```js
{
  _id: ObjectId("..."),
  slug: "sine-to-cosine",          // only for hand-written examples; unique
  title: "Sine becomes cosine",
  description: "Axes are drawn, the graph of sin(x) ...",
  tags: ["maths", "graph", "trigonometry", "morph"],
  scene: { meta: {...}, objects: [...], timeline: [...] },   // the Motif scene, stored as-is
  stats: {                          // derived fields, computed on save
    object_types: ["axes", "graph", "text"],
    actions: ["create", "fade_in", "transform", "wait"],
    n_objects: 3,
    duration: 6.5
  },
  is_example: true,                 // part of the AI's reference library?
  source: "human",                  // "human" | "generated"
  parent_id: ObjectId("..."),       // optional: "this is a variation of that"
  content_hash: "9f2c...",          // sha256 of the scene, also the render-cache key
  embedding: [0.0123, -0.044, ...], // 1024 numbers, for Vector Search
  created_at: ISODate("...")
}
```

**Design decisions and why:**

- **Embed the scene, don't split it up.** The scene is always read and written as
  a whole, so it belongs in one document. This is MongoDB's core modelling rule:
  *data that is accessed together is stored together.*
- **Duplicate a few fields at the top level** (`title`, `tags`, `stats`). They
  already exist inside `scene`, but copying them up makes indexes and queries
  simpler. Denormalising for read patterns is normal and encouraged in MongoDB.
- **Examples and generated scenes share one collection**, separated by
  `is_example`. Vector Search can filter on that flag, so one index serves both
  "find me examples" and "find anything similar".
- **`stats` is computed, not authored.** It lets you answer questions like "how
  many scenes use graphs?" without digging into the nested timeline.
- **`parent_id` gives you lineage.** You can later build "remix this scene" and
  follow the family tree with `$graphLookup`.

### `generations`: the learning log

One document per AI request. **This is the most valuable data in the project.**

```js
{
  request: "show a sine wave turning into a cosine",
  model: "claude-sonnet-5-5",
  retrieved: [ { scene_id: ..., title: "Sine becomes cosine", score: 0.91 }, ... ],
  attempts: [
    { n: 0, output: {...}, errors: [ { level: "error", path: "objects[1].radius", message: "..." } ], warnings: [] },
    { n: 1, output: {...}, errors: [], warnings: [] }
  ],
  success: true,
  scene_id: ObjectId("..."),
  latency_ms: 8123,
  created_at: ISODate("...")
}
```

Why keep all this? Because it lets you **measure** whether a change to the
prompt, the examples, or the language itself makes the model better. `motif stats`
runs two aggregation pipelines over it (section 6).

`attempts` is an **array embedded in the document** because attempts never exist
without their generation, there are only ever a handful, and you always want
them together. If attempts could grow without limit, they'd go in their own
collection instead. That's the main way to decide between embedding and referencing.

### `renders`: a self-cleaning cache

```js
{ _id: "9f2c...sha256...", compiled: { ...player tracks... }, created_at: ISODate("...") }
```

- **`_id` is the content hash** of `renderer version + scene`. Identical scenes map
  to the same `_id`, so a lookup is one primary-key fetch, and changing the
  renderer version automatically invalidates old entries.
- **TTL index** on `created_at` with `expireAfterSeconds: 2592000` (30 days).
  A background job in MongoDB deletes expired documents, so there's no cleanup cron.
- **The 16 MB limit:** a document can't exceed 16 MB. Compiled scenes are small, but
  rendered *video* won't be. When we add video, the file goes to object storage
  (or GridFS) and the document keeps just its URL.

---

## 3. Schema validation: schemaless doesn't mean no rules

MongoDB doesn't force a schema, but it can **enforce** one per collection with
`$jsonSchema` (see `SCENES_VALIDATOR` in `db.py`). We use two layers:

| Layer | Where | Checks |
|---|---|---|
| Database validator | MongoDB, on every insert/update | The envelope: `title`, `scene`, `is_example`, `source`, `created_at` exist and have the right types |
| Motif validator | Python, `validator.py` | The full language: ids exist, expressions parse, timing doesn't conflict, and more |

The database is the last line of defence: even a buggy script can't insert a
scene with no title. The Python layer does what JSON Schema can't, like checking
that a `target` refers to a real object id.

---

## 4. Indexes

```python
scenes.create_index("slug", unique=True, sparse=True)
scenes.create_index([("is_example", 1), ("created_at", -1)])
scenes.create_index("tags")
scenes.create_index("stats.object_types")
generations.create_index([("created_at", -1)])
renders.create_index("created_at", expireAfterSeconds=30 * 24 * 3600)
```

- **unique + sparse on `slug`.** Example scenes have unique slugs; generated
  scenes have none. *Sparse* means documents without the field aren't indexed,
  so many slug-less documents don't clash.
- **Compound `(is_example, created_at desc)`** serves "latest examples" and
  "latest generated scenes" with one index. Field order matters: equality
  fields first, then sort fields (the "ESR rule": Equality, Sort, Range).
- **Multikey on `tags`.** Indexing an array field creates one index entry per
  element, so `find({tags: "maths"})` is fast.
- **Dot-notation** (`stats.object_types`) indexes inside nested documents.

Try `.explain("executionStats")` on a query in Compass or `mongosh` to see whether
it used an index (`IXSCAN`) or scanned the whole collection (`COLLSCAN`).

---

## 5. Atlas Vector Search: the model's memory

### The idea

An **embedding model** turns text into a list of numbers (a vector) so that
texts with similar *meaning* produce vectors that are close together.
"A wave changing shape" and "sine becomes cosine" share no keywords, but their
vectors are close.

We embed each example scene once, store the vector in the document, and at
generation time embed the user's request and ask Atlas for the nearest scenes.
Those become worked examples in the prompt. This pattern is called
**retrieval-augmented generation (RAG)**, and it's the biggest single lever on
output quality.

### What we embed (important)

Not the JSON. Users search in plain language, so we embed a plain-language
summary (`embeddings.scene_text`):

```
Sine becomes cosine
Axes are drawn, the graph of sin(x) traces on, then it morphs into cos(x)...
Tags: maths, graph, trigonometry, morph
Uses objects: axes, graph, text. Uses actions: create, fade_in, transform, wait.
```

That's why every example's `meta.description` matters: it is what search matches against.

### Where the embeddings come from

**Voyage AI** models, which MongoDB owns and serves through Atlas. You create a
*model API key* in Atlas and call `https://ai.mongodb.com/v1/embeddings`
(`embeddings.py`). We pass `input_type: "document"` when storing and `"query"`
when searching; Voyage optimises each side differently, which improves matches.

### The index

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
    { "type": "filter", "path": "is_example" },
    { "type": "filter", "path": "tags" }
  ]
}
```

- `numDimensions` must match the embedding model's output size exactly.
- `similarity: cosine` compares direction, not length, which is standard for text embeddings.
- `filter` fields can narrow the search *before* similarity ranking
  (only examples, only scenes tagged "maths").
- It's created with `create_search_index(..., type="vectorSearch")` and builds
  **asynchronously**. `motif atlas-setup` waits until it reports `queryable`.

### The query

```python
[
  { "$vectorSearch": {
      "index": "scene_embedding",
      "path": "embedding",
      "queryVector": embed_one(request, "query"),
      "numCandidates": 100,   # how many neighbours to consider
      "limit": 3,             # how many to return
      "filter": { "is_example": True }
  }},
  { "$project": { "title": 1, "scene": 1, "score": { "$meta": "vectorSearchScore" } } }
]
```

- `$vectorSearch` must be the **first** stage.
- It's *approximate* nearest neighbour (HNSW graph). `numCandidates` trades speed
  for accuracy; about 10–20× `limit` is a good starting point.
- After it, you can use any normal aggregation stage: `$lookup`, `$match`, `$project`...

Try it: `motif search "something bouncing between two places"` and look at the scores.

---

## 6. Aggregation pipelines over the log

`motif stats` runs these (see `db.generation_stats` and `db.common_errors`).

**Success rate per model:**

```js
[
  { $group: {
      _id: "$model",
      requests:     { $sum: 1 },
      success_rate: { $avg: { $cond: ["$success", 1, 0] } },
      avg_attempts: { $avg: { $size: "$attempts" } }
  }},
  { $sort: { requests: -1 } }
]
```

**Most common mistakes:** `$unwind` turns one document with an array into one
document per element, so two unwinds give one row per error:

```js
[
  { $unwind: "$attempts" },
  { $unwind: "$attempts.errors" },
  { $group: {
      _id: { $regexFind: { input: "$attempts.errors.message", regex: "^[^'.]*" } },
      count: { $sum: 1 },
      example: { $first: "$attempts.errors.message" }
  }},
  { $sort: { count: -1 } }, { $limit: 10 }
]
```

**How to use the results:** if "unknown field 'color'" is at the top, either add
a line to the prompt, add an alias in the validator, or make `color` part of the
language. **The data tells you how to evolve the language.** That's the core
idea of the project.

---

## 7. Setting up Atlas (step by step, done by you)

1. You already have an Atlas account. Use an existing cluster or deploy a free
   **M0** one yourself (a region near you, e.g. Ireland, keeps latency low).
2. **Database Access:** create a database user with a password.
3. **Network Access:** add your current IP address.
4. **Connect → Drivers → Python:** copy the `mongodb+srv://...` string into `.env`
   as `MONGODB_URI`.
5. **AI Models** (in the Atlas sidebar; the exact name may move): create a
   *model API key* and put it in `.env` as `VOYAGE_API_KEY`.
6. `motif atlas-setup` creates collections, validators, indexes and the vector index.
7. `motif seed` embeds and inserts the example scenes.
8. `motif search "a wave changing shape"` checks that it works.

Free clusters support Vector Search but limit how many search indexes you can
have and how big the data can be, which is plenty for this project.

**Working offline:** MongoDB publishes an **Atlas Local** Docker image
(`mongodb/mongodb-atlas-local`) and the Atlas CLI can run one with
`atlas deployments setup --type local`. It supports Vector Search, so you can
develop without the cloud cluster.

**Look at your data:** install **MongoDB Compass** (desktop GUI) or use the Atlas
**Data Explorer**. Open `motif.generations` after a few runs. It's the quickest
way to build intuition.

---

## 8. Atlas features on the roadmap (and what each would teach)

| Feature | Use in Motif | Concept learned |
|---|---|---|
| **Change streams** | A render worker that `watch()`es `scenes` and renders new ones automatically | Event-driven architecture, resume tokens |
| **Atlas Search (full-text)** | Keyword search over titles and descriptions, with typo tolerance and autocomplete | Lucene analysers, `$search` |
| **Hybrid search** | Combine keyword and vector results (newer server versions add `$rankFusion`; check your cluster tier) | Reciprocal rank fusion |
| **Versioning** | Store every edit of a scene as a new document with `parent_id`, and show the history | Document versioning patterns, `$graphLookup` |
| **Atlas Triggers** | Run a function when a generation fails three times in a row | Serverless database triggers |
| **Time-series collection** | Record per-render performance metrics | Time-series bucketing |
| **Charts** | A dashboard of success rate over time from `generations` | Atlas Charts |
