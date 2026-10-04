'''
Persistent login session support.

Problem this solves: the bot used to point Chrome at your *real* Chrome profile
(`%LOCALAPPDATA%\\Google\\Chrome\\User Data`) via `--user-data-dir`. Chrome locks
that directory while it is running, so ChromeDriver failed to start, the code
silently retried with **no** profile at all, and every single run began from a
brand new throwaway session that required a manual login.

The fix mirrors the approach the Wellfound/InstaHyre applier uses: give the tool
its *own* browser profile directory that no other running Chrome ever locks.

Two independent layers, so a login survives even if one of them is wiped:

  1. **Browser profile** - a dedicated `--user-data-dir`. Chrome natively writes
     cookies/localStorage there, so the session is reused across runs.
  2. **Cookie jar** - `session/linkedin_cookies.json`. LinkedIn's `li_at` cookie
     is a *session* cookie unless "Keep me signed in" is ticked, and session
     cookies are dropped whenever Chrome closes. Exporting them lets us restore
     the login even in that case.

Nothing here is allowed to raise: a failure to persist a session must never take
down an application run.
'''

import json
import os
import pathlib
import time

from config.settings import keep_login_session, session_profile_dir
from modules.helpers import print_lg


# Only cookies for this domain are stored; anything else is noise.
_COOKIE_DOMAIN = "linkedin.com"

# Where the exported cookie jar lives, relative to the project root.
_COOKIE_JAR_RELATIVE_PATH = os.path.join("session", "linkedin_cookies.json")

# Session cookies (no expiry) get this many days added so Chrome and our own jar
# both keep them across restarts. LinkedIn invalidates the token server-side
# regardless, so this is purely about surviving a browser restart.
_SESSION_COOKIE_LIFETIME_DAYS = 180

# `sameSite` is deliberately never written back out. Selenium has returned
# Chrome's raw values ("no_restriction", "unspecified", ...) from get_cookies()
# across versions, and feeding those straight back into add_cookie() throws.
# Authentication does not need it.
_RESTORE_COOKIE_KEYS = ("name", "value", "path", "domain", "secure", "httpOnly", "expiry")

# At least one of these must be present for the cookies to represent a real
# login. `li_at` is the auth token; `liap` is the extra long-lived token LinkedIn
# issues when "Keep me signed in" is ticked. Saving without one would overwrite a
# good jar with a logged-out one and cost the user their remembered session.
_AUTH_COOKIE_NAMES = frozenset({"li_at", "liap"})


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_profile_dir() -> str:
    '''The tool's own Chrome profile, kept in the home folder and outside any repo.'''
    return str(pathlib.Path.home() / ".auto-job-apply" / "browser-profile")


def get_session_profile_dir() -> str:
    '''
    Absolute path to the dedicated Chrome profile used to keep the LinkedIn
    login alive between runs. Created if it doesn't exist yet.

    This is deliberately NOT your normal Chrome profile: sharing it means
    fighting Chrome's profile lock whenever Chrome happens to be open.
    '''
    path = os.path.abspath(os.path.expanduser(session_profile_dir.strip() or _default_profile_dir()))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        print_lg(f"Couldn't create the browser profile folder '{path}': {e}")
    return path


def get_cookie_jar_path() -> str:
    '''Absolute path to the exported LinkedIn cookie jar.'''
    return os.path.join(_PROJECT_ROOT, _COOKIE_JAR_RELATIVE_PATH)


def _is_linkedin_domain(domain: str) -> bool:
    '''True for `linkedin.com` itself and any of its subdomains.'''
    domain = (domain or "").lstrip(".").lower()
    return domain == _COOKIE_DOMAIN or domain.endswith("." + _COOKIE_DOMAIN)


def _future_expiry() -> int:
    '''A timestamp far enough ahead to survive browser restarts.'''
    return int(time.time() + _SESSION_COOKIE_LIFETIME_DAYS * 24 * 60 * 60)


