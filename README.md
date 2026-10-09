# Multilingual Fake News Detection System (English + Urdu)

A web-based system that classifies news text written in **English** or **Urdu** as **REAL** or **FAKE** and shows a confidence score. It combines fine-tuned transformer models with a fact-checking memory and optional live web verification.

Final Year Project, BS Data Science, Department of Data Science & AI, Khwaja Fareed University of Engineering & Information Technology (KFUEIT), Rahim Yar Khan.

> Text only. Image, audio and video (deepfake) detection is not part of this project.

---

## Features

- **Bilingual detection:** English and Urdu news text, with an on-screen English/Urdu keyboard.
- **Strict language validation:** rejects wrong language selection, Roman Urdu, Arabic/Persian, mixed-language text and other scripts.
- **Model ensemble:** several transformer models plus a TF-IDF + Logistic Regression model for Urdu, combined by weighted average.
- **Fact checking:** semantic search over trusted facts (multilingual MPNet) and natural language inference (mDeBERTa).
- **Live web verification:** DuckDuckGo search (no API key) when no trusted fact matches.
- **Memory:** repeated news is answered instantly from `trusted_facts.csv`.
- **Accounts:** sign up, sign in, "Remember me", or continue as **guest**.
- **History and analytics** (signed-in users): own predictions, delete records, charts by day, label, language and score.
- **Feedback screen** (1-5 stars + comment) when a signed-in user exits.
- **Optional MongoDB mirror** of all data.
- **Continual learning:** `retrain.py` fine-tunes a copy of the combined model from verified data.
- **Command-line tool:** `main.py` with `/real` and `/fake` correction commands.

## How a prediction works

1. The user selects a language and enters text (max 3000 characters).
2. `language_check.py` verifies the text matches the selected language.
3. The text is cleaned (Unicode normalization, URL removal, Urdu diacritic normalization).
4. If the same news was seen before, the saved result is returned instantly.
5. Otherwise the classifier ensemble computes the real probability.
6. Trusted-fact check: if a similar fact is found, it is combined with the classifiers (80% fact / 20% classifiers).
7. If no fact matches, live web search is tried (60% web / 40% classifiers).
8. Result: `REAL` if probability >= 0.5, otherwise `FAKE`; the score is the confidence of that label.
9. The result is saved to the memory; signed-in users also get it in their history.

## Technology

| Area | Technology |
|---|---|
| Models | PyTorch, Hugging Face Transformers, Sentence-Transformers, scikit-learn |
| Back end | Python, FastAPI, Uvicorn |
| Front end | HTML, CSS, JavaScript (no framework, SVG charts) |
| Storage | CSV / JSON files, optional MongoDB (pymongo) |
| Web search | DuckDuckGo via `ddgs` |

## Project structure

```
project/
├── api.py                # FastAPI server (run this)
├── main.py               # command-line predictor
├── predict_models.py     # classifier ensemble, text cleaning, language detection
├── predict_context.py    # fact check + web check + decision engine
├── fact_store.py         # trusted_facts.csv memory
├── live_search.py        # DuckDuckGo search
├── language_check.py     # English/Urdu input validation
├── auth_store.py         # accounts, password hashing, tokens, feedback
├── history_store.py      # history.csv and analytics
├── db.py                 # optional MongoDB mirror
├── retrain.py            # continual learning
├── show_files.py         # prints a folder tree
├── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   └── auth.js
├── combined_final/       # model folders (not in the repository, see below)
├── english_final/
└── urdu_final/
    ├── final_model_bert/
    ├── final_model_xlm/
    └── tfidf_logreg/
```

Files created automatically while the app runs: `history.csv`, `trusted_facts.csv`, `accounts.json`, `secret.key`.

## Installation

**Requirements:** Python 3.10 or newer (recommended). A GPU is recommended but not required.

```bash
# 1. clone
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY

# 2. virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

# 3. dependencies
pip install -r requirements.txt
```

