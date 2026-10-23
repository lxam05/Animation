"""The generate -> validate -> repair loop.

    request ─► retrieve similar examples (Atlas Vector Search)
            ─► ask the model for a scene
            ─► validate ──ok──► save scene + log generation ─► render
                  │
                  └─errors─► send errors back to the model (up to N times)

Everything that happens is recorded in one `generations` document, so you can
later ask MongoDB things like "which errors are most common?" (db.common_errors).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import prompt
from .config import ROOT, settings
from .validator import Report, extract_json, validate

# A "model" is anything that takes (system, messages) and returns text. This
# makes the loop testable without an API key (see tests/test_generate.py).
LLM = Callable[[str, list[dict]], str]


def anthropic_llm(system: str, messages: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    resp = client.messages.create(
        model=settings.llm_model, max_tokens=8000, system=system, messages=messages)
    return "".join(b.text for b in resp.content if b.type == "text")


@dataclass
class Result:
    request: str
    report: Report
    attempts: list[dict] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    scene_id: Any = None
    generation_id: Any = None

    @property
    def ok(self) -> bool:
        return self.report.ok


def local_examples(request: str, k: int) -> list[dict]:
    """Offline fallback when Atlas isn't configured: crude keyword overlap.
    It's here mainly to show how much better vector search is."""
    words = set(request.lower().split())
    scored = []
    for path in sorted((ROOT / "examples").glob("*.json")):
        scene = json.loads(path.read_text())
        meta = scene["meta"]
        text = f"{meta['title']} {meta.get('description', '')} {' '.join(meta.get('tags', []))}".lower()
        scored.append((len(words & set(text.split())), {"title": meta["title"], "scene": scene, "_id": path.stem}))
    scored.sort(key=lambda s: -s[0])
    return [s[1] for s in scored[:k]]


def generate(request: str, *, llm: LLM | None = None, use_atlas: bool = True,
             save: bool = True, log: Callable[[str], None] = print) -> Result:
    llm = llm or anthropic_llm
    t_start = time.time()

    # 1. Retrieve examples
    if use_atlas:
        from . import db

        examples = db.find_similar(request, k=settings.examples_k)
        log(f"retrieved {len(examples)} examples via $vectorSearch: "
            + ", ".join(f"{e['title']} ({e.get('score', 0):.3f})" for e in examples))
    else:
        examples = local_examples(request, settings.examples_k)
        log(f"using {len(examples)} local examples (Atlas off)")

    # 2. Ask, validate, repair
    messages: list[dict] = [{"role": "user", "content": prompt.user_prompt(request, examples)}]
    attempts: list[dict] = []
    report = Report()
    for n in range(settings.max_repairs + 1):
        reply = llm(prompt.system_prompt(), messages)
        raw = extract_json(reply)
        report = validate(raw)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        attempts.append({
            "n": n,
            "output": parsed if parsed is not None else raw,
            "errors": [vars(i) for i in report.errors],
            "warnings": [vars(i) for i in report.warnings],
        })
        log(f"attempt {n + 1}: {'valid' if report.ok else f'{len(report.errors)} error(s)'}")
        if report.ok:
            break
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": prompt.repair_prompt(report.for_model())},
        ]

    result = Result(request, report, attempts, examples)

    # 3. Record everything in Atlas
    if use_atlas and save:
        from . import db

        if report.ok and report.scene is not None:
            result.scene_id = db.save_scene(report.scene, is_example=False, source="generated")
        result.generation_id = db.log_generation({
            "request": request,
            "model": settings.llm_model,
            "retrieved": [{"scene_id": e.get("_id"), "title": e["title"], "score": e.get("score")}
                          for e in examples],
            "attempts": attempts,
            "success": report.ok,
            "scene_id": result.scene_id,
            "latency_ms": int((time.time() - t_start) * 1000),
        })
    return result


def write_scene(result: Result, path: Path) -> None:
    if result.report.scene is not None:
        path.write_text(json.dumps(result.report.scene.model_dump(mode="json", exclude_defaults=True), indent=2))
