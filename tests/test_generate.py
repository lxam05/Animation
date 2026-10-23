"""The repair loop, with a fake model so no API key or database is needed."""

import json

from motif.generate import generate

BROKEN = {"meta": {"title": "x"}, "objects": [{"id": "c", "type": "circle", "radius": 1}],
          "timeline": [{"action": "create", "target": "c"}]}
FIXED = {"meta": {"title": "x"}, "objects": [{"id": "c", "type": "circle", "r": 1}],
         "timeline": [{"action": "create", "target": "c"}]}


def test_repair_loop_feeds_errors_back():
    seen = []

    def fake_llm(system, messages):
        seen.append(messages[-1]["content"])
        return "```json\n" + json.dumps(BROKEN if len(seen) == 1 else FIXED) + "\n```"

    r = generate("a circle", llm=fake_llm, use_atlas=False, log=lambda *_: None)
    assert r.ok
    assert len(r.attempts) == 2
    assert "Did you mean 'r'" in seen[1]          # the error reached the model
    assert r.attempts[0]["errors"][0]["path"] == "objects[0].radius"


def test_gives_up_after_max_repairs():
    r = generate("a circle", llm=lambda s, m: json.dumps(BROKEN), use_atlas=False, log=lambda *_: None)
    assert not r.ok and len(r.attempts) == 4
