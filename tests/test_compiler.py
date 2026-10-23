import json
from pathlib import Path

from motif.compiler import compile_scene, resolve_times
from motif.render import to_html
from motif.schema import Scene

EX = Path(__file__).parent.parent / "examples"


def scene(timeline, objects=None):
    return Scene.model_validate({
        "meta": {"title": "t"},
        "objects": objects or [{"id": "c", "type": "circle"}, {"id": "d", "type": "dot"}],
        "timeline": timeline,
    })


def test_resolve_times_sequential_parallel_absolute():
    s = scene([
        {"action": "create", "target": "c", "duration": 1},
        {"action": "fade_in", "target": "d", "with_previous": True, "duration": 2},
        {"action": "move", "target": "c", "to": [1, 0]},       # after everything: t=2
        {"action": "highlight", "target": "d", "at": 0.5},
    ])
    assert resolve_times(s.timeline) == [(0, 1), (0, 2), (2, 3), (0.5, 1.1)]


def test_move_segments_have_from_and_to():
    s = scene([{"action": "create", "target": "c"}, {"action": "move", "target": "c", "to": [3, 2]}])
    c = next(o for o in compile_scene(s)["objects"] if o["id"] == "c")
    xs = [seg for seg in c["segs"] if seg[0] == "x"]
    assert xs == [["x", 1.0, 2.0, 0, 3, "smooth"]]


def test_graph_morph_keeps_point_count():
    s = Scene.model_validate(json.loads((EX / "sine-to-cosine.json").read_text()))
    f = next(o for o in compile_scene(s)["objects"] if o["id"] == "f")
    morph = next(seg for seg in f["segs"] if seg[0] == "points")
    assert len(morph[3]) == len(morph[4]) == 200


def test_html_is_self_contained():
    s = Scene.model_validate(json.loads((EX / "hello-circle.json").read_text()))
    html = to_html(compile_scene(s))
    assert "motif-data" in html and "<script src" not in html
