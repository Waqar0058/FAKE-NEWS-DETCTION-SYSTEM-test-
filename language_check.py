"""
language_check.py - checks that the text really is in the language the user selected.

The project supports ONLY English and Urdu. check_language() returns (ok, message).
If ok is False, the message is shown on the website as an error and nothing is predicted or saved.

It rejects:
    * text with no letters (only numbers / symbols / emoji)
    * other scripts (Hindi, Chinese, Russian, accented European languages ...)
    * text that is Urdu while English is selected (and the other way round)
    * mixed Urdu + English text where neither language dominates
    * Arabic / Persian text selected as Urdu
    * other languages written in English letters (for example Roman Urdu)
"""
import re

ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
URDU_SPECIFIC = set("ٹڈڑںہھےۓۃۂ")        # letters used in Urdu but not in Arabic / Persian
NAMES = {"english": "English", "urdu": "Urdu"}

# Common English words that are NOT also common Roman-Urdu words.
ENGLISH_WORDS = set("""
the and of for with on at by from are was were be been has have had will would can could says said
that this it as not after before over under new who what when where which their they his her its
than about into more also but an if during between against announced government minister
""".split())

MIN_SHARE = 0.70          # the chosen language must be at least 70% of all letters
MAX_OTHER = 0.15          # at most 15% letters from other scripts


def check_language(text, selected):
    urdu = latin = other = 0
    for ch in text:
        if not ch.isalpha():
            continue
        if "a" <= ch <= "z" or "A" <= ch <= "Z":
            latin += 1
        elif ARABIC_SCRIPT.match(ch):
            urdu += 1
        else:
            other += 1
    total = urdu + latin + other

    if total == 0:
        return False, ("Invalid text: it contains no readable letters. "
                       "Please enter news text in English or Urdu.")

    if other / total > MAX_OTHER:
        return False, ("Invalid language: this text is not English or Urdu. "
                       "This system supports only English and Urdu news.")

    detected = "urdu" if urdu > latin else "english"
    if detected != selected:
        return False, (f"Invalid language selection: the text is written in {NAMES[detected]}, "
                       f"but {NAMES[selected]} is selected. "
                       f"Select {NAMES[detected]} or enter {NAMES[selected]} news.")

    if max(urdu, latin) / total < MIN_SHARE:
        return False, ("Invalid language: the text mixes English and Urdu. "
                       f"Please enter the news fully in {NAMES[selected]}.")

    if selected == "urdu":
        if urdu >= 15 and not any(c in URDU_SPECIFIC for c in text):
            return False, ("Invalid language: this looks like Arabic or Persian, not Urdu. "
                           "This system supports only English and Urdu news.")
    else:
        words = re.findall(r"[A-Za-z']+", text.lower())
        if len(words) >= 6:
            need = 1 if len(words) < 10 else 2
            if sum(1 for w in words if w in ENGLISH_WORDS) < need:
                return False, ("Invalid language: this does not look like English "
                               "(for example Roman Urdu or another language written in English letters). "
                               "Please enter English news, or select Urdu and type in Urdu script.")
    return True, ""
