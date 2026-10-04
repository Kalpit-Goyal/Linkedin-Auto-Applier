'''
Unit tests for modules/session.py — the persistent-login layer.

These use a stub driver rather than a real browser, so they exercise the cookie
filtering/normalising rules and the "never raise" contract without launching
Chrome. That contract is the important one: losing a saved session must never
take down an application run.

License: MIT  (https://opensource.org/license/mit)
'''

import json
import os
import time

import pytest

from modules import session
from modules.session import (
    _future_expiry,
    _is_linkedin_domain,
    clear_saved_session,
    get_cookie_jar_path,
    get_session_profile_dir,
    has_saved_cookies,
    load_linkedin_cookies,
    save_linkedin_cookies,
)


class FakeDriver:
    '''Minimal stand-in for the bits of Selenium's driver that session.py uses.'''

    def __init__(self, cookies=None, raises_on_get=False, rejects=()):
        self._cookies = cookies if cookies is not None else []
        self._raises_on_get = raises_on_get
        self._rejects = rejects
        self.added = []

    def get_cookies(self):
        if self._raises_on_get:
            raise RuntimeError("no such window")
        return self._cookies

    def add_cookie(self, cookie):
        if cookie["name"] in self._rejects:
            raise ValueError("invalid cookie domain")
        self.added.append(cookie)


def li_at_cookie(expiry=None, domain=".linkedin.com"):
    return {
        "name": "li_at", "value": "AQEDAT123", "domain": domain, "path": "/",
        "secure": True, "httpOnly": True, "expiry": expiry,
        "sameSite": "no_restriction",
    }


@pytest.fixture
def jar(tmp_path, monkeypatch):
    '''Point the cookie jar at a temp folder for the duration of a test.'''
    path = tmp_path / "session" / "linkedin_cookies.json"
    monkeypatch.setattr(session, "get_cookie_jar_path", lambda: str(path))
    monkeypatch.setattr(session, "_PROJECT_ROOT", str(tmp_path))
    return path


@pytest.fixture(autouse=True)
def keep_session_on(monkeypatch):
    '''The persistence layer is on unless a test says otherwise.'''
    monkeypatch.setattr(session, "keep_login_session", True)


