"""
retrain.py - continual learning from the news saved in trusted_facts.csv

    python retrain.py

What it does
  * takes ONLY verified rows (source = manual or web) that were not used for training yet
  * mixes them with a sample of your ORIGINAL dataset (so the model does not forget it)
  * fine-tunes a COPY of the combined model and saves it to combined_final_v2
  * your current model is never overwritten

After it finishes, test combined_final_v2 on your validation data. If it is as good or
better, change "combined_final" to "combined_final_v2" in predict_models.py.
A GPU is strongly recommended.
"""
import os
import random

import pandas as pd
import torch

from fact_store import FactStore
from predict_models import BASE_DIR, DEVICE, LABEL_MAP, MAX_LEN, P, TransformerModel, clean_text

SOURCE_MODEL = "combined_final"
OUTPUT_MODEL = "combined_final_v2"
FACTS_CSV = os.path.join(BASE_DIR, "trusted_facts.csv")

MIN_NEW_ROWS = 50        # do nothing until at least this many new verified rows exist
EPOCHS = 1
LR = 1e-5                # small, to avoid forgetting
BATCH = 8
REPLAY_RATIO = 3         # original-data samples per new row

# Your ORIGINAL training data: (csv path, text column, label column)
REPLAY_CSVS = [
    # ("data/english.csv", "text", "label"),
    # ("data/urdu.csv", "text", "label"),
]


def is_real(value):
    s = str(value).strip().lower()
    if s in ("real", "true"):
        return True
    if s in ("fake", "false"):
        return False
    return LABEL_MAP.get(int(float(s)), "FAKE") == "REAL"


def load_replay(n):
    pool = []
    for path, tcol, lcol in REPLAY_CSVS:
        df = pd.read_csv(path if os.path.isabs(path) else os.path.join(BASE_DIR, path))
        pool += [(clean_text(t), is_real(l)) for t, l in zip(df[tcol].astype(str), df[lcol])]
    random.shuffle(pool)
    return pool[:n]


def main():
    store = FactStore(FACTS_CSV)
    rows = store.training_rows()
    print(f"New verified rows: {len(rows)} (need {MIN_NEW_ROWS})")
    if len(rows) < MIN_NEW_ROWS:
        print("Not enough new data yet. Keep using the system and correcting results with /real, /fake.")
        return

    new_data = [(clean_text(r["fact"]), r["label"] == "REAL") for r in rows]
    replay = load_replay(len(new_data) * REPLAY_RATIO)
    if not replay:
        print("WARNING: REPLAY_CSVS is empty -> training on new rows only can make the model "
              "forget your original data. Fill REPLAY_CSVS first.")
        return
    data = new_data + replay
    random.shuffle(data)
    print(f"Training on {len(new_data)} new + {len(replay)} original examples ...")

    tm = TransformerModel("combined", P(SOURCE_MODEL), ["urdu", "english"], 1.0)
    model, tok = tm.model, tm.tokenizer
    real_idx, fake_idx = tm.real_idx, 1 - tm.real_idx

    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    for epoch in range(EPOCHS):
        random.shuffle(data)
        total = 0.0
        for i in range(0, len(data), BATCH):
            batch = data[i:i + BATCH]
            enc = tok([t for t, _ in batch], truncation=True, padding=True,
                      max_length=MAX_LEN, return_tensors="pt").to(DEVICE)
            y = torch.tensor([real_idx if r else fake_idx for _, r in batch]).to(DEVICE)
            loss = model(**enc, labels=y).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            total += loss.item()
        print(f"epoch {epoch + 1}: average loss {total / max(1, len(data) // BATCH):.4f}")

    out = P(OUTPUT_MODEL)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    store.mark_trained([r["fact"] for r in rows])
    print(f"\nSaved to {OUTPUT_MODEL}. Evaluate it, then switch the path in predict_models.py.")


if __name__ == "__main__":
    main()
