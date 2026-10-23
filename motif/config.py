"""Settings, read from environment variables (or a .env file in the project root)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Tiny .env loader so we don't need python-dotenv. Real env vars win."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # MongoDB Atlas connection string, from Atlas -> your cluster -> Connect -> Drivers
    mongodb_uri: str = os.environ.get("MONGODB_URI", "")
    db_name: str = os.environ.get("MOTIF_DB", "motif")

    # Embeddings (Voyage AI models, served by MongoDB). Create a "model API key"
    # in Atlas. A key from voyageai.com also works if you set the base URL to
    # https://api.voyageai.com/v1
    voyage_api_key: str = os.environ.get("VOYAGE_API_KEY", "")
    voyage_base_url: str = os.environ.get("VOYAGE_BASE_URL", "https://ai.mongodb.com/v1")
    embed_model: str = os.environ.get("MOTIF_EMBED_MODEL", "voyage-4")
    embed_dims: int = int(os.environ.get("MOTIF_EMBED_DIMS", "1024"))

    # The model that writes scenes
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    llm_model: str = os.environ.get("MOTIF_LLM_MODEL", "claude-sonnet-5-5")
    max_repairs: int = int(os.environ.get("MOTIF_MAX_REPAIRS", "3"))
    examples_k: int = int(os.environ.get("MOTIF_EXAMPLES_K", "3"))


settings = Settings()
