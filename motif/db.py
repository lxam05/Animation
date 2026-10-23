"""Everything that talks to MongoDB Atlas lives in this file.

Collections (database "motif" by default):

  scenes       one document per scene. Example scenes (the AI's reference
               library) and generated scenes live together, told apart by
               `is_example`. Each has an `embedding` for Vector Search.
  generations  one document per AI generation request: the prompt, which
               examples were retrieved, every attempt with its validation
               errors, and the outcome. This is the project's learning log.
  renders      cache of compiled player data, keyed by a hash of the scene.
               Expires automatically after 30 days (TTL index).

Read docs/02-atlas-and-mongodb.md for the reasoning behind each choice.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.operations import SearchIndexModel

from .config import settings
from .embeddings import embed_one, scene_text
from .schema import Scene

VECTOR_INDEX = "scene_embedding"
RENDER_TTL_SECONDS = 30 * 24 * 3600

_client: MongoClient | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_db() -> Database:
    global _client
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set (copy .env.example to .env)")
    if _client is None:
        # appname shows up in Atlas monitoring, handy for spotting your app's traffic
        _client = MongoClient(settings.mongodb_uri, appname="motif")
    return _client[settings.db_name]


def ping() -> dict:
    return get_db().command("ping")


# ------------------------------------------------------------------- setup


# Server-side schema validation. MongoDB is schemaless by default; a $jsonSchema
# validator lets the *database* reject documents missing key fields. We only
# check the envelope here. The full scene format is checked in Python
# (validator.py), because it needs logic a JSON schema can't express.
SCENES_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["title", "scene", "is_example", "source", "created_at"],
        "properties": {
            "title": {"bsonType": "string"},
            "scene": {"bsonType": "object", "required": ["meta", "objects", "timeline"]},
            "is_example": {"bsonType": "bool"},
            "source": {"enum": ["human", "generated"]},
            "tags": {"bsonType": "array", "items": {"bsonType": "string"}},
            "embedding": {"bsonType": "array"},
            "created_at": {"bsonType": "date"},
        },
    }
}


def setup(verbose: bool = True) -> None:
    """Create collections, validators and indexes. Safe to run repeatedly."""
    db = get_db()
    log = print if verbose else (lambda *a, **k: None)

    try:
        db.create_collection("scenes", validator=SCENES_VALIDATOR)
        log("created collection scenes (with $jsonSchema validator)")
    except CollectionInvalid:
        db.command("collMod", "scenes", validator=SCENES_VALIDATOR)
        log("scenes exists; validator updated")
    for name in ("generations", "renders"):
        if name not in db.list_collection_names():
            db.create_collection(name)
            log(f"created collection {name}")

    scenes, gens, renders = db.scenes, db.generations, db.renders
    # Regular (B-tree) indexes
    scenes.create_index("slug", unique=True, sparse=True)
    scenes.create_index([("is_example", ASCENDING), ("created_at", DESCENDING)])
    scenes.create_index("tags")  # multikey index: one entry per array element
    scenes.create_index("stats.object_types")
    gens.create_index([("created_at", DESCENDING)])
    gens.create_index("success")
    # TTL index: MongoDB deletes render cache entries ~30 days after created_at
    renders.create_index("created_at", expireAfterSeconds=RENDER_TTL_SECONDS)
    log("regular + TTL indexes ok")

    # Atlas Vector Search index. This is NOT a normal index: it's managed by
    # Atlas Search (mongot) and builds asynchronously, so it can take a minute
    # before $vectorSearch returns results.
    definition = {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": settings.embed_dims,
             "similarity": "cosine"},
            # "filter" fields can be used inside $vectorSearch's `filter` option
            {"type": "filter", "path": "is_example"},
            {"type": "filter", "path": "tags"},
        ]
    }
    existing = {ix["name"]: ix for ix in scenes.list_search_indexes()}
    if VECTOR_INDEX in existing:
        scenes.update_search_index(VECTOR_INDEX, definition)
        log(f"vector search index '{VECTOR_INDEX}' updated")
    else:
        scenes.create_search_index(
            SearchIndexModel(definition=definition, name=VECTOR_INDEX, type="vectorSearch"))
        log(f"vector search index '{VECTOR_INDEX}' requested (builds in the background)")


def wait_for_vector_index(timeout: float = 180) -> bool:
    scenes = get_db().scenes
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ix in scenes.list_search_indexes(VECTOR_INDEX):
            if ix.get("queryable"):
                return True
        time.sleep(3)
    return False


# ------------------------------------------------------------------ scenes


def scene_stats(scene: Scene) -> dict:
    from .compiler import scene_duration

    return {
        "object_types": sorted({o.type for o in scene.objects}),
        "actions": sorted({a.action for a in scene.timeline}),
        "n_objects": len(scene.objects),
        "duration": round(scene_duration(scene), 3),
    }


def save_scene(scene: Scene, *, is_example: bool, source: str, slug: str | None = None,
               parent_id: Any = None, embed: bool = True) -> Any:
    """Insert or update (by slug) a scene document. Returns its _id."""
    doc: dict[str, Any] = {
        "title": scene.meta.title,
        "description": scene.meta.description,
        "tags": scene.meta.tags,
        "scene": scene.model_dump(mode="json"),
        "stats": scene_stats(scene),
        "is_example": is_example,
        "source": source,
        "content_hash": content_hash(scene),
        "created_at": now(),
    }
    if parent_id is not None:
        doc["parent_id"] = parent_id  # lineage: "this scene was a variation of that one"
    if embed:
        doc["embedding"] = embed_one(scene_text(scene), "document")
    scenes = get_db().scenes
    if slug:
        doc["slug"] = slug
        res = scenes.find_one_and_update(
            {"slug": slug}, {"$set": doc}, upsert=True, return_document=ReturnDocument.AFTER, projection={"_id": 1})
        return res["_id"]
    return scenes.insert_one(doc).inserted_id


def find_similar(query: str, k: int = 3, examples_only: bool = True,
                 num_candidates: int = 100) -> list[dict]:
    """Semantic search: the k scenes whose meaning is closest to `query`.

    $vectorSearch must be the first stage of the pipeline. numCandidates is how
    many approximate neighbours Atlas considers before picking the best `limit`;
    roughly 10-20x limit is a good rule of thumb.
    """
    stage: dict[str, Any] = {
        "index": VECTOR_INDEX,
        "path": "embedding",
        "queryVector": embed_one(query, "query"),
        "numCandidates": num_candidates,
        "limit": k,
    }
    if examples_only:
        stage["filter"] = {"is_example": True}
    pipeline = [
        {"$vectorSearch": stage},
        {"$project": {"title": 1, "description": 1, "scene": 1, "tags": 1,
                      "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(get_db().scenes.aggregate(pipeline))


# ------------------------------------------------------------- generations


def log_generation(doc: dict) -> Any:
    doc.setdefault("created_at", now())
    return get_db().generations.insert_one(doc).inserted_id


def generation_stats() -> list[dict]:
    """Aggregation pipeline: success rate and average attempts, per model.

    A good first pipeline to read: $group buckets documents, $avg/$sum compute
    per bucket, $cond turns a boolean into 1/0 so we can average it.
    """
    pipeline = [
        {"$group": {
            "_id": "$model",
            "requests": {"$sum": 1},
            "success_rate": {"$avg": {"$cond": ["$success", 1, 0]}},
            "avg_attempts": {"$avg": {"$size": "$attempts"}},
            "avg_latency_ms": {"$avg": "$latency_ms"},
        }},
        {"$sort": {"requests": -1}},
    ]
    return list(get_db().generations.aggregate(pipeline))


def common_errors(limit: int = 10) -> list[dict]:
    """Which validation errors does the model make most? ($unwind twice)."""
    pipeline = [
        {"$unwind": "$attempts"},
        {"$unwind": "$attempts.errors"},
        # Group by the message with quoted names stripped, so "unknown object 'a'"
        # and "unknown object 'b'" count as the same mistake.
        {"$group": {
            "_id": {"$regexFind": {"input": "$attempts.errors.message", "regex": "^[^'.]*"}},
            "count": {"$sum": 1},
            "example": {"$first": "$attempts.errors.message"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "pattern": "$_id.match", "count": 1, "example": 1}},
    ]
    return list(get_db().generations.aggregate(pipeline))


# ------------------------------------------------------------------ renders


def content_hash(scene: Scene) -> str:
    from .compiler import RENDERER_VERSION

    canonical = json.dumps(scene.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{RENDERER_VERSION}:{canonical}".encode()).hexdigest()


def cached_render(scene: Scene) -> dict | None:
    doc = get_db().renders.find_one({"_id": content_hash(scene)})
    return doc["compiled"] if doc else None


def store_render(scene: Scene, compiled: dict) -> None:
    try:
        get_db().renders.replace_one(
            {"_id": content_hash(scene)},
            {"compiled": compiled, "created_at": now()},
            upsert=True,
        )
    except OperationFailure as exc:  # e.g. document over the 16 MB BSON limit
        print(f"warning: render not cached: {exc}")
