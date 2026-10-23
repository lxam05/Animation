"""Turn text into vectors for Atlas Vector Search.

We call the Voyage AI embeddings endpoint over plain HTTP (it is the same API
whether you use MongoDB's endpoint or voyageai.com), so there's no extra SDK.

Two ideas worth knowing:

* input_type: Voyage models embed *documents* (things you store) and *queries*
  (things you search with) slightly differently. Use "document" when seeding
  scenes and "query" when embedding a user's prompt. It improves retrieval.

* What we embed: NOT the raw scene JSON. Users search with plain language
  ("show a sine wave morphing"), so we embed a plain-language summary of each
  scene: its title, description, tags, and which object/action types it uses.
  See scene_text() below.
"""

from __future__ import annotations

from typing import Literal

import httpx

from .config import settings
from .schema import Scene


class EmbeddingError(RuntimeError):
    pass


def embed(texts: list[str], input_type: Literal["document", "query"]) -> list[list[float]]:
    if not settings.voyage_api_key:
        raise EmbeddingError("VOYAGE_API_KEY is not set (see .env.example)")
    resp = httpx.post(
        f"{settings.voyage_base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={
            "input": texts,
            "model": settings.embed_model,
            "input_type": input_type,
            "output_dimension": settings.embed_dims,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise EmbeddingError(f"embedding request failed ({resp.status_code}): {resp.text[:300]}")
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_one(text: str, input_type: Literal["document", "query"]) -> list[float]:
    return embed([text], input_type)[0]


def scene_text(scene: Scene) -> str:
    """The plain-language text we embed for a scene."""
    types = sorted({o.type for o in scene.objects})
    actions = sorted({a.action for a in scene.timeline})
    parts = [
        scene.meta.title,
        scene.meta.description,
        f"Tags: {', '.join(scene.meta.tags)}" if scene.meta.tags else "",
        f"Uses objects: {', '.join(types)}. Uses actions: {', '.join(actions)}.",
    ]
    return "\n".join(p for p in parts if p)
