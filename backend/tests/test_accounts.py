import pytest

from vigil import accounts as acc
from vigil.accounts import Accounts, AuthError
from vigil.db import DB


@pytest.fixture
def A(tmp_path, monkeypatch):
    sent = {}

    def fake_send(to, subject, text, code_for_log=""):
        sent["code"] = code_for_log
        return "log"

    monkeypatch.setattr("vigil.mail.send", fake_send)
    monkeypatch.setattr(acc, "check_anthropic_key", lambda key: None)
    monkeypatch.setattr(acc, "use_key", lambda key: None)
    a = Accounts(DB(tmp_path / "t.db"))
    a.sent = sent
    return a


def test_only_edu_emails():
    assert acc.check_email(" Student@Gatech.EDU ") == "student@gatech.edu"
    assert acc.check_email("a.b@cs.stanford.edu") == "a.b@cs.stanford.edu"
    assert acc.check_email("x@unsw.edu.au") == "x@unsw.edu.au"
    for bad in ("x@gmail.com", "x@edu.com", "x@school.education", "nope", "x@.edu"):
        with pytest.raises(AuthError):
            acc.check_email(bad)


def test_passwords():
    h = acc.hash_password("hunter2hunter2")
    assert acc.check_password("hunter2hunter2", h) and not acc.check_password("wrong", h)
    with pytest.raises(AuthError):
        acc.check_new_password("short1")
    with pytest.raises(AuthError):
        acc.check_new_password("onlyletters")


def test_full_onboarding(A):
    with pytest.raises(AuthError):
        A.sign_up("me@gatech.edu", "password1", consent=False)
    u = A.sign_up("me@gatech.edu", "password1", consent=True)
    assert A.next_step(u) == "verify"
    A.send_code(u)
    with pytest.raises(AuthError):
        A.verify(u, "000000" if A.sent["code"] != "000000" else "111111")
    u = A.verify(u, A.sent["code"])
    assert A.next_step(u) == "profile"
    with pytest.raises(AuthError):
        A.set_profile(u, {"use": "business", "goals": "count customers in line"})  # no business type
    u = A.set_profile(u, {"use": "business", "business_type": "coffee shop", "goals": "count customers in line"})
    assert A.next_step(u) == "ai_key"
    with pytest.raises(AuthError):
        A.set_ai_key(u, "anthropic", "not-a-key")
    u = A.set_ai_key(u, "anthropic", "sk-ant-" + "x" * 40)
    assert A.next_step(u) == "camera"
    u = A.finish(u)
    assert A.next_step(u) == "ready" and A.public(u)["ai_key_hint"] == "…xxxx"


def test_sessions_and_login(A):
    u = A.sign_up("me@gatech.edu", "password1", consent=True)
    token = A.new_session(u["id"])
    assert A.session_user(token)["id"] == u["id"]
    A.end_session(token)
    assert A.session_user(token) is None
    assert A.sign_in("ME@gatech.edu", "password1")["id"] == u["id"]
    with pytest.raises(AuthError):
        A.sign_in("me@gatech.edu", "wrong")


def test_resend_cooldown_and_feedback(A):
    u = A.sign_up("me@gatech.edu", "password1", consent=True)
    A.send_code(u)
    with pytest.raises(AuthError):
        A.send_code(u)
    A.add_feedback(u, 5, "idea", "love it", "/")
    assert A.feedback()[0]["email"] == "me@gatech.edu"
