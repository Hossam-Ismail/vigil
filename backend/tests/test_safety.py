"""The safety policy: legitimate requests pass, creepy or unlawful ones are refused with a reason and a rewording."""

from vigil import brain, privacy
from vigil.safety import check_spec, check_text

ALLOWED = [
    "Text me when a package is left on the front step",
    "Text the shift lead if anyone at the pump isn't wearing a hard hat",
    "Text me when more than 4 people are waiting to pay",
    "Count walk-ins at the front door",
    "What % of the time is the staging area empty?",
    "Open a HubSpot ticket, high priority, if a pallet blocks aisle 3",
    "Text me if anyone goes near the pool",
    "Alert me if a person falls in the warehouse",
    "Text the store manager when the line is long",
    "Text me when the baby wakes up",
]

REFUSED = {
    "Detect when a girl walks by": "protected_traits",
    "Tell me when a black man enters": "protected_traits",
    "Recognize who is at the door": "identity",
    "Tell me if my ex comes by": "identity",
    "Watch the bathroom and text me": "private_spaces",
    "Text me when someone undresses": "bodies",
    "Spy on my neighbour's yard": "private_spaces",
    "Alert me if someone looks suspicious": "inference",
    "Alert me when a kid is changing": "minors",
}


def test_allowed_requests_pass():
    for q in ALLOWED:
        assert check_text(q).allowed, q


def test_refused_requests_explain_themselves():
    for q, cat in REFUSED.items():
        v = check_text(q)
        assert not v.allowed and v.category == cat, (q, v)
        assert v.reason and v.suggestion


def test_compiled_spec_is_checked_too():
    assert not check_spec({"name": "Lobby", "positive_label": "a woman in the lobby", "question": "Is a woman here?"}).allowed
    assert check_spec({"name": "Pump", "positive_label": "a worker without a hard hat", "question": "No hard hat?"}).allowed


def test_private_mode_keeps_images_local():
    privacy.apply({"private_mode": True})
    assert brain.private() and brain.get_brain().label.split(" ")[0] != "Claude"
    privacy.apply({"private_mode": False, "keep_history_days": 0, "keep_events_days": 99999})
    assert not brain.private()
    assert privacy.current()["keep_history_days"] == 1 and privacy.current()["keep_events_days"] == 3650
    privacy.apply({})  # back to the safe defaults
    assert privacy.current() == privacy.DEFAULTS
