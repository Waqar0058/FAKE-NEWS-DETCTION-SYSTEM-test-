"""
predict_models.py
Fake-news prediction (English + Urdu) using YOUR saved models.

Folder layout expected (relative to this file):
    combined_final/                     XLM-R trained on Urdu + English
    english_final/                      English model
    urdu_final/final_model_bert/        Urdu transformer model
    urdu_final/final_model_xlm/         Urdu transformer model
    urdu_final/tfidf_logreg/            TF-IDF + Logistic Regression (Urdu)
"""
import os
import re
import unicodedata

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# ----------------------------------------------------------------------------
# ROOT PATH: folder that contains this file. All model paths are relative to it,
# so the project works no matter where you start it from.
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def P(relative_path: str) -> str:
    return os.path.join(BASE_DIR, *relative_path.split("/"))


# name -> folder, languages it is used for, weight in the final average
TRANSFORMER_MODELS = {
    "combined":   {"path": "combined_final",               "langs": ["urdu", "english"], "weight": 0.40},
    "english":    {"path": "english_final",                "langs": ["english"],         "weight": 0.60},
    "urdu_bert":  {"path": "urdu_final/final_model_bert",  "langs": ["urdu"],            "weight": 0.35},
    "urdu_xlm":   {"path": "urdu_final/final_model_xlm",   "langs": ["urdu"],            "weight": 0.35},
}
TFIDF_MODEL = {"path": "urdu_final/tfidf_logreg", "langs": ["urdu"], "weight": 0.15}

# Used only if a model's config has no real label names (LABEL_0 / LABEL_1).
# CHECK this matches the labels you used in training!
LABEL_MAP = {0: "FAKE", 1: "REAL"}

MAX_LEN = 256
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ----------------------------------------------------------------------------
# Text utilities
# ----------------------------------------------------------------------------
URDU_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
LATIN_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    urdu = len(URDU_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    return "urdu" if urdu > latin else "english"


def clean_text(text: str) -> str:
    """Light cleaning. Keep it the SAME as what you used in training."""
    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ----------------------------------------------------------------------------
# Model wrappers
# ----------------------------------------------------------------------------
class TransformerModel:
    def __init__(self, name, path, langs, weight):
        self.name, self.langs, self.weight = name, langs, weight
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path)
        self.model.to(DEVICE).eval()
        self.real_idx = self._find_real_index()

    def _find_real_index(self):
        id2label = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        for i, lab in id2label.items():
            if lab in ("real", "true", "genuine", "reliable"):
                return i
        for i, lab in LABEL_MAP.items():
            if lab == "REAL":
                return i
        return 1

    @torch.no_grad()
    def real_probability(self, text):
        enc = self.tokenizer(text, truncation=True, padding=True,
                             max_length=MAX_LEN, return_tensors="pt").to(DEVICE)
        enc.pop("token_type_ids", None) if "xlm" in self.model.config.model_type else None
        probs = torch.softmax(self.model(**enc).logits, dim=-1)
        return float(probs[0, self.real_idx])


class TfidfModel:
    def __init__(self, name, folder, langs, weight):
        import joblib
        self.name, self.langs, self.weight = name, langs, weight
        self.clf = joblib.load(os.path.join(folder, "logreg_model.joblib"))
        self.vec = joblib.load(os.path.join(folder, "tfidf_vectorizer.joblib"))
        self.real_col = self._find_real_col()

    def _find_real_col(self):
        classes = list(self.clf.classes_)
        for i, c in enumerate(classes):
            if str(c).lower() in ("real", "true", "1"):
                return i
        return len(classes) - 1

    def real_probability(self, text):
        return float(self.clf.predict_proba(self.vec.transform([text]))[0, self.real_col])


class NewsClassifier:
    def __init__(self):
        self.models = {}
        for name, cfg in TRANSFORMER_MODELS.items():
            path = P(cfg["path"])
            try:
                self.models[name] = TransformerModel(name, path, cfg["langs"], cfg["weight"])
                print(f"[loaded] {name}: {cfg['path']}")
            except Exception as e:
                print(f"[skipped] {name} ({cfg['path']}): {str(e)[:150]}")
        try:
            path = P(TFIDF_MODEL["path"])
            self.models["urdu_tfidf"] = TfidfModel("urdu_tfidf", path,
                                                   TFIDF_MODEL["langs"], TFIDF_MODEL["weight"])
            print(f"[loaded] urdu_tfidf: {TFIDF_MODEL['path']}")
        except Exception as e:
            print(f"[skipped] urdu_tfidf: {str(e)[:150]}")
        if not self.models:
            raise RuntimeError("No model could be loaded. Check the folder names in predict_models.py")

    def predict(self, text: str) -> dict:
        text = clean_text(text)
        lang = detect_language(text)
        used = [m for m in self.models.values() if lang in m.langs] or list(self.models.values())
        per_model, num, den = {}, 0.0, 0.0
        for m in used:
            p = m.real_probability(text)
            per_model[m.name] = round(p, 4)
            num += m.weight * p
            den += m.weight
        real_p = num / den
        label = "REAL" if real_p >= 0.5 else "FAKE"
        return {
            "text": text,
            "language": lang,
            "label": label,
            "score": round(real_p if label == "REAL" else 1 - real_p, 4),
            "real_prob": round(real_p, 4),
            "fake_prob": round(1 - real_p, 4),
            "models_used": per_model,
        }

    def predict_batch(self, texts):
        return [self.predict(t) for t in texts]


def show(r):
    print(f"\nText      : {r['text']}")
    print(f"Language  : {r['language']}")
    print(f"Prediction: {r['label']}   (score = {r['score']:.2%})")
    print(f"Real={r['real_prob']:.2%} | Fake={r['fake_prob']:.2%}")
    print(f"Per model (real prob): {r['models_used']}")


if __name__ == "__main__":
    clf = NewsClassifier()
    while True:
        t = input("\n> ").strip()
        if not t:
            break
        show(clf.predict(t))