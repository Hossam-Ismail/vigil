from vigil.brain.base import parse_json
from vigil.brain.heuristic import HeuristicBrain
from vigil.perception.detector import coco_class_for


def test_heuristic_state_request():
    spec = HeuristicBrain().compile("Alert me when the blue bin on the top shelf is empty", None, "cam")
    assert spec["kind"] == "state"
    assert "empty" in spec["positive_label"] and "blue bin" in spec["positive_label"]
    assert spec["locate_noun"] == "blue bin"


def test_heuristic_presence_request():
    spec = HeuristicBrain().compile("Tell me when a person enters through the front door", None, "cam")
    assert spec["kind"] == "presence"
    assert spec["targets"] == ["person"]
    assert spec["trigger"] == "per_object"
    assert spec["locate"] == "the front door"


def test_heuristic_count_request():
    spec = HeuristicBrain().compile("Notify me if there are fewer than 3 pallets on the dock", None, "cam")
    assert spec["kind"] == "count"
    assert spec["count_op"] == "<" and spec["count_value"] == 3
    assert spec["targets"] == ["pallet"]


def test_coco_mapping():
    assert coco_class_for("someone") == "person"
    assert coco_class_for("Workers") == "person"
    assert coco_class_for("forklift") is None


def test_parse_json_handles_noise():
    assert parse_json('<think>hmm {"a": 0}</think> Sure: ```json\n{"answer": "yes"}\n```') == {"answer": "yes"}
    assert parse_json('blah {"x": {"y": 1}} trailing') == {"x": {"y": 1}}


def test_heuristic_reads_hold_time_and_follow_up():
    spec = HeuristicBrain().compile("When the staging area for Line 1 is empty for 2 minutes, add a restock task in HubSpot", None, "cam")
    assert spec["min_duration_s"] == 120
    assert spec["actions"] == [{"type": "hubspot", "object": "task", "note": ""}]
