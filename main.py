"""
main.py  -  RUN THIS FILE:   python main.py

Asks for news text (English or Urdu) and prints only:
    Text      : ...
    Language  : ...
    Prediction: REAL/FAKE   (score = xx.xx%)

New confident results are saved automatically to trusted_facts.csv, so the same
news is answered instantly (and offline) next time.

If a result is wrong, type  /real  or  /fake  right after it to correct it.
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)


@contextlib.contextmanager
def quiet():
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


def main():
    print("Loading models, please wait ...")
    with quiet():
        from predict_context import ContextChecker
        checker = ContextChecker()
    print("Ready.  (Tip: type /real or /fake after a result to correct it)\n")

    last_text = None
    while True:
        try:
            text = input("Type news in English or Urdu (press Enter on an empty line to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break

        if text.lower() in ("/real", "/fake"):
            if not last_text:
                print("Type some news first.\n")
                continue
            with quiet():
                checker.correct(last_text, text[1:])
            print(f"Saved: that news is now marked {text[1:].upper()}.\n")
            continue

        with quiet():
            r = checker.predict(text)
        last_text = text
        print(f"\nText      : {text}")
        print(f"Language  : {r['language']}")
        print(f"Prediction: {r['label']}   (score = {r['score']:.2%})\n")


if __name__ == "__main__":
    main()