def has_saved_cookies() -> bool:
    '''True if a usable cookie jar has been saved on a previous run.'''
    if not keep_login_session:
        return False
    try:
        with open(get_cookie_jar_path(), "r", encoding="utf-8") as file:
            return bool(json.load(file))
    except (OSError, ValueError):
        return False


def save_linkedin_cookies(driver) -> bool:
    '''
    Write the browser's current LinkedIn cookies to disk so the next run can log
    in without asking. Cookies without an expiry (session cookies such as
    `li_at`) are given one, otherwise they'd be dropped the moment Chrome exits.

    Returns True if anything was written. Never raises.
    '''
    if not keep_login_session:
        return False
    try:
        raw_cookies = driver.get_cookies()
    except Exception as e:
        print_lg(f"Couldn't read cookies from the browser: {e}")
        return False

    cookies = []
    for cookie in raw_cookies or []:
        try:
            if not _is_linkedin_domain(cookie.get("domain", "")):
                continue
            saved = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path") or "/",
                "secure": bool(cookie.get("secure", False)),
                "httpOnly": bool(cookie.get("httpOnly", False)),
            }
            expiry = cookie.get("expiry")
            saved["expiry"] = int(expiry) if expiry else _future_expiry()
            cookies.append(saved)
        except Exception as e:
            print_lg(f"Skipping a malformed cookie: {e}")

    if not cookies:
        return False
    if not any(cookie["name"] in _AUTH_COOKIE_NAMES for cookie in cookies):
        print_lg("Not signed in to LinkedIn, so the saved login was left untouched.")
        return False

    jar_path = get_cookie_jar_path()
    try:
        os.makedirs(os.path.dirname(jar_path), exist_ok=True)
        # Write to a sibling temp file first so an interrupted write can never
        # leave a half-written jar behind that breaks the next login.
        tmp_path = jar_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(cookies, file, indent=2)
        os.replace(tmp_path, jar_path)
        try:
            os.chmod(jar_path, 0o600)  # the jar holds live auth tokens
        except OSError:
            pass
    except OSError as e:
        print_lg(f"Couldn't save the login session to '{jar_path}': {e}")
        return False

    print_lg(f"Saved {len(cookies)} LinkedIn cookies for the next run.")
    return True


def load_linkedin_cookies(driver) -> bool:
    '''
    Re-apply a previously saved cookie jar to the browser. Call this only while
    sitting on a linkedin.com page - Selenium refuses cookies for a domain the
    browser isn't currently on.

    Returns True if cookies were applied. Never raises.
    '''
    if not keep_login_session:
        return False
    jar_path = get_cookie_jar_path()
    try:
        with open(jar_path, "r", encoding="utf-8") as file:
            saved_cookies = json.load(file)
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as e:
        print_lg(f"Ignoring the unreadable saved login session '{jar_path}': {e}")
        return False

    if not isinstance(saved_cookies, list):
        return False

    now = int(time.time())
    restored = 0
    for cookie in saved_cookies:
        try:
            if not _is_linkedin_domain(cookie.get("domain", "")):
                continue
            expiry = cookie.get("expiry")
            if expiry is not None and int(expiry) <= now:
                continue  # expired; LinkedIn would reject it anyway
            driver.add_cookie({key: cookie[key] for key in _RESTORE_COOKIE_KEYS if key in cookie})
            restored += 1
        except Exception as e:
            # A single rejected cookie isn't worth giving up over - `li_at` is
            # the one that matters and the rest are conveniences.
            print_lg(f"Couldn't restore the cookie '{cookie.get('name', '?')}': {e}")

    if restored:
        print_lg(f"Restored {restored} saved LinkedIn cookies.")
    return restored > 0


def clear_saved_session() -> None:
    '''
    Forget the exported cookie jar (but leave the browser profile alone, so a
    login held there survives). Useful when switching LinkedIn accounts or when
    a saved session goes stale and keeps getting rejected.
    '''
    try:
        os.remove(get_cookie_jar_path())
        print_lg("Forgot the saved LinkedIn login session.")
    except FileNotFoundError:
        pass
    except OSError as e:
        print_lg(f"Couldn't delete '{get_cookie_jar_path()}': {e}")