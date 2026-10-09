"""
fact_store.py - the memory behind trusted_facts.csv

Columns: fact, label (REAL/FAKE), score, source, added, trained

source tells HOW MUCH the row can be trusted:
    seed    facts you wrote yourself                       -> used for meaning checks
    manual  you corrected a result with /real or /fake      -> used for meaning checks + training
    web     verified by live web search                     -> used for meaning checks + training
    fact    derived from an existing trusted fact           -> saved result only (fast repeat answers)
    model   predicted by the classifiers alone              -> saved result only (fast repeat answers)

Only seed/manual/web rows are ever used as "evidence", so a wrong model guess
can never become a "trusted fact" and poison later predictions.
"""
import csv
import datetime
import os
import re

import db
from predict_models import clean_text

COLUMNS = ["fact", "label", "score", "source", "added", "trained"]
SEMANTIC_SOURCES = {"seed", "manual", "web"}      # usable as evidence
TRAINING_SOURCES = {"manual", "web"}              # usable for retraining


def normalize_key(text: str) -> str:
    t = clean_text(text).lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip(" .!?؟۔،,;:\"'“”‘’")


def _doc(row):
    """The MongoDB version of one trusted-facts row."""
    try:
        score = float(row["score"])
    except (TypeError, ValueError):
        score = 1.0
    return {"key": normalize_key(row["fact"]), "fact": row["fact"], "label": row["label"],
            "score": score, "source": row["source"], "added": row["added"], "trained": row["trained"]}


class FactStore:
    def __init__(self, path):
        self.path = path
        self.rows = []
        self.index = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    fact = (r.get("fact") or "").strip()
                    if not fact:
                        continue
                    label = (r.get("label") or "REAL").strip().upper()
                    self.rows.append({
                        "fact": fact,
                        "label": label if label in ("REAL", "FAKE") else "REAL",
                        "score": (r.get("score") or "1.0").strip(),
                        "source": (r.get("source") or "seed").strip().lower(),
                        "added": (r.get("added") or "").strip(),
                        "trained": (r.get("trained") or "").strip(),
                    })
        self.index = {normalize_key(r["fact"]): i for i, r in enumerate(self.rows)}

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                w.writeheader()
                w.writerows(self.rows)
            os.replace(tmp, self.path)
            return True
        except PermissionError:          # file open in Excel
            return False

    def lookup(self, text):
        i = self.index.get(normalize_key(text))
        return dict(self.rows[i]) if i is not None else None

    def add(self, text, label, score, source):
        """Add or update a row. A manual correction is never overwritten by automatic ones."""
        key = normalize_key(text)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        i = self.index.get(key)
        if i is not None:
            if self.rows[i]["source"] == "manual" and source != "manual":
                return i
            self.rows[i].update({"label": label, "score": f"{float(score):.4f}",
                                 "source": source, "added": now, "trained": ""})
        else:
            self.rows.append({"fact": text.strip(), "label": label, "score": f"{float(score):.4f}",
                              "source": source, "added": now, "trained": ""})
            i = len(self.rows) - 1
            self.index[key] = i
        self.save()
        db.upsert_fact(_doc(self.rows[i]))           # extra copy in MongoDB (ignored if unavailable)
        return i

    def delete(self, index):
        """Remove one row by position. Returns True if it existed."""
        if not 0 <= index < len(self.rows):
            return False
        removed = self.rows.pop(index)
        db.delete_fact(normalize_key(removed["fact"]))
        self.index = {normalize_key(r["fact"]): i for i, r in enumerate(self.rows)}
        self.save()
        return True

    def mongo_docs(self):
        return [_doc(r) for r in self.rows]

    def semantic_rows(self):
        return [(normalize_key(r["fact"]), r["fact"], r["label"])
                for r in self.rows if r["source"] in SEMANTIC_SOURCES]

    def training_rows(self):
        return [r for r in self.rows if r["source"] in TRAINING_SOURCES and r["trained"] != "yes"]

    def mark_trained(self, facts):
        keys = {normalize_key(f) for f in facts}
        for r in self.rows:
            if normalize_key(r["fact"]) in keys:
                r["trained"] = "yes"
        self.save()
        db.mark_facts_trained(keys)