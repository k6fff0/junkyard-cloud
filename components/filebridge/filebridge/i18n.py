"""Messages the owner reads, per language. English is the base; a locale file only overrides what it has."""
import json
import os
import re

LOCALES = os.path.join(os.path.dirname(__file__), "locales")


def _load(code):
    path = os.path.join(LOCALES, "%s.json" % code)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def available():
    return sorted(f[:-5] for f in os.listdir(LOCALES) if f.endswith(".json"))


class Messages:
    def __init__(self, lang="en"):
        base = _load("en")
        own = _load(lang)
        self.lang = lang if own else "en"
        self.text = {**base.get("messages", {}), **own.get("messages", {})}
        self.language_name = own.get("language_name") or base.get("language_name", "English")
        # people mix languages, so a text "about files" is detected with the words of every locale
        words = set()
        for code in available():
            words.update(_load(code).get("file_words", []))
        # Latin words must be whole words ("word" is not inside "password"). Arabic words are matched
        # inside longer words on purpose, because Arabic glues prefixes to them ("والصور").
        parts = [(r"\b%s\b" if w.isascii() else "%s") % re.escape(w)
                 for w in sorted(words, key=len, reverse=True)]
        self.file_words = re.compile("(%s)" % "|".join(parts), re.I)

    def __call__(self, key, **kw):
        return self.text[key].format(**kw)
