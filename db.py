"""
db.py - optional MongoDB mirror for the project

The local files (history.csv, trusted_facts.csv, accounts.json) stay the MAIN storage. MongoDB is an
EXTRA copy: every time the app saves something, it is also written to MongoDB. If MongoDB is not
installed, not running, or pymongo is missing, nothing breaks: the app keeps using the local files.

Database : fake_news_db   (change with the environment variable MONGO_DB)
Server   : mongodb://localhost:27017   (change with the environment variable MONGO_URI)

Collections
    history        one document per signed-in user's prediction (soft-deleted when removed from History)
    trusted_facts  one document per trusted fact / saved result (never deleted by the website)
    users          email, password hash, sign-up date/time, last sign-in, number of sign-ins
    auth_events    every sign-up and sign-in with its date/time
    feedback       stars + comment given when a signed-in user closes the application
"""
import datetime
import os
import time

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "fake_news_db")
RETRY_SECONDS = 15                  # after a failure, do not try to reconnect more often than this

_db = None
_last_try = 0.0
_last_error = ""


def get_db():
    """Return the database, or None if MongoDB is not available. Never raises."""
    global _db, _last_try, _last_error
    if _db is not None:
        return _db
    if _last_try and time.time() - _last_try < RETRY_SECONDS:
        return None
    _last_try = time.time()
    try:
        from pymongo import ASCENDING, MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000, socketTimeoutMS=5000)
        client.admin.command("ping")
        db = client[DB_NAME]
        db.history.create_index([("added_at", ASCENDING)])
        db.history.create_index([("csv_id", ASCENDING), ("added", ASCENDING)])
        db.history.create_index([("label", ASCENDING)])
        db.history.create_index([("user_email", ASCENDING)])
        db.trusted_facts.create_index([("key", ASCENDING)], unique=True)
        db.users.create_index([("email", ASCENDING)], unique=True)
        db.auth_events.create_index([("email", ASCENDING), ("type", ASCENDING), ("when", ASCENDING)])
        db.feedback.create_index([("id", ASCENDING)])
        db.feedback.create_index([("email", ASCENDING)])
        _db, _last_error = db, ""
        return _db
    except Exception as e:
        _last_error = f"{type(e).__name__}: {str(e)[:120]}"
        return None


def _run(fn):
    """Run fn(db). Returns True on success, False if MongoDB is unavailable or the call failed."""
    global _db, _last_try, _last_error
    db = get_db()
    if db is None:
        return False
    try:
        fn(db)
        return True
    except Exception as e:                 # connection lost: forget it, retry later
        _db, _last_try = None, time.time()
        _last_error = f"{type(e).__name__}: {str(e)[:120]}"
        return False


# ------------------------------------------------------------------ history
def upsert_history(doc):
    def go(db):
        db.history.update_one({"csv_id": doc["csv_id"], "added": doc["added"]},
                              {"$set": doc, "$setOnInsert": {"deleted": False}}, upsert=True)
    return _run(go)


def mark_history_deleted(csv_id, added):
    """Soft delete: the document stays in MongoDB, flagged deleted."""
    def go(db):
        db.history.update_one({"csv_id": csv_id, "added": added},
                              {"$set": {"deleted": True,
                                        "deleted_at": datetime.datetime.now().astimezone()}})
    return _run(go)


# ------------------------------------------------------------ trusted facts
def upsert_fact(doc):
    return _run(lambda db: db.trusted_facts.update_one({"key": doc["key"]}, {"$set": doc}, upsert=True))


def delete_fact(key):
    return _run(lambda db: db.trusted_facts.delete_one({"key": key}))


def mark_facts_trained(keys):
    keys = list(keys)
    return _run(lambda db: db.trusted_facts.update_many({"key": {"$in": keys}}, {"$set": {"trained": "yes"}}))


# ------------------------------------------------- accounts / events / feedback
def upsert_user(doc):
    return _run(lambda db: db.users.update_one({"email": doc["email"]}, {"$set": doc}, upsert=True))


def upsert_event(doc):
    return _run(lambda db: db.auth_events.update_one(
        {"email": doc["email"], "type": doc["type"], "when": doc["when"]}, {"$set": doc}, upsert=True))


def upsert_feedback(doc):
    return _run(lambda db: db.feedback.update_one({"id": doc["id"], "email": doc["email"]},
                                                  {"$set": doc}, upsert=True))


# --------------------------------------------------- bulk copy + status page
def sync(history_docs, fact_docs, user_docs=(), event_docs=(), feedback_docs=()):
    """Copy everything currently in the local files into MongoDB (safe to run many times)."""
    result = {"history": 0, "facts": 0, "users": 0, "events": 0, "feedback": 0}

    def go(db):
        from pymongo import UpdateOne
        if history_docs:
            db.history.bulk_write([
                UpdateOne({"csv_id": d["csv_id"], "added": d["added"]},
                          {"$set": d, "$setOnInsert": {"deleted": False}}, upsert=True)
                for d in history_docs], ordered=False)
            result["history"] = len(history_docs)
        if fact_docs:
            db.trusted_facts.bulk_write([
                UpdateOne({"key": d["key"]}, {"$set": d}, upsert=True) for d in fact_docs], ordered=False)
            result["facts"] = len(fact_docs)
        if user_docs:
            db.users.bulk_write([
                UpdateOne({"email": d["email"]}, {"$set": d}, upsert=True) for d in user_docs], ordered=False)
            result["users"] = len(user_docs)
        if event_docs:
            db.auth_events.bulk_write([
                UpdateOne({"email": d["email"], "type": d["type"], "when": d["when"]}, {"$set": d}, upsert=True)
                for d in event_docs], ordered=False)
            result["events"] = len(event_docs)
        if feedback_docs:
            db.feedback.bulk_write([
                UpdateOne({"id": d["id"], "email": d["email"]}, {"$set": d}, upsert=True)
                for d in feedback_docs], ordered=False)
            result["feedback"] = len(feedback_docs)

    return _run(go), result


def status(user_email=None):
    """Connection status for the Settings page. Counts and records are limited to this user's own
    predictions, and no email / password / personal detail is ever returned."""
    shown = MONGO_URI.split("@")[-1]          # never show a password if one is in the URI
    db = get_db()
    if db is None:
        return {"connected": False, "uri": shown, "database": DB_NAME, "error": _last_error}
    out = {"connected": True, "uri": shown, "database": DB_NAME}
    mine = {"user_email": user_email} if user_email else {}

    def go(d):
        out["history"] = d.history.count_documents({**mine, "deleted": {"$ne": True}})
        out["history_deleted"] = d.history.count_documents({**mine, "deleted": True})
        out["trusted_facts"] = d.trusted_facts.count_documents({})
        recent = d.history.find({**mine, "deleted": {"$ne": True}}).sort("added_at", -1).limit(5)
        out["recent"] = [{"text": r.get("text", ""), "label": r.get("label", ""),
                          "score": r.get("score", 0), "language": r.get("language", ""),
                          "added": r.get("added", "")} for r in recent]

    if not _run(go):
        return {"connected": False, "uri": shown, "database": DB_NAME, "error": _last_error}
    return out