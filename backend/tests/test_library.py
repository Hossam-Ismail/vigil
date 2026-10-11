from vigil.perception import library as lib


def test_specialists_by_words():
    assert lib.match("Text me if anyone isn't wearing a hard hat") == {"id": "hardhat", "yes": ["NO-Hardhat"]}
    assert lib.match("Count workers wearing hard hats")["yes"] == ["Hardhat"]
    assert lib.match("Text me if someone falls in the lobby")["id"] == "fall"
    assert lib.match("Tell me when a forklift enters aisle 3")["id"] == "forklift"
    assert lib.match("Alert me if there's smoke in the kitchen")["yes"] == ["Smoke", "Smoke and Fire"]
    assert lib.match("Text me if a fire starts")["yes"] == ["Fire", "Smoke and Fire"]


def test_actions_need_every_word(monkeypatch):
    monkeypatch.setattr(lib, "kinetics_labels", lambda: ["smoking", "smoking hookah", "mopping floor",
                                                         "running on treadmill", "waiting in line", "drinking beer"])
    assert lib.match("Text me if anyone is smoking by the entrance") == {"id": "actions", "yes": ["smoking"]}
    assert lib.match("Tell me when someone is mopping")["yes"] == ["mopping floor"]
    assert lib.match("Text me when someone is running") is None          # treadmill not mentioned
    assert lib.match("How many people are waiting in line?", kind="count") is None
    assert lib.match("Text me when the garage door is open") is None


def test_library_has_ten_with_two_not_native():
    assert len(lib.LIBRARY) == 10
    assert sorted(m.id for m in lib.LIBRARY if not m.native) == ["pose", "xclip"]