def read_jar(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------- domain filtering ------------------------------
@pytest.mark.parametrize("domain, expected", [
    ("linkedin.com", True),
    (".linkedin.com", True),
    ("www.linkedin.com", True),
    ("LIKE.APP.LINKEDIN.COM", True),
    ("notlinkedin.com", False),          # suffix must be a real subdomain
    ("linkedin.com.evil.com", False),
    ("google.com", False),
    ("", False),
])
def test_is_linkedin_domain(domain, expected):
    assert _is_linkedin_domain(domain) is expected


# -------------------------------- saving -----------------------------------
def test_save_writes_only_linkedin_cookies(jar):
    driver = FakeDriver([
        li_at_cookie(),
        {"name": "sid", "value": "x", "domain": ".example.com", "path": "/", "secure": False, "httpOnly": False},
    ])

    assert save_linkedin_cookies(driver) is True
    saved = read_jar(jar)
    assert [c["name"] for c in saved] == ["li_at"]


def test_save_gives_session_cookies_a_future_expiry(jar):
    """The whole point: a cookie with no expiry dies when Chrome closes."""
    assert save_linkedin_cookies(FakeDriver([li_at_cookie(expiry=None)])) is True

    cookie = read_jar(jar)[0]
    assert cookie["expiry"] > int(time.time())


def test_save_keeps_an_existing_expiry(jar):
    expiry = int(time.time()) + 12345
    assert save_linkedin_cookies(FakeDriver([li_at_cookie(expiry=expiry)])) is True

    assert read_jar(jar)[0]["expiry"] == expiry


def test_save_drops_same_site(jar):
    """Selenium hands back raw Chrome values that add_cookie() would reject."""
    assert save_linkedin_cookies(FakeDriver([li_at_cookie()])) is True

    assert "sameSite" not in read_jar(jar)[0]


def test_save_accepts_liap_as_the_auth_cookie(jar):
    assert save_linkedin_cookies(FakeDriver([
        {"name": "liap", "value": "y", "domain": ".linkedin.com", "path": "/",
         "secure": True, "httpOnly": True},
    ])) is True


def test_save_refuses_to_overwrite_a_good_jar_with_a_logged_out_one(jar):
    """Without this, a failed login would wipe the session the user relies on."""
    assert save_linkedin_cookies(FakeDriver([li_at_cookie()])) is True
    before = read_jar(jar)

    logged_out = FakeDriver([
        {"name": "JSESSIONID", "value": "x", "domain": ".linkedin.com", "path": "/",
         "secure": True, "httpOnly": True},
    ])
    assert save_linkedin_cookies(logged_out) is False
    assert read_jar(jar) == before


def test_save_skips_malformed_cookies_instead_of_failing(jar):
    driver = FakeDriver([{"name": "broken"}, li_at_cookie()])

    assert save_linkedin_cookies(driver) is True
    assert [c["name"] for c in read_jar(jar)] == ["li_at"]


def test_save_survives_a_dead_browser(jar):
    assert save_linkedin_cookies(FakeDriver(raises_on_get=True)) is False
    assert not jar.exists()


def test_save_returns_false_when_disabled(jar, monkeypatch):
    monkeypatch.setattr(session, "keep_login_session", False)
    assert save_linkedin_cookies(FakeDriver([li_at_cookie()])) is False
    assert not jar.exists()


def test_save_leaves_no_temp_file_behind(jar):
    save_linkedin_cookies(FakeDriver([li_at_cookie()]))
    assert not os.path.exists(str(jar) + ".tmp")


# -------------------------------- loading -----------------------------------
def test_load_restores_the_auth_cookie(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([li_at_cookie(expiry=int(time.time()) + 600)]), encoding="utf-8")

    driver = FakeDriver()
    assert load_linkedin_cookies(driver) is True
    assert [c["name"] for c in driver.added] == ["li_at"]


def test_load_skips_expired_cookies(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([li_at_cookie(expiry=int(time.time()) - 10)]), encoding="utf-8")

    driver = FakeDriver()
    assert load_linkedin_cookies(driver) is False
    assert driver.added == []


def test_load_keeps_cookies_with_no_expiry(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([li_at_cookie(expiry=None)]), encoding="utf-8")

    driver = FakeDriver()
    assert load_linkedin_cookies(driver) is True


def test_load_passes_only_supported_keys(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([li_at_cookie(expiry=int(time.time()) + 600)]), encoding="utf-8")

    driver = FakeDriver()
    load_linkedin_cookies(driver)
    # sameSite is the value that historically makes add_cookie() throw.
    assert "sameSite" not in driver.added[0]
    assert set(driver.added[0]) == {"name", "value", "domain", "path", "secure", "httpOnly", "expiry"}


def test_load_ignores_foreign_domains_in_the_jar(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([
        {"name": "tracker", "value": "x", "domain": ".evil.com", "path": "/"},
        li_at_cookie(expiry=int(time.time()) + 600),
    ]), encoding="utf-8")

    driver = FakeDriver()
    assert load_linkedin_cookies(driver) is True
    assert [c["name"] for c in driver.added] == ["li_at"]


def test_load_continues_past_a_rejected_cookie(jar):
    """One bad cookie must not cost us the auth cookie after it."""
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([
        {"name": "JSESSIONID", "value": "x", "domain": ".linkedin.com", "path": "/"},
        li_at_cookie(expiry=int(time.time()) + 600),
    ]), encoding="utf-8")

    driver = FakeDriver(rejects={"JSESSIONID"})
    assert load_linkedin_cookies(driver) is True
    assert [c["name"] for c in driver.added] == ["li_at"]


