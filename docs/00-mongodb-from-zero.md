# 00 — MongoDB from zero

Read this before `02-atlas-and-mongodb.md`. It assumes you've never used a
database. Every example comes from this project.

---

## 1. What is a database, and why not just files?

Right now the example scenes are JSON files in `examples/`. That works for 6.
It stops working when you want to:

- store thousands of AI-generated scenes
- find "every scene that uses a graph" without opening every file
- find scenes that *mean* something similar to a request (the AI's memory)
- log every AI attempt and then ask "what mistake does it make most often?"
- have a web app, a script and a render worker all read and write at once

A **database** is a program that stores data and answers questions about it
quickly and safely, even when lots of things use it at the same time.

## 2. What kind of database is MongoDB?

There are two big families:

| | Relational (SQL), e.g. PostgreSQL | Document, e.g. **MongoDB** |
|---|---|---|
| Stores data as | **Tables**: rows and fixed columns, like a strict spreadsheet | **Documents**: JSON-like objects that can nest |
| A Motif scene would be | Split across ~5 tables (scenes, objects, actions, properties…) and re-joined on every read | **One document, stored exactly as it looks** |
| Changing the shape | Alter the table for every row | Just start writing the new shape |

Our scenes are already JSON with nested lists (objects, timeline), so a
document database is the natural fit. That's the main reason for MongoDB here.

## 3. The four words you need

```
Cluster  (your Atlas "server", hosted by MongoDB in the cloud)
 └── Database   "motif"
      ├── Collection   "scenes"        ← like a folder of similar documents
      │    ├── Document  { title: "Sine becomes cosine", scene: {...}, ... }
      │    └── Document  { title: "Bars growing", ... }
      ├── Collection   "generations"
      └── Collection   "renders"
```

- **Cluster:** the machine(s) running MongoDB. Atlas runs it for you; the free size is called **M0**.
- **Database:** a named container. Ours is `motif`.
- **Collection:** a group of documents of the same *kind* (like a table, but without forced columns).
- **Document:** one record, written as JSON. Every document gets a unique `_id` automatically.

## 4. What "Atlas" adds

**MongoDB** is the database software. **Atlas** is MongoDB's cloud service: it
runs the database for you (backups, security, monitoring) and adds extra
features we use:

- **Vector Search:** find documents by *meaning*, not exact words
- **Embedding models (Voyage AI):** turn text into the numbers Vector Search uses
- A web UI (**Data Explorer**) to look at your data in the browser

## 5. The five operations (CRUD + search)

Here's what the code does, in Python with PyMongo, the official driver:

```python
db = MongoClient(uri)["motif"]          # connect, pick the database

# Create: add a document
db.scenes.insert_one({"title": "Hello", "tags": ["basics"]})

# Read: find documents matching a filter (a filter is just a dict)
db.scenes.find({"tags": "basics"})                 # all scenes tagged basics
db.scenes.find_one({"title": "Hello"})             # the first match

# Update: change part of a document ($set = "set these fields")
db.scenes.update_one({"title": "Hello"}, {"$set": {"tags": ["basics", "intro"]}})

# Delete
db.scenes.delete_one({"title": "Hello"})

# Aggregate: a pipeline of steps, like an assembly line
db.generations.aggregate([
    {"$match": {"success": False}},                 # step 1: only failed attempts
    {"$group": {"_id": "$model", "n": {"$sum": 1}}} # step 2: count them per model
])
```

Words starting with `$` (`$set`, `$match`, `$group`, `$sum`) are **operators**:
MongoDB's built-in instructions. A `$` in front of a field name inside a
pipeline (`"$model"`) means "the value of that field".

## 6. Indexes, in one picture

Without an index, `find({"tags": "maths"})` reads **every** document and checks
it, like reading a whole book to find one word. An **index** is the book's index
at the back: a sorted list that jumps straight to the right pages.

- Indexes make reads fast but make writes slightly slower and take space,
  so we add them only for questions we actually ask.
- A **vector index** is a special index for "which documents are closest in meaning?"

## 7. Where each concept shows up in this project

| Concept | In Motif | File |
|---|---|---|
| Documents with nesting | A whole scene stored in one document | `db.py` → `save_scene` |
| Collections | `scenes`, `generations`, `renders` | `db.py` → `setup` |
| Schema validation | MongoDB rejects scenes missing a title | `db.py` → `SCENES_VALIDATOR` |
| Indexes | Fast lookups by slug, tags, date | `db.py` → `setup` |
| TTL index | Render cache deletes itself after 30 days | `db.py` → `setup` |
| Embeddings | Scene description → 1024 numbers | `embeddings.py` |
| Vector Search | "Find 3 scenes like this request" | `db.py` → `find_similar` |
| Aggregation | "Most common AI mistakes" | `db.py` → `common_errors` |

## 8. The decisions we made, and why (session 2)

Liam is new to MongoDB, so Claude made these calls. Each has a plain-English reason.

1. **MongoDB rather than a SQL database.** Scenes are nested JSON. Storing them as
   one document avoids splitting them across tables and joining them back on every read.

2. **One `scenes` collection for both hand-written examples and AI-generated
   scenes**, with an `is_example: true/false` field.
   *Why:* they're the same kind of thing (a Motif scene). One collection means one
   vector index and one place to search. When a generated scene turns out great,
   promoting it to an example is a one-field change. *Alternative:* two
   collections, which would mean two indexes and copying documents to promote them.

3. **Each AI attempt is stored inside its `generations` document** (an array),
   not in a separate collection.
   *Why:* there are only 1–4 attempts per request, they're always read together,
   and they mean nothing on their own. MongoDB's rule of thumb: *data that's used
   together is stored together.* *When we'd change it:* if attempts could grow
   without limit (documents max out at 16 MB).

4. **Voyage AI for embeddings, through your Atlas account.**
   *Why:* MongoDB owns Voyage and serves it from Atlas, so it's one account and
   one bill, and it's designed to pair with Atlas Vector Search. *Alternative:*
   OpenAI or a local model; `embeddings.py` is small, so swapping later is easy.

5. **The free M0 cluster is enough.** It supports Vector Search; the limits on
   data size and index count are far beyond what this project needs for now.
