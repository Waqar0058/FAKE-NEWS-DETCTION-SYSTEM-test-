"""
auth_store.py - accounts for the website (sign up / sign in / feedback)

Everything is saved in accounts.json (main copy) and mirrored to MongoDB (extra copy),
exactly like history.csv and trusted_facts.csv.

MongoDB collections written from here
    users        email, password_hash, created (sign-up date/time), last_login, login_count
    auth_events  one document for every sign-up and every sign-in: email, type, date/time
    feedback     email, rating (1-5 stars), comment, date/time

Passwords are NEVER stored as plain text. They are stored as a salted PBKDF2-SHA256 hash,
so even someone who opens the database cannot read them.

Login sessions use signed tokens (HMAC). The signing key is kept in secret.key
(created automatically the first time). Keep accounts.json and secret.key private.
"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

import db

FMT = "%Y-%m-%d %H:%M:%S"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PBKDF2_ROUNDS = 200_000
MIN_PASSWORD = 8
MAX_PASSWORD = 128
MAX_COMMENT = 500
TOKEN_DAYS = 1           # normal sign-in lasts 1 day
REMEMBER_DAYS = 30       # "Remember me" lasts 30 days


class AuthError(Exception):
    """Shown to the person on the website as a plain message."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- helpers
def _now():
    return datetime.datetime.now().replace(microsecond=0)


def _stamp(dt):
    return dt.strftime(FMT)


def _when(text):
    try:
        return datetime.datetime.strptime(text, FMT).astimezone()
    except (TypeError, ValueError):
        return None


def _hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def _check(password, stored):
    try:
        _, rounds, salt, good = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(dk.hex(), good)
    except Exception:
        return False


_DUMMY_HASH = _hash("not-a-real-password")      # used so unknown emails take the same time as wrong passwords


# ------------------------------------------------- MongoDB versions of rows
def user_doc(u):
    return {"email": u["email"], "password_hash": u["password_hash"],
            "created": u["created"], "created_at": _when(u["created"]),
            "last_login": u["last_login"], "last_login_at": _when(u["last_login"]),
            "login_count": u["login_count"]}


def event_doc(e):
    return {"email": e["email"], "type": e["type"], "when": e["when"], "at": _when(e["when"])}


def feedback_doc(f):
    return {"id": f["id"], "email": f["email"], "rating": f["rating"], "comment": f["comment"],
            "created": f["created"], "created_at": _when(f["created"])}


# ------------------------------------------------------------------ store
class AccountStore:
    def __init__(self, path, key_path):
        self.path = path
        self.lock = threading.RLock()
        self.secret = self._load_secret(key_path)
        self.data = {"users": [], "events": [], "feedback": []}
        self._load()

    # ---- storage
    @staticmethod
    def _load_secret(key_path):
        env = os.environ.get("FND_SECRET")
        if env:
            return env.encode("utf-8")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                key = f.read().strip()
            if key:
                return key
        key = secrets.token_hex(32).encode("utf-8")
        with open(key_path, "wb") as f:
            f.write(key)
        return key

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in self.data:
                    self.data[k] = list(loaded.get(k, []))
            except (OSError, ValueError):
                print("[warning] accounts.json could not be read; starting with no accounts.")

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def _find(self, email):
        return next((u for u in self.data["users"] if u["email"] == email), None)

    def _event(self, email, kind, when):
        ev = {"email": email, "type": kind, "when": _stamp(when)}
        self.data["events"].append(ev)
        db.upsert_event(event_doc(ev))

    # ---- tokens
    def make_token(self, email, remember=False):
        expires = int(time.time()) + (REMEMBER_DAYS if remember else TOKEN_DAYS) * 86400
        payload = base64.urlsafe_b64encode(f"{email}|{expires}".encode("utf-8")).decode().rstrip("=")
        sig = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def verify_token(self, token):
        """Return the email the token belongs to, or None if it is invalid / expired."""
        try:
            payload, sig = (token or "").split(".")
            good = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, good):
                return None
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
            email, expires = raw.rsplit("|", 1)
            if int(expires) < time.time():
                return None
            with self.lock:
                return email if self._find(email) else None
        except Exception:
            return None

    # ---- validation
    @staticmethod
    def clean_email(email):
        e = (email or "").strip().lower()
        if len(e) > 254 or not EMAIL_RE.match(e):
            raise AuthError("Please enter a valid email address.", 400)
        return e

    # ---- accounts
    def signup(self, email, password, confirm, remember=False):
        email = self.clean_email(email)
        password = password or ""
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.", 400)
        if len(password) > MAX_PASSWORD:
            raise AuthError("Password is too long.", 400)
        if password != (confirm or ""):
            raise AuthError("The two passwords do not match.", 400)
        with self.lock:
            if self._find(email):
                raise AuthError("An account with this email already exists. Please sign in.", 409)
            now = _now()
            user = {"email": email, "password_hash": _hash(password), "created": _stamp(now),
                    "last_login": _stamp(now), "login_count": 1}
            self.data["users"].append(user)
            self._event(email, "signup", now)
            self._event(email, "signin", now)            # signing up also signs the person in
            self._save()
            db.upsert_user(user_doc(user))
        return self.make_token(email, remember)

    def signin(self, email, password, remember=False):
        email = self.clean_email(email)
        with self.lock:
            user = self._find(email)
            stored = user["password_hash"] if user else _DUMMY_HASH
            if not _check(password or "", stored) or not user:
                raise AuthError("Incorrect email or password.", 401)
            now = _now()
            user["last_login"] = _stamp(now)
            user["login_count"] = int(user.get("login_count", 0)) + 1
            self._event(email, "signin", now)
            self._save()
            db.upsert_user(user_doc(user))
        return self.make_token(email, remember)

    # ---- feedback
    def add_feedback(self, email, rating, comment):
        comment = (comment or "").strip()
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = 0
        if not 0 <= rating <= 5:
            raise AuthError("Rating must be between 1 and 5 stars.", 400)
        if rating == 0 and not comment:
            raise AuthError("Please choose a star rating or write a short comment.", 400)
        if len(comment) > MAX_COMMENT:
            raise AuthError(f"The comment is too long (maximum {MAX_COMMENT} characters).", 400)
        with self.lock:
            fb = {"id": max((f["id"] for f in self.data["feedback"]), default=0) + 1,
                  "email": email, "rating": rating, "comment": comment, "created": _stamp(_now())}
            self.data["feedback"].append(fb)
            self._save()
            db.upsert_feedback(feedback_doc(fb))

    # ---- bulk copy to MongoDB
    def user_docs(self):
        with self.lock:
            return [user_doc(u) for u in self.data["users"]]

    def event_docs(self):
        with self.lock:
            return [event_doc(e) for e in self.data["events"]]

    def feedback_docs(self):
        with self.lock:
            return [feedback_doc(f) for f in self.data["feedback"]]
