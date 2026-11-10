"""Language utilities for Indian conversational commands.

* Devanagari → Latin transliteration (so Hindi-script transcripts from Prisma hi-IN
  share one keyword grammar with Hinglish/English transcripts from Prisma en-IN).
* Phonetic keys for fuzzy name matching — speech recognisers routinely hear an
  unfamiliar project name like "Dineo" as "the new" or "डिन्यूर".
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Common tech / command words written in Devanagari → canonical Latin spelling.
DEVANAGARI_WORDS = {
    "प्रोजेक्ट": "project", "प्रॉजेक्ट": "project", "गिट": "git", "स्टेटस": "status", "स्टैटस": "status",
    "सर्वर": "server", "स्टार्ट": "start", "डेवलपमेंट": "development", "डेव": "dev", "टेस्ट": "test",
    "टेस्ट्स": "tests", "बिल्ड": "build", "चेक": "check", "खोलो": "kholo", "खोल": "khol", "खोलिए": "kholiye",
    "चलाओ": "chalao", "चला": "chala", "चालू": "chalu", "बंद": "band", "रोको": "roko", "करो": "karo",
    "कर": "kar", "दो": "do", "और": "aur", "फिर": "phir", "एरर": "error", "एरर्स": "errors", "लॉग्स": "logs",
    "लॉग": "log", "फाइल": "file", "फ़ाइल": "file", "फाइलें": "files", "फ़ाइलें": "files", "नोट": "note",
    "क्रोम": "chrome", "ब्राउज़र": "browser", "ब्राउजर": "browser", "टैब्स": "tabs", "टैब": "tab",
    "कमिट": "commit", "कमिट्स": "commits", "स्टॉप": "stop", "रन": "run", "मेरा": "mera", "मेरे": "mere",
    "ओपन": "open", "कोड": "code", "स्क्रिप्ट": "script", "स्क्रिप्ट्स": "scripts", "दिखाओ": "dikhao",
    "बताओ": "batao", "देखो": "dekho", "क्या": "kya", "कोई": "koi", "है": "hai", "हैं": "hain",
    "रहे": "rahe", "रहा": "raha", "आ": "aa", "की": "ki", "के": "ke", "का": "ka", "को": "ko",
    "पेरी": "perry", "पैरी": "perry", "परी": "perry", "जार्विस": "perry", "यूट्यूब": "youtube", "गिटहब": "github", "स्पॉटिफाई": "spotify",
    "टर्मिनल": "terminal", "लिंट": "lint", "प्रोसेस": "process", "बनाओ": "banao", "लिखो": "likho",
}

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ज़": "z", "फ़": "f", "ड़": "d", "ढ़": "dh",
}
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o",
           "औ": "au", "ऋ": "ri", "ऑ": "o", "ॲ": "e"}
_MATRAS = {"ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
           "ृ": "ri", "ॉ": "o", "ॅ": "e"}
_NUKTA, _VIRAMA = "़", "्"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _translit_word(w: str) -> str:
    out = []
    i = 0
    while i < len(w):
        ch = w[i]
        if i + 1 < len(w) and w[i + 1] == _NUKTA and ch + _NUKTA in _CONS:
            ch = ch + _NUKTA
            i += 1
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch in _CONS:
            out.append(_CONS[ch])
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 1
            elif nxt == _VIRAMA:
                i += 1
            elif nxt and (nxt in _CONS or nxt in "ंँ"):
                out.append("a")
            # word-final consonant: inherent 'a' is dropped (schwa deletion)
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in "ंँ":
            out.append("n")
        elif ch == "ः":
            out.append("h")
        elif ch in "।॥":
            out.append(".")
        elif not DEVANAGARI.match(ch):
            out.append(ch)
        i += 1
    return "".join(out)


def to_latin(text: str) -> str:
    if not DEVANAGARI.search(text):
        return text
    tokens = re.split(r"(\s+|[,.;!?।])", text)
    return "".join(DEVANAGARI_WORDS.get(t, _translit_word(t)) if DEVANAGARI.search(t) else t for t in tokens)


def phonetic(s: str) -> str:
    """Coarse consonant skeleton: 'Dineo' ≈ 'the new' ≈ 'dinyur' → 'tn' / 'tnr'."""
    s = re.sub(r"[^a-z]", "", to_latin(s).lower())
    for a, b in (("ph", "f"), ("th", "t"), ("dh", "t"), ("kh", "k"), ("gh", "g"), ("bh", "b"),
                 ("ch", "c"), ("sh", "s"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("d", "t"),
                 ("z", "j"), ("w", "v"), ("c", "k")):
        s = s.replace(a, b)
    head, rest = s[:1], s[1:]
    rest = re.sub(r"[aeiouyhv]", "", rest)
    if head in "aeiouyh":
        head = "a" if head else ""
    key = head + rest
    return re.sub(r"(.)\1+", r"\1", key)


def similarity(a: str, b: str) -> float:
    """0..1 score combining spelling and sound similarity."""
    a, b = to_latin(a), to_latin(b)
    a_l, b_l = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
    if not a_l or not b_l:
        return 0.0
    if a_l == b_l:
        return 1.0
    spelled = SequenceMatcher(None, a_l, b_l).ratio()
    pa, pb = phonetic(a), phonetic(b)
    sound = SequenceMatcher(None, pa, pb).ratio() if pa and pb else 0.0
    if pa and pa == pb:
        sound = max(sound, 0.92 if len(pa) >= 2 else 0.6)
    return max(spelled, sound * 0.95)


HINDI_MARKERS = {
    "karo", "kar", "kholo", "khol", "chalao", "chala", "hai", "hain", "mera", "meri", "mere", "aur", "kya",
    "ki", "ka", "ko", "ke", "do", "dikhao", "batao", "dekho", "band", "roko", "kijiye", "zara",
    "phir", "fir", "wala", "wali", "abhi", "nahi", "koi", "rahe", "raha", "chahiye", "banao", "likho",
    "gaana", "gana", "gaane", "bajao", "lagao", "agla", "pichla", "kaunsa", "konsa", "garo", "jao", "mein", "pe",
}


def detect_style(text: str) -> str:
    """'hinglish' | 'hindi' | 'english' — drives the reply language and Timbre voice."""
    if DEVANAGARI.search(text):
        return "hindi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    return "hinglish" if len(words & HINDI_MARKERS) >= 1 else "english"
