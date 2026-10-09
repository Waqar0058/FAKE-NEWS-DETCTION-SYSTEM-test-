"""
predict_context.py
Context / meaning-aware fake-news prediction for English + Urdu, with memory.

Order of checks for every input:
  0. Saved result      : same news seen before -> instant answer, works offline
  1. Trusted facts     : meaning match + NLI against trusted_facts.csv
  2. Live web search   : only if no trusted fact matched (needs internet)
  3. Classifiers       : your BERT / XLM-R models (always part of the decision)
After a confident new result, it is saved to trusted_facts.csv automatically.
"""
import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import pandas as pd
import torch
import uvicorn
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from fact_store import SEMANTIC_SOURCES, FactStore, normalize_key
from predict_models import BASE_DIR, DEVICE, NewsClassifier, clean_text, detect_language

FACTS_CSV = os.path.join(BASE_DIR, "trusted_facts.csv")
EMBED_MODEL = "paraphrase-multilingual-mpnet-base-v2"
NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

TOP_K = 3
MIN_SIMILARITY = 0.45
MIN_NLI_CONF = 0.70
FACT_WEIGHT = 0.80

# ---- live web verification (only when no trusted fact matched) ----
USE_LIVE_SEARCH = True
LIVE_RESULTS = 8
LIVE_NLI_CONF = 0.60
LIVE_MIN_EVIDENCE = 1.0
LIVE_WEIGHT = 0.60
TRUSTED_DOMAINS = (
    "bbc.", "reuters.", "apnews.", "dawn.com", "thenews.com.pk", "geo.tv", "tribune.com.pk",
    "aljazeera.", "express.pk", "urdupoint.", "wikipedia.org", "britannica.com", ".gov", ".edu",
)

# ---- automatic saving ----
AUTO_SAVE = True
SAVE_MIN_SCORE = 0.0      # 0.0 = EVERY prediction is saved to trusted_facts.csv (even 51%)
EVIDENCE_MIN_SCORE = 0.80  # a web-verified result below this is saved as 'model' (never used as evidence)
# Your original training CSV files, so news that already exists in them is not saved again.
# Example: [("data/english.csv", "text"), ("data/urdu.csv", "text")]
DATASET_CSVS = []


