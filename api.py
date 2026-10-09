"""
api.py - local web server (FastAPI) for the interface

    python api.py
    then open   http://localhost:5000   in Microsoft Edge or Google Chrome

It serves the pages in the  frontend/  folder and provides:

  Open to everyone (guests too)
    POST   /api/predict            {"text": "...", "language": "english|urdu"}
  Accounts
    POST   /api/auth/signup        {"email", "password", "confirm", "remember"}  -> {"token"}
    POST   /api/auth/signin        {"email", "password", "remember"}             -> {"token"}
    GET    /api/auth/check         is my token still valid?
    POST   /api/feedback           {"rating": 0-5, "comment": "..."}             (signed-in only)
  Signed-in users only  (header  Authorization: Bearer <token>)
    GET    /api/history?range=     all | today | 7 | 15 | 30   (the user's OWN records, newest first)
    DELETE /api/history/{id}       delete one of the user's records from the website history ONLY
    GET    /api/analytics?range=   today | 7 | 15 | 30         (numbers for the charts)
    GET    /api/mongo/status       MongoDB connection + the user's own record counts
    POST   /api/mongo/sync         copy everything in the local files into MongoDB
Automatic API documentation: http://localhost:5000/docs

Local files:
    history.csv         what the website shows (History + Analytics). Deleting a record deletes it here only.
    trusted_facts.csv   the system's memory. Every prediction is added here, and the website never deletes from it.
    accounts.json       users (password hashes), sign-in log and feedback. Keep it private.
MongoDB (optional, local) keeps an EXTRA copy of all of it. If it is not running, the local files still work.
"""
import os
import warnings

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
warnings.filterwarnings("ignore")

import contextlib
import sys
import threading
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import db
from auth_store import AccountStore, AuthError
from history_store import HistoryStore
from language_check import check_language

MAX_CHARS = 3000
PORT = 5000
VALID_RANGES = ("all", "today", "7", "15", "30")
history = HistoryStore(os.path.join(BASE_DIR, "history.csv"))
accounts = AccountStore(os.path.join(BASE_DIR, "accounts.json"), os.path.join(BASE_DIR, "secret.key"))


@contextlib.contextmanager
def quiet():
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


print("Loading models, please wait ...")
with quiet():
    from predict_context import ContextChecker
    checker = ContextChecker()
lock = threading.Lock()          # the models handle one request at a time


def sync_mongo():
    """Copy the local data into MongoDB. Returns (success, counts)."""
    return db.sync(history.mongo_docs(), checker.store.mongo_docs(), accounts.user_docs(),
                   accounts.event_docs(), accounts.feedback_docs())


_ok, _n = sync_mongo()
if _ok:
    print(f"MongoDB connected ({db.DB_NAME}): {_n['history']} history + {_n['facts']} facts + "
          f"{_n['users']} users + {_n['feedback']} feedback copied.")
else:
    print("MongoDB not available -> using the local files only. (Start MongoDB and restart to enable it.)")

app = FastAPI(title="Fake News Detection API")

# Allow pages served from localhost / 127.0.0.1 only (e.g. VS Code Live Server on port 5500)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class PredictIn(BaseModel):
    text: str = ""
    language: str = ""


class SignupIn(BaseModel):
    email: str = ""
    password: str = ""
    confirm: str = ""
    remember: bool = False


class SigninIn(BaseModel):
    email: str = ""
    password: str = ""
    remember: bool = False


class FeedbackIn(BaseModel):
    rating: int = 0
    comment: str = ""


def error(message, status):
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(AuthError)
async def auth_error_handler(request, exc):
    return error(exc.message, exc.status)


def clean_range(value):
    return value if value in VALID_RANGES else "all"


def _bearer(authorization):
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""


def optional_user(authorization: str = Header(default="")) -> Optional[str]:
    """No token = guest (None). A token that is wrong or expired = error."""
    if not authorization:
        return None
    email = accounts.verify_token(_bearer(authorization))
    if not email:
        raise AuthError("Your session has expired. Please sign in again.", 401)
    return email


def require_user(authorization: str = Header(default="")) -> str:
    email = accounts.verify_token(_bearer(authorization))
    if not email:
        raise AuthError("Please sign in to use this service.", 401)
    return email


# ------------------------------------------------------------------ accounts
@app.post("/api/auth/signup")
def signup(body: SignupIn):
    return {"token": accounts.signup(body.email, body.password, body.confirm, body.remember)}


@app.post("/api/auth/signin")
def signin(body: SigninIn):
    return {"token": accounts.signin(body.email, body.password, body.remember)}


@app.get("/api/auth/check")
def auth_check(user: str = Depends(require_user)):
    return {"ok": True}


@app.post("/api/feedback")
def feedback(body: FeedbackIn, user: str = Depends(require_user)):
    accounts.add_feedback(user, body.rating, body.comment)
    return {"ok": True}


# Plain "def" endpoints run in a worker thread, so the server stays responsive
# while the models are working.
@app.post("/api/predict")
def predict(body: PredictIn, user: Optional[str] = Depends(optional_user)):
    text = body.text.strip()
    language = body.language.strip().lower()

    if language not in ("english", "urdu"):
        return error("Please select a language first (English or Urdu).", 400)
    if not text:
        return error("Please enter some news text.", 400)
    if len(text) > MAX_CHARS:
        return error(f"Text is too long (maximum {MAX_CHARS} characters).", 400)

    ok, message = check_language(text, language)      # only English / Urdu are supported
    if not ok:
        return error(message, 400)

    try:
        with lock, quiet():
            r = checker.predict(text)                 # also saves the text into trusted_facts.csv
    except Exception as e:
        return error(f"Prediction failed: {str(e)[:150]}", 500)

    # Signed-in users: EVERY prediction goes to their history (any label, any score, even 51%).
    # Guests only get the answer; nothing is added to the website history.
    row, history_saved = None, True
    if user:
        row, history_saved = history.add(text, r["label"], r["score"], language, r["method"], user)
    return {"id": row["id"] if row else None, "label": r["label"], "score": r["score"],
            "language": language, "method": r["method"], "saved": r["saved"],
            "history_saved": history_saved}


@app.get("/api/history")
def get_history(range: str = "all", user: str = Depends(require_user)):
    return history.list(clean_range(range), user)


@app.delete("/api/history/{rid}")
def delete_record(rid: int, user: str = Depends(require_user)):
    # Only history.csv is changed. trusted_facts.csv is NOT touched.
    if not history.delete(rid, user):
        return error("Record not found.", 404)
    return {"ok": True}


@app.get("/api/analytics")
def get_analytics(range: str = "7", user: str = Depends(require_user)):
    rng = range if range in ("today", "7", "15", "30") else "7"
    return history.analytics(rng, user)


@app.get("/api/mongo/status")
def mongo_status(user: str = Depends(require_user)):
    return db.status(user)


@app.post("/api/mongo/sync")
def mongo_sync(user: str = Depends(require_user)):
    ok, counts = sync_mongo()
    if not ok:
        return error("MongoDB is not available. Start the MongoDB service and try again.", 503)
    return {"ok": True, "history": counts["history"], "facts": counts["facts"], "status": db.status(user)}


# The web pages. Mounted last so the /api routes above take priority.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    print(f"\nReady. Open  http://localhost:{PORT}  in Microsoft Edge or Google Chrome.")
    print("Press Ctrl+C to stop.\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")