"""Command line interface: `python -m motif <command>` (or just `motif` once installed).

Works offline:
  motif validate examples/sine-to-cosine.json
  motif render   examples/sine-to-cosine.json -o out/sine.html
  motif schema                      # print the JSON Schema

Needs Atlas (MONGODB_URI):
  motif ping                        # read-only connection check

Needs Atlas and embeddings (VOYAGE_API_KEY):
  motif atlas-setup                 # collections, validators, indexes, vector index
  motif seed                        # load examples/ into Atlas with embeddings
  motif search "a wave changing shape"

Needs Atlas + ANTHROPIC_API_KEY:
  motif generate "show how a circle's area grows with its radius" -o out/area.html
  motif stats                       # aggregation pipelines over the generation log

Add --offline to `generate` to skip Atlas entirely (keyword-matched examples).
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .compiler import compile_scene
from .config import ROOT
from .render import to_html
from .schema import json_schema
from .validator import validate


def _render_to(scene, out: Path, use_cache: bool = False) -> None:
    compiled = None
    if use_cache:
        from . import db

        compiled = db.cached_render(scene)
        print("render cache:", "hit" if compiled else "miss")
    if compiled is None:
        compiled = compile_scene(scene)
        if use_cache:
            from . import db

            db.store_render(scene, compiled)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_html(compiled))
    print(f"wrote {out}  ({compiled['duration']:.1f}s animation)")


def cmd_validate(a) -> int:
    report = validate(Path(a.file).read_text())
    for issue in report.issues:
        print(issue)
    print("OK" if report.ok else f"FAILED ({len(report.errors)} errors)")
    return 0 if report.ok else 1


def cmd_render(a) -> int:
    report = validate(Path(a.file).read_text())
    for issue in report.issues:
        print(issue)
    if not report.ok:
        return 1
    out = Path(a.out or f"out/{Path(a.file).stem}.html")
    _render_to(report.scene, out, use_cache=a.cache)
    if a.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_schema(a) -> int:
    print(json.dumps(json_schema(), indent=2))
    return 0


def cmd_ping(a) -> int:
    """Read-only connection check: creates and changes nothing."""
    from .config import settings
    from . import db

    host = settings.mongodb_uri.split("@")[-1].split("/")[0] if "@" in settings.mongodb_uri else "?"
    print(f"connecting to {host} ...")
    try:
        db.ping()
    except Exception as exc:  # show the beginner-relevant cause, not a wall of text
        print(f"FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        print("hints: timeout -> check Network Access (your IP); "
              "auth failed -> check username/password in .env; "
              "unset -> copy .env.example to .env")
        return 1
    client = db.get_db().client
    info = client.server_info()
    print(f"connected! MongoDB server version {info['version']}")
    print("databases on this cluster:", ", ".join(client.list_database_names()))
    print(f"this project will use the database '{settings.db_name}' "
          "(MongoDB creates it on the first write)")
    return 0


def cmd_setup(a) -> int:
    from . import db

    print("ping:", db.ping())
    db.setup()
    print("waiting for the vector index to become queryable...")
    print("ready" if db.wait_for_vector_index() else "still building - check Atlas UI > Search")
    return 0


def cmd_seed(a) -> int:
    from . import db
    from .embeddings import embed, scene_text

    valid = []
    for path in sorted((ROOT / "examples").glob("*.json")):
        report = validate(path.read_text())
        if not report.ok:
            print(f"skip {path.name}: {report.errors[0]}")
            continue
        valid.append((path.stem, report.scene))
    # One embedding request for all scenes, not one per scene: fewer round trips,
    # and it stays under the 3-requests-per-minute free-tier rate limit.
    vectors = embed([scene_text(s) for _, s in valid], "document")
    for (slug, scene), vector in zip(valid, vectors):
        _id = db.save_scene(scene, is_example=True, source="human", slug=slug, embedding=vector)
        print(f"seeded {slug} -> {_id}")
    print(f"{len(valid)} example scenes in Atlas")
    return 0


def cmd_search(a) -> int:
    from . import db

    for hit in db.find_similar(a.query, k=a.k, examples_only=not a.all):
        print(f"{hit['score']:.4f}  {hit['title']}  —  {hit.get('description', '')[:70]}")
    return 0


def cmd_generate(a) -> int:
    from .generate import generate, write_scene

    result = generate(a.request, use_atlas=not a.offline)
    for issue in result.report.issues:
        print(issue)
    if not result.ok:
        print("could not produce a valid scene; see attempts above")
        return 1
    slug = a.out and Path(a.out).stem or "generated"
    json_path = Path(a.out).with_suffix(".json") if a.out else Path(f"out/{slug}.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_scene(result, json_path)
    print(f"wrote {json_path}")
    _render_to(result.report.scene, json_path.with_suffix(".html"))
    if a.open:
        webbrowser.open(json_path.with_suffix(".html").resolve().as_uri())
    return 0


def cmd_stats(a) -> int:
    from . import db

    print("== per model ==")
    for row in db.generation_stats():
        print(f"{row['_id']}: {row['requests']} requests, {row['success_rate']:.0%} success, "
              f"{row['avg_attempts']:.2f} attempts avg, {row['avg_latency_ms'] or 0:.0f} ms avg")
    print("\n== most common validation errors ==")
    for row in db.common_errors():
        print(f"{row['count']:4}  {row['example']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="motif", description="Motif: a motion-graphics language for AI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="check a scene file")
    s.add_argument("file")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("render", help="render a scene to a self-contained HTML player")
    s.add_argument("file")
    s.add_argument("-o", "--out")
    s.add_argument("--open", action="store_true", help="open in your browser")
    s.add_argument("--cache", action="store_true", help="use the Atlas render cache")
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("schema", help="print the JSON Schema of the format")
    s.set_defaults(fn=cmd_schema)

    s = sub.add_parser("ping", help="check the connection to Atlas (read-only)")
    s.set_defaults(fn=cmd_ping)

    s = sub.add_parser("atlas-setup", help="create collections and indexes in Atlas")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("seed", help="load examples/ into Atlas with embeddings")
    s.set_defaults(fn=cmd_seed)

    s = sub.add_parser("search", help="semantic search over scenes")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--all", action="store_true", help="include generated scenes, not just examples")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("generate", help="ask the AI for a scene, validate, repair, render")
    s.add_argument("request")
    s.add_argument("-o", "--out", help="output path, e.g. out/area.html")
    s.add_argument("--offline", action="store_true", help="don't use Atlas")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_generate)

    s = sub.add_parser("stats", help="aggregation pipelines over the generation log")
    s.set_defaults(fn=cmd_stats)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
