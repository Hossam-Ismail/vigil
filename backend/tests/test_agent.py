from vigil.agent import best_match, count_phrase, owners, route


def test_routes_owner_texts():
    assert route("Text me when a package is left at the front door").kind == "create"
    assert route("can you count the cars in the lot").kind == "create"
    assert route("What's happening at the dock?").kind == "look"
    assert route("show me").kind == "look"
    assert route("How many cars are in the lot?").kind == "metric"
    assert route("what are you watching").kind == "list"
    assert route("status").kind == "list"
    assert route("pause dock").kind == "pause" and route("pause dock").arg == "dock"
    assert route("Resume the dock watch").kind == "resume"
    assert route("YES").kind == "feedback" and route("yes").arg == "correct"
    assert route("no").arg == "false_alarm"
    assert route("hi").kind == "help"
    assert route("banana phone").kind == "unknown"


def test_pending_camera_pick():
    assert route("2", pending=True).kind == "pick"
    assert route("front door", pending=True).kind == "pick"
    assert route("text me when the bin is full", pending=True).kind == "create"


def test_owners_and_matching():
    assert owners({"imessage_to": "+1 (404) 555-0101, me@icloud.com"}) == {"4045550101", "me@icloud.com"}
    assert owners({}) == set()
    assert best_match("what's happening at the loading dock", ["Front door", "Loading dock"]) == 1
    assert best_match("zzz", ["Front door"]) is None
    assert count_phrase({"person": 2, "car": 1}) == "2 people and 1 car"