### Download the trained models

The model files are too large for GitHub. Download them from: **[ADD YOUR LINK HERE: Hugging Face / Google Drive]**

Place them in the project folder exactly like this:

```
combined_final/
english_final/
urdu_final/final_model_bert/
urdu_final/final_model_xlm/
urdu_final/tfidf_logreg/      (logreg_model.joblib, tfidf_vectorizer.joblib)
```

The first run also downloads two helper models from Hugging Face (`paraphrase-multilingual-mpnet-base-v2` and `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`), so an internet connection is needed the first time. After that they are loaded from the local cache. If these helpers cannot load, the system still works with the classifiers and saved results only.

## Run the web application

```bash
python api.py
```

Wait for "Ready", then open **http://localhost:5000** in Chrome or Edge. API documentation is at http://localhost:5000/docs.

1. Click **Explore as Guest**, or sign up / sign in.
2. Select **English** or **Urdu**.
3. Type or paste the news and click **Predict News**.

Guests can predict but cannot use History or Analytics.

## Command-line use

```bash
python main.py
```

Type news and read the prediction. After a result, type `/real` or `/fake` to correct it; the correction is saved as trusted data.

## Optional: MongoDB

MongoDB is an extra copy of the data. The app works without it.

```bash
# default connection (change with environment variables)
MONGO_URI=mongodb://localhost:27017
MONGO_DB=fake_news_db
```

Use **Settings → Copy CSV data to MongoDB** to sync. **Security:** a default local MongoDB may run without a login. Before using real user data, enable authentication, create a user with the `readWrite` role on `fake_news_db` only, keep `bindIp` at `127.0.0.1`, and put the credentials in `MONGO_URI`.

## Continual learning

```bash
python retrain.py
```

Uses only verified rows (`manual` or `web`) from `trusted_facts.csv`, mixes them with your original dataset (set `REPLAY_CSVS` in `retrain.py`), and saves a new model to `combined_final_v2`. The current model is never overwritten. Evaluate it before changing the path in `predict_models.py`.

## API summary

| Method and path | Access | Purpose |
|---|---|---|
| `POST /api/predict` | guest or user | predict REAL/FAKE |
| `POST /api/auth/signup`, `/api/auth/signin` | public | create account / sign in |
| `GET /api/auth/check` | user | check token |
| `POST /api/feedback` | user | save rating and comment |
| `GET /api/history?range=` | user | own history (all, today, 7, 15, 30) |
| `DELETE /api/history/{id}` | user | delete own history record |
| `GET /api/analytics?range=` | user | chart data |
| `GET /api/mongo/status`, `POST /api/mongo/sync` | user | MongoDB status / sync |

## Security

- Passwords are stored only as salted PBKDF2-SHA256 hashes (200,000 rounds).
- Sessions use HMAC-signed tokens that expire (1 day, or 30 days with "Remember me").
- Users can read and delete only their own history.
- The server listens on `127.0.0.1` and allows cross-origin requests only from localhost.
- **Never publish** `secret.key`, `accounts.json`, `history.csv` or `trusted_facts.csv`. They are listed in `.gitignore`.

## Privacy note

Every prediction is saved with its result in `trusted_facts.csv` (guests included). Signed-in users' predictions are also saved in `history.csv` and optionally MongoDB. If no trusted fact matches, the text is sent as a search query to DuckDuckGo. Do not enter confidential text.

## Limitations

- Text only; no image, audio or video detection.
- Only the first 256 tokens (and at most 3000 characters) are analyzed.
- Results are probabilistic and are not proof that a claim is true or false.
- The supporting facts and web sources are computed internally but are not yet displayed.
- One prediction is processed at a time; intended for local or small-scale use.


## Authors

- Waqar Ahmad (DSAI232102023)
- Ahsan Ali Naveed (DSAI232102032)

**Supervisor:** Mr. Safdar Hussain
