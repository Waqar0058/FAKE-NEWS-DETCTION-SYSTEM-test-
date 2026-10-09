"""
history_store.py - the WEBSITE history (history.csv)

This file is completely separate from trusted_facts.csv:
    history.csv        every prediction a SIGNED-IN user makes on the website (any score, REAL or FAKE).
                       Used by the History and Analytics pages. Each record belongs to one user, and a
                       user can only see / delete their own records. Deleting here does NOT touch
                       trusted_facts.csv. Guest predictions are not saved here.
    trusted_facts.csv  the system's memory / evidence. Never changed by the website's delete button.

Columns: id, text, label, score, language, method, added, user
"""
import csv
import datetime
import os
import threading

import db

COLUMNS = ["id", "text", "label", "score", "language", "method", "added", "user"]
RANGES = {"today": 1, "7": 7, "15": 15, "30": 30}      # range name -> number of calendar days
FMT = "%Y-%m-%d %H:%M:%S"


def _parse(value):
    try:
        return datetime.datetime.strptime(value, FMT)
    except (TypeError, ValueError):
        return None


def _doc(row):
    """The MongoDB version of one history row."""
    return {"csv_id": row["id"], "user_email": row.get("user", ""),
            "text": row["text"], "label": row["label"],
            "score": float(row["score"]), "language": row["language"], "method": row["method"],
            "added": row["added"],
            "added_at": row["dt"].astimezone() if row["dt"] else None}


class HistoryStore:
    def __init__(self, path):
        self.path = path
        self.rows = []                       # oldest -> newest
        self.lock = threading.RLock()
        self._load()

    # ---------------------------------------------------------------- storage
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        rid = int(r.get("id", ""))
                    except ValueError:
                        continue
                    text = (r.get("text") or "").strip()
                    if not text:
                        continue
                    try:
                        score = float(r.get("score") or 0)
                    except ValueError:
                        score = 0.0
                    label = (r.get("label") or "FAKE").strip().upper()
                    added = (r.get("added") or "").strip()
                    self.rows.append({
                        "id": rid, "text": text,
                        "label": label if label in ("REAL", "FAKE") else "FAKE",
                        "score": score,
                        "language": (r.get("language") or "").strip().lower(),
                        "method": (r.get("method") or "").strip(),
                        "added": added, "dt": _parse(added),
                        "user": (r.get("user") or "").strip().lower(),   # old rows have no owner
                    })
        self.next_id = max((r["id"] for r in self.rows), default=0) + 1

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
                w.writeheader()
                for r in self.rows:
                    w.writerow({**r, "score": f"{r['score']:.4f}"})
            os.replace(tmp, self.path)
            return True
        except PermissionError:              # file open in Excel
            return False

    # ------------------------------------------------------------- operations
    def add(self, text, label, score, language, method, user):
        """Save one prediction for a signed-in user. Returns (row, saved_to_disk)."""
        with self.lock:
            now = datetime.datetime.now().replace(microsecond=0)
            row = {"id": self.next_id, "text": text.strip(), "label": label,
                   "score": float(score), "language": language, "method": method,
                   "added": now.strftime(FMT), "dt": now, "user": user}
            self.next_id += 1
            self.rows.append(row)
            saved = self._save()
            db.upsert_history(_doc(row))             # extra copy in MongoDB (ignored if unavailable)
            return row, saved

    def delete(self, rid, user):
        """Remove one of THIS user's history records (only from history.csv). Returns True if it existed."""
        with self.lock:
            for i, r in enumerate(self.rows):
                if r["id"] == rid and r["user"] == user:
                    self.rows.pop(i)
                    self._save()
                    db.mark_history_deleted(r["id"], r["added"])   # soft delete in MongoDB
                    return True
            return False

    def mongo_docs(self):
        with self.lock:
            return [_doc(r) for r in self.rows]

    @staticmethod
    def _start(rng, now):
        if rng not in RANGES:
            return None                      # "all"
        start = now - datetime.timedelta(days=RANGES[rng] - 1)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def _in_range(self, rng, user):
        start = self._start(rng, datetime.datetime.now())
        rows = reversed(self.rows)           # newest first
        return [r for r in rows
                if r["user"] == user and (start is None or (r["dt"] and r["dt"] >= start))]

    def list(self, rng, user):
        with self.lock:
            return [{k: r[k] for k in ("id", "text", "label", "score", "language", "method", "added")}
                    for r in self._in_range(rng, user)]

    def analytics(self, rng, user):
        with self.lock:
            rows = self._in_range(rng, user)
            now = datetime.datetime.now()
            total = len(rows)
            real = sum(1 for r in rows if r["label"] == "REAL")

            # ---- timeline buckets: hourly for "today", daily otherwise
            if rng == "today":
                keys = [f"{h:02d}:00" for h in range(24)]
                timeline = {k: {"label": k, "real": 0, "fake": 0} for k in keys}
                for r in rows:
                    k = f"{r['dt'].hour:02d}:00"
                    timeline[k]["real" if r["label"] == "REAL" else "fake"] += 1
            else:
                days = RANGES.get(rng, 30)
                start = self._start(rng if rng in RANGES else "30", now)
                keys = [(start + datetime.timedelta(days=i)).strftime("%m-%d") for i in range(days)]
                timeline = {k: {"label": k, "real": 0, "fake": 0} for k in keys}
                for r in rows:
                    k = r["dt"].strftime("%m-%d")
                    if k in timeline:
                        timeline[k]["real" if r["label"] == "REAL" else "fake"] += 1

            # ---- confidence buckets (score is always 0.5 - 1.0)
            edges = ["50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
            score_counts = [0] * 5
            for r in rows:
                score_counts[min(4, max(0, int((r["score"] - 0.5) * 10)))] += 1

            return {
                "range": rng,
                "total": total, "real": real, "fake": total - real,
                "avg_score": (sum(r["score"] for r in rows) / total) if total else 0,
                "languages": {"english": sum(1 for r in rows if r["language"] == "english"),
                              "urdu": sum(1 for r in rows if r["language"] == "urdu")},
                "timeline": [timeline[k] for k in keys],
                "scores": [{"label": e, "count": c} for e, c in zip(edges, score_counts)],
            }