class ContextChecker:
    def __init__(self, facts_csv=FACTS_CSV):
        self.classifier = NewsClassifier()
        self.store = FactStore(facts_csv)
        self.dataset_keys = self._load_dataset_keys()
        self.facts, self.fact_labels, self.sem_pos = [], [], {}
        self.fact_emb = None
        self.fact_ok = False
        try:
            self._load_helpers()
            for key, fact, label in self.store.semantic_rows():
                self.sem_pos[key] = len(self.facts)
                self.facts.append(fact)
                self.fact_labels.append(label)
            if self.facts:
                self.fact_emb = self.embedder.encode(self.facts, convert_to_tensor=True,
                                                     normalize_embeddings=True)
            self.fact_ok = True
        except Exception as e:
            print(f"[warning] meaning/fact layer disabled -> classifiers + saved results only. "
                  f"Reason: {str(e)[:200]}")

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _load_dataset_keys():
        keys = set()
        for path, col in DATASET_CSVS:
            try:
                p = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
                keys.update(normalize_key(t) for t in pd.read_csv(p)[col].astype(str))
            except Exception:
                pass
        return keys

    def _load_helpers(self):
        """Local cache first (fast, offline); download only if missing."""
        from sentence_transformers import SentenceTransformer
        last_error = None
        for local_only in (True, False):
            try:
                self.embedder = SentenceTransformer(EMBED_MODEL, device=str(DEVICE),
                                                    local_files_only=local_only)
                self.nli_tok = AutoTokenizer.from_pretrained(NLI_MODEL, local_files_only=local_only)
                self.nli = AutoModelForSequenceClassification.from_pretrained(
                    NLI_MODEL, local_files_only=local_only).to(DEVICE).eval()
                labels = {int(i): str(l).lower() for i, l in self.nli.config.id2label.items()}
                self.ent_i = next(i for i, l in labels.items() if "entail" in l)
                self.con_i = next(i for i, l in labels.items() if "contra" in l)
                return
            except Exception as e:
                last_error = e
        raise last_error

    # ------------------------------------------------------------- evidence
    @torch.no_grad()
    def _nli_batch(self, premises, hypotheses):
        enc = self.nli_tok(premises, hypotheses, truncation=True, max_length=256,
                           padding=True, return_tensors="pt").to(DEVICE)
        probs = torch.softmax(self.nli(**enc).logits, dim=-1).cpu().tolist()
        return [(p[self.ent_i], p[self.con_i]) for p in probs]

    def fact_check(self, text):
        if not self.fact_ok or not self.facts:
            return None
        from sentence_transformers import util
        q = self.embedder.encode(text, convert_to_tensor=True, normalize_embeddings=True)
        hits = [h for h in util.semantic_search(q, self.fact_emb, top_k=TOP_K)[0]
                if h["score"] >= MIN_SIMILARITY]
        if not hits:
            return None
        facts = [self.facts[h["corpus_id"]] for h in hits]
        labels = [self.fact_labels[h["corpus_id"]] for h in hits]
        n = len(facts)
        res = self._nli_batch(facts + [text] * n, [text] * n + facts)   # both directions
        best = None
        for i, h in enumerate(hits):
            ent = (res[i][0] + res[n + i][0]) / 2
            con = (res[i][1] + res[n + i][1]) / 2
            if labels[i] == "FAKE":                  # a known-false claim: only a match counts
                if ent < MIN_NLI_CONF:
                    continue
                cand = {"supports": False, "strength": ent}
            else:
                if max(ent, con) < MIN_NLI_CONF:
                    continue
                cand = {"supports": ent > con, "strength": max(ent, con)}
            cand.update({"fact": facts[i], "similarity": round(h["score"], 3),
                         "entailment": round(ent, 3), "contradiction": round(con, 3)})
            if best is None or cand["strength"] > best["strength"]:
                best = cand
        return best

    def live_check(self, text):
        if not (USE_LIVE_SEARCH and self.fact_ok):
            return None
        try:
            from live_search import web_snippets
            items = web_snippets(text, LIVE_RESULTS)
            if not items:
                return None
            premises = [f"{i['title']}. {i['body']}" for i in items]
            res = self._nli_batch(premises, [text] * len(premises))
            support = contradict = 0.0
            sources = []
            for item, (ent, con) in zip(items, res):
                w = 1.5 if any(d in item["url"] for d in TRUSTED_DOMAINS) else 1.0
                if ent >= LIVE_NLI_CONF and ent > con:
                    support += w * ent
                    sources.append((item["url"], "supports"))
                elif con >= LIVE_NLI_CONF and con > ent:
                    contradict += w * con
                    sources.append((item["url"], "contradicts"))
            total = support + contradict
            if total < LIVE_MIN_EVIDENCE:
                return None
            return {"real": support / total, "support": round(support, 2),
                    "contradict": round(contradict, 2), "sources": sources[:5]}
        except Exception:
            return None

    # --------------------------------------------------------------- memory
    def rebuild_semantic(self):
        """Re-read evidence rows from the store (used after a record is deleted)."""
        self.facts, self.fact_labels, self.sem_pos = [], [], {}
        self.fact_emb = None
        for key, fact, label in self.store.semantic_rows():
            self.sem_pos[key] = len(self.facts)
            self.facts.append(fact)
            self.fact_labels.append(label)
        if self.fact_ok and self.facts:
            self.fact_emb = self.embedder.encode(self.facts, convert_to_tensor=True,
                                                 normalize_embeddings=True)

    def _upsert_semantic(self, text, label):
        """Make a saved row usable as evidence immediately (no restart needed)."""
        if not self.fact_ok:
            return
        key = normalize_key(text)
        emb = self.embedder.encode(text, convert_to_tensor=True, normalize_embeddings=True)
        if key in self.sem_pos:
            i = self.sem_pos[key]
            self.fact_labels[i] = label
            self.fact_emb[i] = emb
        else:
            self.sem_pos[key] = len(self.facts)
            self.facts.append(text)
            self.fact_labels.append(label)
            self.fact_emb = emb.unsqueeze(0) if self.fact_emb is None \
                else torch.cat([self.fact_emb, emb.unsqueeze(0)])

    def _remember(self, text, label, score, source):
        self.store.add(text, label, score, source)
        if source in SEMANTIC_SOURCES:
            self._upsert_semantic(text, label)

    def correct(self, text, label):
        """User feedback: the ground truth. Saved as 'manual' (trusted + used for retraining)."""
        text = clean_text(text)
        self._remember(text, label.upper(), 1.0, "manual")

    # ----------------------------------------------------------- prediction
    def predict(self, text):
        text = clean_text(text)
        lang = detect_language(text)

        saved = self.store.lookup(text)
        if saved:                                             # step 0: instant + offline
            try:
                score = float(saved["score"])
            except ValueError:
                score = 1.0
            return {"text": text, "language": lang, "label": saved["label"], "score": round(score, 4),
                    "method": "saved result", "evidence": None, "live": None, "saved": False}

        clf = self.classifier.predict(text)
        clf_real = clf["real_prob"]
        evidence = self.fact_check(text)
        live = None if evidence else self.live_check(text)

        if evidence:
            fact_real = evidence["strength"] if evidence["supports"] else 1 - evidence["strength"]
            real_p = FACT_WEIGHT * fact_real + (1 - FACT_WEIGHT) * clf_real
            method, source = "fact-check + classifiers", "fact"
        elif live:
            real_p = LIVE_WEIGHT * live["real"] + (1 - LIVE_WEIGHT) * clf_real
            method, source = "live web search + classifiers", "web"
        else:
            real_p = clf_real
            method, source = "classifiers only (no matching trusted fact)", "model"

        label = "REAL" if real_p >= 0.5 else "FAKE"
        score = round(real_p if label == "REAL" else 1 - real_p, 4)

        saved_now = False
        if AUTO_SAVE and score >= SAVE_MIN_SCORE and normalize_key(text) not in self.dataset_keys:
            save_source = "model" if (source == "web" and score < EVIDENCE_MIN_SCORE) else source
            self._remember(text, label, score, save_source)
            saved_now = True

        return {"text": text, "language": lang, "label": label, "score": score,
                "real_prob": round(real_p, 4), "classifier_real_prob": clf_real,
                "models_used": clf["models_used"], "method": method,
                "evidence": evidence, "live": live, "saved": saved_now}


def show(r):
    """Detailed view (used only if you run this file directly)."""
    print(f"\nText      : {r['text']}")
    print(f"Language  : {r['language']}")
    print(f"Prediction: {r['label']}   (score = {r['score']:.2%})")
    print(f"Method    : {r['method']}   | newly saved: {r['saved']}")


if __name__ == "__main__":
    checker = ContextChecker()
    while True:
        t = input("\n> ").strip()
        if not t:
            break
        show(checker.predict(t))