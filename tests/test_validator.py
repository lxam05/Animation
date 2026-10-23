import json
from pathlib import Path

import pytest

from motif.validator import extract_json, validate

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.json"))


def base(**over):
    scene = {
        "meta": {"title": "t"},
        "objects": [{"id": "c", "type": "circle"}],
        "timeline": [{"action": "create", "target": "c"}],
    }
    scene.update(over)
    return scene


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_are_valid_with_no_warnings(path):
    r = validate(path.read_text())
    assert r.ok, r.for_model()
    assert not r.warnings, r.for_model()


def test_minimal_scene_ok():
    assert validate(base()).ok


def test_bad_json():
    r = validate("{not json")
    assert not r.ok and "invalid JSON" in r.errors[0].message


def test_unknown_field_suggests_fix():
    r = validate(base(objects=[{"id": "c", "type": "circle", "radius": 2}]))
    assert not r.ok
    assert r.errors[0].path == "objects[0].radius"
    assert "Did you mean 'r'" in r.errors[0].message


def test_unknown_type_lists_options():
    r = validate(base(objects=[{"id": "c", "type": "cirle"}]))
    assert "Did you mean 'circle'" in r.errors[0].message


def test_unknown_target_suggests_id():
    r = validate(base(objects=[{"id": "circle1", "type": "circle"}],
                      timeline=[{"action": "create", "target": "circel1"}]))
    assert "Did you mean 'circle1'" in r.errors[0].message


def test_overlapping_animation_is_error():
    r = validate(base(timeline=[
        {"action": "create", "target": "c"},
        {"action": "move", "target": "c", "to": [1, 0]},
        {"action": "move", "target": "c", "to": [2, 0], "with_previous": True},
    ]))
    assert any("overlaps timeline[1]" in e.message for e in r.errors)


def test_bad_expression():
    r = validate(base(
        objects=[{"id": "ax", "type": "axes"}, {"id": "g", "type": "graph", "axes": "ax", "expr": "__import__('os')"}],
        timeline=[{"action": "create", "target": "g"}]))
    assert any(e.path == "objects[1].expr" for e in r.errors)


def test_graph_needs_axes():
    r = validate(base(objects=[{"id": "g", "type": "graph", "axes": "nope", "expr": "x"}],
                      timeline=[{"action": "create", "target": "g"}]))
    assert any("not an axes" in e.message for e in r.errors)


def test_transform_prop_not_allowed():
    r = validate(base(timeline=[
        {"action": "create", "target": "c"},
        {"action": "transform", "target": "c", "to": {"w": 3}},
    ]))
    assert any("can't be animated on a circle" in e.message for e in r.errors)


def test_bad_colour():
    r = validate(base(objects=[{"id": "c", "type": "circle", "fill": "red"}]))
    assert any("hex" in e.message for e in r.errors)


def test_move_before_create_warns():
    r = validate(base(timeline=[{"action": "move", "target": "c", "to": [1, 1]}]))
    assert r.ok and any("not visible yet" in w.message for w in r.warnings)


def test_extract_json_from_fenced_reply():
    reply = 'Sure!\n```json\n{"a": 1}\n```\nEnjoy'
    assert json.loads(extract_json(reply)) == {"a": 1}