def test_load_returns_false_when_no_jar_exists(jar):
    assert load_linkedin_cookies(FakeDriver()) is False


def test_load_survives_a_corrupt_jar(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text("{ this is not json", encoding="utf-8")

    assert load_linkedin_cookies(FakeDriver()) is False


def test_load_ignores_a_jar_that_is_not_a_list(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps({"li_at": "AQEDAT"}), encoding="utf-8")

    assert load_linkedin_cookies(FakeDriver()) is False


def test_load_returns_false_when_disabled(jar, monkeypatch):
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([li_at_cookie(expiry=int(time.time()) + 600)]), encoding="utf-8")
    monkeypatch.setattr(session, "keep_login_session", False)

    assert load_linkedin_cookies(FakeDriver()) is False


# ----------------------------- has_saved_cookies ----------------------------
def test_has_saved_cookies_reflects_the_jar(jar):
    assert has_saved_cookies() is False

    save_linkedin_cookies(FakeDriver([li_at_cookie()]))
    assert has_saved_cookies() is True


def test_has_saved_cookies_is_false_for_an_empty_jar(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text("[]", encoding="utf-8")
    assert has_saved_cookies() is False


def test_has_saved_cookies_survives_a_corrupt_jar(jar):
    jar.parent.mkdir(parents=True)
    jar.write_text("not json at all", encoding="utf-8")
    assert has_saved_cookies() is False


# -------------------------------- round trip --------------------------------
def test_saved_cookies_can_be_restored_unchanged(jar):
    original = li_at_cookie()
    save_linkedin_cookies(FakeDriver([original]))

    driver = FakeDriver()
    assert load_linkedin_cookies(driver) is True
    assert driver.added[0]["value"] == original["value"]


def test_clear_forgets_the_jar(jar):
    save_linkedin_cookies(FakeDriver([li_at_cookie()]))
    clear_saved_session()
    assert has_saved_cookies() is False


def test_clear_on_a_missing_jar_is_harmless(jar):
    clear_saved_session()  # must not raise


# ----------------------------- profile folder ------------------------------
def test_session_profile_dir_is_absolute_and_created(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "session_profile_dir", str(tmp_path / "custom-profile"))

    path = get_session_profile_dir()
    assert os.path.isabs(path)
    assert os.path.isdir(path)


def test_session_profile_dir_defaults_outside_the_project(monkeypatch):
    """It must never land in a git repo - it holds live auth tokens."""
    monkeypatch.setattr(session, "session_profile_dir", "")
    path = os.path.normcase(os.path.abspath(get_session_profile_dir()))

    assert not path.startswith(os.path.normcase(os.path.abspath(session._PROJECT_ROOT)))


def test_session_profile_dir_is_not_the_live_chrome_profile(monkeypatch):
    """Attaching to a running Chrome's profile is what broke session reuse."""
    from modules.helpers import find_default_profile_directory

    live = find_default_profile_directory()
    if not live:
        pytest.skip("no Chrome profile found on this machine")

    monkeypatch.setattr(session, "session_profile_dir", "")
    assert os.path.normcase(os.path.abspath(get_session_profile_dir())) != os.path.normcase(os.path.abspath(live))


def test_blank_profile_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setattr(session, "session_profile_dir", "   ")
    assert get_session_profile_dir() == session._default_profile_dir()


def test_get_default_temp_profile_has_no_embedded_flag():
    """It used to return '--user-data-dir=...' which the caller wrapped twice."""
    from modules.helpers import get_default_temp_profile

    profile = get_default_temp_profile()
    assert "--user-data-dir" not in profile
    assert os.path.isabs(profile)


# --------------------------------- expiry -----------------------------------
def test_future_expiry_is_ahead_of_now():
    assert _future_expiry() > int(time.time())


def test_cookie_jar_path_is_inside_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "_PROJECT_ROOT", str(tmp_path))
    assert get_cookie_jar_path().startswith(os.path.abspath(tmp_path))