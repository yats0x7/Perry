"""Planners turn a command into a structured `Plan` of tool calls.

A planner only *proposes*. Every plan, whichever planner produced it, goes through
`PolicyEngine.review` before anything is shown for approval or executed.

`RulePlanner` is a deterministic grammar for Hinglish / Hindi / English developer
commands. It needs no LLM, is fully inspectable, works offline and resolves project
names phonetically (speech recognisers often hear "Dineo" as "the new").
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from perry_protocol import DesktopManifest, Plan, PlanStep, ProjectSummary

from .language import similarity, to_latin


@dataclass
class PlanningContext:
    manifest: DesktopManifest
    last_project_id: str | None = None
    history: list[tuple[str, str]] = field(default_factory=list)  # (user, assistant) recent turns


class Planner(abc.ABC):
    name: str = "planner"

    @abc.abstractmethod
    async def plan(self, text: str, ctx: PlanningContext) -> Plan: ...


# ---------------------------------------------------------------------------- grammar --

# Wake word "Perry" and how speech recognition tends to hear it (also accepts the old name).
WAKE = re.compile(r"^\s*(hey\s+|hi\s+|ok\s+|okay\s+|hello\s+|arre\s+|oye\s+)?(perry|peri|pery|perri|perrie|parry|pari|"
                  r"paari|berry|bery|beri|perry ji|jarvis)\b[\s,!.:]*", re.I)
SPLIT = re.compile(
    r"\s*(?:,|;|\.\s|\.$|\bthen\b|\band then\b|\bafter that\b|\buske baad\b|\buske bad\b|\bphir\b|\bfir\b|"
    r"\baur\b|\band\b|\bthen\b|\bplus\b|\balso\b|\bsaath hi\b)\s*",
    re.I,
)
W = lambda *ws: re.compile(r"\b(" + "|".join(ws) + r")\b", re.I)  # noqa: E731

OPEN = W("kholo", "khol", "kholiye", "kholna", "khol do", "open", "launch", "opening", "le aao", "chalu karo")
START = W("start", "chalao", "chala", "chala do", "chalu", "run", "shuru", "launch", "boot", "up", "on",
          "chalana", "chalaiye", "running")
STOP = W("stop", "band", "bandh", "rok", "roko", "ruko", "kill", "off", "shut", "terminate", "close")
SHOW = W("check", "dekho", "dekh", "batao", "bata", "dikhao", "dikha", "show", "kya", "list", "tell", "see",
         "aa rahe", "aa raha", "hai kya", "hain kya", "inspect", "status")
SERVER = W("server", "dev server", "development server", "devserver", "localhost", "dev", "app", "website", "site", "frontend")
GIT = W("git", "gitt", "geet", "kit")
GIT_CHANGES = W("changes", "change", "status", "diff", "modified", "uncommitted")
COMMITS = W("commit", "commits", "log", "history")
RECENT = W("recent", "last", "latest", "pichle", "pichhle", "aakhri", "new")
TESTS = W("test", "tests", "testing", "spec", "specs")
BUILD = W("build", "compile")
LINT = W("lint", "linter", "eslint")
TYPECHECK = W("typecheck", "type check", "types", "tsc")
ERRORS = W("error", "errors", "erros", "issue", "issues", "problem", "problems", "warning", "warnings",
           "logs", "log", "output", "crash", "galti")
SCRIPTS = W("scripts", "script", "info", "details", "framework", "commands", "package json", "package.json")
FILES = W("files", "file", "folder", "folders", "directory")
FIND = W("find", "dhundo", "dhoondo", "dhundho", "search", "khojo", "locate", "kahan hai", "kaha hai")
READ = W("read", "padho", "padh", "content", "contents", "andar kya")
NOTE = W("note", "notes", "yaad", "reminder", "todo")
NOTE_VERB = W("banao", "bana", "likho", "likh", "create", "make", "save", "add", "rakh", "rakho", "jot", "write", "bana do")
TABS = W("tabs", "tab")
PROCS = W("processes", "process", "kya chal raha", "running", "chal rahe")
FOCUS = W("switch", "focus", "par jao", "pe jao", "pe le chalo", "front", "aage lao", "activate")
PROJECT_WORD = W("project", "projects", "repo", "repository", "codebase", "app")
MEDIA_NOUN = W("song", "songs", "gaana", "gana", "gaane", "gane", "music", "track", "spotify", "apple music",
               "playlist", "audio", "geet")
M_PAUSE = W("pause", "ruko", "rok", "roko", "band", "stop", "mute")
M_PLAY = W("resume", "play", "bajao", "baja", "baja do", "chalao", "chala", "chala do", "lagao", "laga do",
           "continue", "shuru", "start", "sunao", "suna do")
M_NEXT = W("next", "agla", "agle", "skip", "badlo", "change")
MUSIC_VERB = W("play", "bajao", "baja", "baja do", "lagao", "laga do", "sunao", "suna do")
M_PREV = W("previous", "pichla", "pichhla", "pehle wala", "pichle", "back")
M_WHAT = W("kaunsa", "konsa", "kaun sa", "kon sa", "which", "what", "kya")
SEARCH_SITE = re.compile(r"\b(google|youtube|you tube|github|wikipedia|wiki|amazon|flipkart|stack ?overflow|npm|maps|google maps|instagram)\b", re.I)
ORDINALS = {"first": 1, "1st": 1, "pehla": 1, "pahla": 1, "pahala": 1, "pehli": 1, "pahli": 1, "second": 2, "2nd": 2,
            "doosra": 2, "dusra": 2, "dusri": 2, "doosri": 2, "third": 3, "3rd": 3, "teesra": 3, "tisra": 3, "teesri": 3,
            "fourth": 4, "4th": 4, "chautha": 4, "fifth": 5, "5th": 5}
ORDINAL_RESULT = re.compile(r"\b(" + "|".join(ORDINALS) + r")\s+(video|videos|result|results|link|one|wala|vala|wali|gaana|song)\b", re.I)
SEARCH_VERB = W("search", "search karo", "dhundo", "dhoondo", "dhundho", "khojo", "find", "look up", "lookup")
B_NEW_TAB = re.compile(r"\b(new|naya|nayi|ek aur|another)\s+tab\b", re.I)
B_TAB = re.compile(r"\btab\b", re.I)
B_CLOSE = W("close", "band", "bandh", "hatao", "hata do", "remove")
B_RELOAD = W("reload", "refresh", "re-load")
B_BACK = re.compile(r"\b(go back|back jao|peeche jao|piche jao|peeche chalo|pichle page|previous page|wapas jao|wapis jao)\b", re.I)
B_FWD = re.compile(r"\b(go forward|aage jao|forward jao|aage chalo|next page|agle page)\b", re.I)
B_NEXT_TAB = re.compile(r"\b(next|agla|agle|agli)\s+tab\b", re.I)
B_PREV_TAB = re.compile(r"\b(previous|prev|pichla|pichle|pichhla|pichli)\s+tab\b", re.I)
B_SWITCH = [
    re.compile(r"(?:switch to|go to|open)\s+(?:the\s+)?(?P<q>[\w .:/-]+?)\s+tab\b", re.I),
    re.compile(r"(?P<q>[\w.:/-]+(?:\s+[\w.:/-]+)?)\s+(?:wale|wala|wali|vale|vala|vali)\s+tab", re.I),
    re.compile(r"(?P<q>[\w.:/-]+)\s+tab\s+(?:pe|par|me|mein)\s+(?:jao|chalo|switch|le chalo)", re.I),
]
B_READ = re.compile(r"\b(page|website|site|tab|article)\b.*\b(padho|read|kya likha|kya hai|summary|summarise|summarize|title|dikhao)\b|"
                    r"\b(read|padho)\b.*\b(page|website|article|tab)\b", re.I)
B_VIDEO = W("video", "youtube", "you tube", "reel")
CURRENT_SITE = re.compile(r"\b(yahan|yaha|isi|isme|is (page|site|tab|website)|iss (page|site|tab|website)|"
                          r"this (page|site|tab|website)|current (tab|page|site)|same tab|here)\b", re.I)
PLAY_IT_WORDS = {"it", "isko", "usko", "use", "wo", "woh", "pehla", "first", "video", "result", "one", "that", "ye", "yeh"}


SEARCHABLE = {"google", "youtube", "github", "wikipedia", "amazon", "flipkart", "stackoverflow", "npm", "maps", "instagram"}


def _norm_site(raw: str) -> str:
    site = raw.lower().replace(" ", "")
    return {"wiki": "wikipedia", "googlemaps": "maps", "youtube": "youtube"}.get(site, site)
SEARCH_FILLER = set("""google youtube you tube github wikipedia wiki amazon flipkart stack overflow stackoverflow npm maps instagram
pe par per pay on in mein me se ka ki ke ko search karo kar do de dijiye kijiye dhundo dhoondo dhundho khojo find look up lookup
for please plz zara perry mera meri mere my the a chrome brave safari edge firefox browser bajao baja play chalao chala
lagao laga sunao suna video videos dikhao open kholo khol karke kar ke and aur then phir for from""".split())
BROWSER_ALIASES = {"chrome": "Google Chrome", "google chrome": "Google Chrome", "brave": "Brave Browser",
                   "safari": "Safari", "edge": "Microsoft Edge", "vivaldi": "Vivaldi", "firefox": "Firefox", "arc": "Arc"}
BROWSER_NAMES = {"Safari", "Google Chrome", "Brave Browser", "Arc", "Firefox", "Microsoft Edge", "Opera", "Vivaldi"}
MEDIA_FILLER = set("""spotify apple music pe par on in mein me se ka ki ke ko song songs gaana gana gaane gane track geet
bajao baja do play chalao chala lagao laga sunao suna karo kar please plz zara mera meri mere my a the koi ek wala
wali perry chahiye hai music playlist from resume continue shuru start dobara wapas wapis phir fir again do de
dijiye kijiye""".split())

KNOWN_SITES = {
    "youtube": "https://www.youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "chatgpt": "https://chatgpt.com", "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com", "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
    "vercel": "https://vercel.com", "netflix": "https://www.netflix.com", "instagram": "https://www.instagram.com",
    "whatsapp web": "https://web.whatsapp.com", "gnani": "https://www.gnani.ai",
    "chatgpt": "https://chatgpt.com", "gmail": "https://mail.google.com", "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com", "wikipedia": "https://www.wikipedia.org",
    "npm": "https://www.npmjs.com", "maps": "https://maps.google.com",
}
APP_ALIASES = {"brave browser": "Brave Browser", "edge": "Microsoft Edge", "apple music": "Music", "chrome": "Google Chrome", "vs code": "Visual Studio Code", "vscode": "Visual Studio Code",
               "visual studio code": "Visual Studio Code", "brave": "Brave Browser", "iterm": "iTerm",
               "settings": "System Settings", "system settings": "System Settings"}
DOMAIN = re.compile(r"\b((?:https?://)?(?:[a-z0-9-]+\.)+(?:com|in|org|net|io|dev|ai|app|co|so|me|gg|tv)(?:/[^\s]*)?)", re.I)
LOCALHOST = re.compile(r"\blocal\s?host\s*(?:port\s*)?:?\s*(\d{2,5})", re.I)
FILENAME = re.compile(r"\b([\w.-]+\.(?:md|txt|json|js|ts|tsx|jsx|py|css|html|yml|yaml|toml|mjs|cjs|env|sh|go|rs|java|kt|swift))\b", re.I)
STOPWORDS = set("""mera meri mere my the a an to ka ki ke ko wala wali vala vali project projects repo app please plz zara
perry open kholo khol karo kar do de dena hai hain is in mein me pe par se and aur check status git start server dev
development run chalao chala chalu tests test build ek""".split())


VERB_END = re.compile(
    r"\b(kholo|khol do|kholiye|karo|kar do|kijiye|chalao|chala do|dikhao|dikha do|batao|bata do|dekho|"
    r"open it|start it)\b\s+(?=\S)", re.I)
FILLER = set("ok okay theek thik hai haan please plz zara bhi ek baar check karo kar do kijiye ki kya".split())


def _clauses(text: str) -> list[str]:
    """Split on conjunctions/punctuation, then after Hinglish imperative verbs (Prisma
    output is usually unpunctuated). Note dictation keeps the rest of the sentence."""
    raw = [p.strip(" .,!?") for p in SPLIT.split(text) if p and p.strip(" .,!?")]
    out: list[str] = []
    for i, part in enumerate(raw):
        if NOTE.search(part) and NOTE_VERB.search(part):
            # everything after "note banao ki …" is the note body, even across "aur"
            rest = re.search(re.escape(part) + r".*$", text, re.I | re.S)
            out.append(rest.group(0).strip(" .,!?") if rest else " ".join(raw[i:]))
            break
        for sub in VERB_END.sub(lambda m: m.group(1) + " | ", part).split(" | "):
            sub = sub.strip(" .,!?")
            words = set(re.findall(r"[a-z]+", sub.lower()))
            if sub and not words <= FILLER:
                out.append(sub)
    return out or [text]


# Frequent speech-recognition slips on Hinglish developer commands (observed with Prisma
# en-IN): "kholo"→"holo", "git status"→"get status", "chalao"→"chala o", "dev"→"day".
ASR_FIXES = [
    (re.compile(r"\b(holo|kolo|khulo|kollo|kholu|golo|khol o)\b", re.I), "kholo"),
    (re.compile(r"\b(get|kit|geet|gitt|guitar)\s+(status|log|diff)\b", re.I), r"git \2"),
    (re.compile(r"\bchala o\b", re.I), "chalao"),
    (re.compile(r"\b(garo|caro|kro)\b", re.I), "karo"),
    (re.compile(r"\b(sone|sona|soye|so)\s+(mar|maat|matt|mut)\s+(do|dena|dijiye)\b", re.I), r"\1 mat \3"),
    (re.compile(r"\b(krome|crome|krom|chrom)\b", re.I), "chrome"),
    (re.compile(r"\b(spodify|spotfy|spotifi|spotifai|spotyfy|spot if i|spotty fy|spotfi)\b", re.I), "spotify"),
    (re.compile(r"\b(pump|pon|aan|un)\s+spotify\b", re.I), "on spotify"),
    (re.compile(r"\bchat\s+gpt\b", re.I), "chatgpt"),
    (re.compile(r"\byou\s+tube\b", re.I), "youtube"),
    (re.compile(r"\b(agale|aagle|aagla|agala)\b", re.I), "agle"),
    (re.compile(r"\b(pichhale|pichale|pichhle|pichala)\b", re.I), "pichle"),
    # "tab" is often heard as top/tha/tub/tap right after a tab-ish word
    (re.compile(r"\b(ye|yeh|is|iss|naya|nayi|new|agla|agle|agli|pichla|pichle|pichli|previous|next|close|current|"
                r"wale|wala|wali)\s+(top|tha|tub|tap|taab|tob|tabh)\b", re.I), r"\1 tab"),
    (re.compile(r"\btab\s+(pe|par)\s+(ja|bheja|jaao|jau)\b", re.I), r"tab \1 jao"),
    (re.compile(r"\b(pozacaro|posacaro|pozkaro|poskaro|pausekaro|poz karo|pose karo|pos karo|paus karo|pauz karo|"
                r"pause caro|poz caro|pose caro)\b", re.I), "pause karo"),
    (re.compile(r"\b(spotify|youtube|google|github|amazon|chrome|brave|safari)\s+(pay|pai|pey)\b", re.I), r"\1 pe"),
    (re.compile(r"\b(ban|bandh|bund|band)\s+(karo|kar do|kardo|kar dijiye|kijiye|kar)\b", re.I), r"band \2"),
    (re.compile(r"\b(day|deo|their)\s+server\b", re.I), "dev server"),
    (re.compile(r"\bdevelopment\s+(sarvar|server|surver)\b", re.I), "development server"),
    (re.compile(r"\bnpm\s+run\s+day\b", re.I), "npm run dev"),
]


def normalize(text: str) -> str:
    return _norm(text)


def _norm(text: str) -> str:
    t = to_latin(text)
    for pat, rep in ASR_FIXES:
        t = pat.sub(rep, t)
    t = WAKE.sub("", t)
    t = t.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class _Match:
    project: ProjectSummary
    score: float
    span: str


def find_project(clause: str, projects: list[ProjectSummary]) -> _Match | None:
    if not projects:
        return None
    low = clause.lower()
    # 1. exact name / alias (word-bounded)
    for p in projects:
        for n in [p.name, *p.aliases]:
            if n and re.search(r"(?<![\w])" + re.escape(n.lower()) + r"(?![\w])", low):
                return _Match(p, 1.0, n)
    # 2. fuzzy: n-grams, strongest right before "project/repo/app"
    words = re.findall(r"[\w-]+", low)
    best: _Match | None = None
    for i in range(len(words)):
        for n in (1, 2, 3):
            gram_words = words[i:i + n]
            if len(gram_words) < n or all(w in STOPWORDS for w in gram_words):
                continue
            if gram_words[0] in STOPWORDS and n > 1 and gram_words[0] not in ("the",):
                continue
            gram = " ".join(gram_words)
            after = " ".join(words[i + n:i + n + 2])
            near_project = bool(PROJECT_WORD.search(after)) or (i > 0 and words[i - 1] in ("mera", "my", "meri"))
            for p in projects:
                for name in [p.name, *p.aliases]:
                    s = similarity(gram, name)
                    threshold = 0.72 if near_project else 0.88
                    if s >= threshold and (best is None or s > best.score):
                        best = _Match(p, s, gram)
    return best


def find_app(clause: str, apps: list[str]) -> str | None:
    low = clause.lower()
    for alias, app in APP_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and (app in apps or not apps):
            return app
    by_len = sorted(apps, key=len, reverse=True)
    for app in by_len:
        if len(app) >= 3 and re.search(rf"(?<![\w]){re.escape(app.lower())}(?![\w])", low):
            return app
    return None


def find_url(clause: str) -> str | None:
    m = LOCALHOST.search(clause)
    if m:
        return f"http://localhost:{m.group(1)}"
    m = DOMAIN.search(clause)
    if m:
        u = m.group(1)
        return u if u.lower().startswith("http") else "https://" + u
    low = clause.lower()
    for site, url in KNOWN_SITES.items():
        if re.search(rf"\b{re.escape(site)}\b", low):
            return url
    return None


_NUMS = {"das": 10, "bees": 20, "tees": 30, "chalis": 40, "pachas": 50, "pachaas": 50, "saath": 60, "sattar": 70,
         "assi": 80, "nabbe": 90, "sau": 100, "full": 100, "poora": 100, "half": 50, "aadha": 50, "aadhi": 50, "zero": 0}
_VOL = re.compile(r"\b(volume|awaaz|awaz|aawaz|sound|speaker)\b", re.I)
_BRI = re.compile(r"\b(brightness|bright|roshni|screen\s+(dim|light|bright)|dim)\b", re.I)
_UP = re.compile(r"\b(up|increase|badhao|badha do|badhaao|zyada|jyada|tez|high|louder|raise|upar|aur)\b", re.I)
_DOWN = re.compile(r"\b(down|decrease|kam|ghatao|ghata do|dheema|dheemi|dheere|low|lower|quieter|neeche|dim)\b", re.I)
_NO_SLEEP = re.compile(
    r"(\b(don'?t|dont|do not|never|mat)\b.{0,25}\bsleep\b|\bsleep\b.{0,25}\b(mat|nahi|na)\b|"
    r"\b(sone|sona|soye|so)\s+(mat|nahi|na)\b|\bjaga\s*(ke|kar|a|ae)?\s*rakho\b|\b(keep|stay)\b.{0,20}\bawake\b|"
    r"\bawake\s+rakho\b|\bcaffeinate\b|\bno\s+sleep\b)", re.I)
_ALLOW_SLEEP = re.compile(r"(\ballow\b.{0,15}\bsleep\b|\b(sone|so jane|sleep hone)\s+do\b|\bcaffeinate\s+band\b|"
                          r"\bstop keeping\b|\bnormal sleep\b)", re.I)


def _num(low: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\s*(%|percent|pratishat)?", low)
    if m:
        return max(0, min(100, int(m.group(1))))
    for w, n in _NUMS.items():
        if re.search(rf"\b{w}\b", low):
            return n
    return None


def _minutes(low: str) -> int | None:
    m = re.search(r"\b(\d{1,3}|ek|do|teen|char|aadha)\s*(ghante|ghanta|hours?|hrs?|minutes?|mins?|minute)\b", low)
    if not m:
        return None
    n = {"ek": 1, "do": 2, "teen": 3, "char": 4, "aadha": 0.5}.get(m.group(1)) or float(m.group(1))
    return int(n * 60) if m.group(2).startswith(("ghant", "h")) else int(n)


def _system_intent(low: str):
    """Hinglish/English Mac controls → (tool, args, reason) or None."""
    if _NO_SLEEP.search(low):
        mins = _minutes(low)
        return ("system.control", {"action": "keep_awake", **({"minutes": mins} if mins else {})},
                "Keep the Mac awake" + (f" for {mins} min" if mins else " until you say otherwise"))
    if _ALLOW_SLEEP.search(low):
        return ("system.control", {"action": "allow_sleep"}, "Let the Mac sleep normally again")
    if re.search(r"\b(unmute|mute hatao|awaaz wapas|sound on)\b", low):
        return ("system.control", {"action": "unmute"}, "Unmute the Mac")
    if re.search(r"\b(mute|chup|silent|awaaz band|sound off)\b", low) and not re.search(r"\b(video|youtube|spotify|gaana)\b", low):
        return ("system.control", {"action": "mute"}, "Mute the Mac")
    if _VOL.search(low):
        n = _num(low)
        if n is not None and not _UP.search(low) and not _DOWN.search(low) or re.search(r"\b(pe|par|to|at)\s+\d", low):
            return ("system.control", {"action": "volume_set", "value": n if n is not None else 50}, f"Set volume to {n}%")
        if _DOWN.search(low):
            return ("system.control", {"action": "volume_down"}, "Turn the volume down")
        if _UP.search(low):
            return ("system.control", {"action": "volume_up"}, "Turn the volume up")
        if re.search(r"\b(kitna|kitni|what|level|status)\b", low):
            return ("system.status", {}, "Check volume and other Mac status")
    if _BRI.search(low):
        n = _num(low)
        if n is not None and (re.search(r"\b(pe|par|to|at)\s+\d", low) or not (_UP.search(low) or _DOWN.search(low))):
            return ("system.control", {"action": "brightness_set", "value": n}, f"Set screen brightness to {n}%")
        if _DOWN.search(low):
            return ("system.control", {"action": "brightness_down"}, "Lower the screen brightness")
        if _UP.search(low):
            return ("system.control", {"action": "brightness_up"}, "Raise the screen brightness")
    if re.search(r"\bdark\s*mode\b", low):
        if re.search(r"\b(off|band|hatao|disable)\b", low):
            return ("system.control", {"action": "dark_mode_off"}, "Turn dark mode off")
        if re.search(r"\b(toggle|switch|badlo)\b", low):
            return ("system.control", {"action": "dark_mode_toggle"}, "Toggle dark mode")
        return ("system.control", {"action": "dark_mode_on"}, "Turn dark mode on")
    if re.search(r"\blight\s*mode\b", low):
        return ("system.control", {"action": "dark_mode_off"}, "Switch to light mode")
    if re.search(r"\b(screenshot|screen shot|screen capture)\b", low):
        return ("system.control", {"action": "screenshot"}, "Take a screenshot to the Desktop")
    if re.search(r"\b(battery|charge|charging)\b", low) and not re.search(r"\b(project|app)\b", low):
        return ("system.status", {}, "Check battery and Mac status")
    if re.search(r"\b(screen|display)\b.{0,15}\b(off|band|sula|sleep)\b", low):
        return ("system.control", {"action": "display_sleep"}, "Turn the display off")
    mac = r"(mac|laptop|computer|system|pc)"
    if re.search(rf"\block\b.{{0,20}}(\b{mac}\b|\bscreen\b)|\b{mac}\b.{{0,15}}\block\b|^\s*lock\s+(karo|kar do|it)", low):
        return ("system.power", {"action": "lock"}, "Lock the Mac")
    if re.search(rf"\b(restart|reboot)\b", low) and re.search(rf"\b{mac}\b|^\s*(restart|reboot)\b", low):
        return ("system.power", {"action": "restart"}, "Restart the Mac")
    if re.search(rf"\b(shut\s*down|power\s*off|switch\s*off)\b", low) or re.search(rf"\b{mac}\b\s+(band|off)\s+(karo|kar do)", low):
        return ("system.power", {"action": "shutdown"}, "Shut down the Mac")
    if re.search(rf"\b(sula do|so jao|go to sleep|sleep (karo|kar do|now|mode))\b", low) or re.search(rf"\b{mac}\b.{{0,15}}\bsleep\b", low):
        return ("system.power", {"action": "sleep"}, "Put the Mac to sleep")
    return None


def _note_body(clause: str) -> tuple[str, str]:
    m = re.search(r"\b(?:ki|that|:|ke liye|about)\b\s*(.+)$", clause, re.I)
    body = (m.group(1) if m else re.sub(NOTE_VERB, "", re.sub(NOTE, "", clause))).strip(" :,-")
    body = body or clause
    title = " ".join(body.split()[:7]).strip()
    return title[:1].upper() + title[1:], body


def _query_token(clause: str) -> str | None:
    m = FILENAME.search(clause)
    if m:
        return m.group(1)
    words = [w for w in re.findall(r"[\w.-]+", clause) if w.lower() not in STOPWORDS and not FIND.search(w)
             and not FILES.search(w) and w.lower() not in ("naam", "name", "called", "wali", "jiska")]
    return words[0] if words else None


class RulePlanner(Planner):
    name = "rules"

    async def plan(self, text: str, ctx: PlanningContext) -> Plan:
        m = ctx.manifest
        text_n = _norm(text)
        projects = m.projects
        tools = {t.id for t in m.tools}
        current: ProjectSummary | None = next((p for p in projects if p.id == ctx.last_project_id), None)
        if current is None and len(projects) == 1:
            current = projects[0]
        steps: list[PlanStep] = []
        browser_ctx: dict[str, str | None] = {"name": None, "site": None}
        notes: list[str] = []
        needs_project: list[str] = []

        def proj() -> ProjectSummary | None:
            return current

        def add(tool: str, args: dict, reason: str) -> None:
            if tool not in tools:
                notes.append(f"'{tool}' is not available on this desktop")
                return
            if any(s.tool == tool and s.args == args for s in steps):
                return
            steps.append(PlanStep(id=f"s{len(steps) + 1}", tool=tool, args=args, reason=reason))

        for clause in _clauses(text_n):
            pm = find_project(clause, projects)
            if pm:
                current = pm.project
            p = proj()
            low = clause.lower()

            def need(what: str) -> bool:
                if p is None:
                    needs_project.append(what)
                    return False
                return True

            # ---- Mac system controls
            sysplan = _system_intent(low)
            if sysplan:
                tool, args, reason = sysplan
                add(tool, args, reason)
                continue
            # ---- notes
            if NOTE.search(low) and NOTE_VERB.search(low):
                title, body = _note_body(clause)
                add("notes.create", {"title": title, "body": body}, f"Save a note: “{title}”")
                continue
            # ---- browser (user's own Chrome/Brave/Edge/Vivaldi/Safari)
            named = next((b for alias, b in BROWSER_ALIASES.items() if re.search(rf"\b{alias}\b", low)), None)
            if named:
                browser_ctx["name"] = named
            bargs = {"browser": browser_ctx["name"]} if browser_ctx["name"] else {}
            bname = browser_ctx["name"] or "the browser"
            site_m = SEARCH_SITE.search(low)
            wants_play = bool(M_PLAY.search(low)) and not M_PAUSE.search(low)
            if site_m:
                browser_ctx["site"] = _norm_site(site_m.group(1))
            ctx_site = browser_ctx["site"]
            words_q = [w for w in re.findall(r"[\w'&.+#-]+", clause) if w.lower() not in SEARCH_FILLER]
            # "play/open the first|second video/result" on the results page that is already open
            om = ORDINAL_RESULT.search(low)
            if om and not SEARCH_VERB.search(low):
                n = ORDINALS[om.group(1).lower()]
                if n == 1 and steps and steps[-1].tool == "browser.search" and steps[-1].args.get("site") == "youtube":
                    steps[-1].args["play_first"] = True
                    steps[-1].reason = f"Play “{steps[-1].args['query']}” on YouTube"
                    continue
                add("browser.open_result", {"index": n, **bargs},
                    f"Open the {om.group(1).lower()} {om.group(2).lower()} on the open page")
                continue
            # "...search kesariya and play it": attach "play it" to the YouTube search just planned
            if (MUSIC_VERB.search(low) or M_PLAY.search(low)) and steps and steps[-1].tool == "browser.search" \
                    and steps[-1].args.get("site") == "youtube" and all(w.lower() in PLAY_IT_WORDS for w in words_q):
                steps[-1].args["play_first"] = True
                steps[-1].reason = f"Play “{steps[-1].args['query']}” on YouTube"
                continue
            # "search X here / in this tab": the site that is open right now, same tab
            if CURRENT_SITE.search(low) and SEARCH_VERB.search(low) and not site_m:
                q = " ".join(w for w in words_q if not CURRENT_SITE.search(w.lower()) and w.lower() not in
                             {"yahan", "yaha", "isi", "isme", "is", "iss", "this", "page", "site", "tab", "website", "current", "same", "here"})
                if q:
                    add("browser.search", {"query": q, "site": "current", **bargs},
                        f"Search “{q}” on the open site" + (f" in {bname}" if bargs else ""))
                    continue
            # "open github and search fastapi" / "open youtube and play kesariya": later clauses inherit the site
            if not site_m and ctx_site and words_q and not MEDIA_NOUN.search(low) and not CURRENT_SITE.search(low) \
                    and (SEARCH_VERB.search(low) or (ctx_site == "youtube" and MUSIC_VERB.search(low))):
                q = " ".join(words_q)
                home = KNOWN_SITES.get(ctx_site, "")
                steps[:] = [st for st in steps if not (st.tool == "url.open" and home
                                                        and st.args.get("url", "").rstrip("/") == home.rstrip("/"))]
                play = ctx_site == "youtube" and bool(MUSIC_VERB.search(low))
                site_key = ctx_site if ctx_site in SEARCHABLE else "google"
                add("browser.search", {"query": q, "site": site_key, **({"play_first": True} if play else {}), **bargs},
                    f"{'Play' if play else 'Search'} “{q}” on {site_key.title().replace('Youtube', 'YouTube').replace('Github', 'GitHub')}"
                    + (f" in {bname}" if bargs else ""))
                continue
            controlling = bool(M_PAUSE.search(low) or re.search(r"\b(resume|continue|dobara)\b", low))
            if site_m and not controlling and (SEARCH_VERB.search(low) or wants_play or re.search(r"\b(dikhao|videos?)\b", low)):
                words = [w for w in re.findall(r"[\w'&.+#-]+", clause) if w.lower() not in SEARCH_FILLER]
                query = " ".join(words).strip()
                if query:
                    site = _norm_site(site_m.group(1))
                    play = site == "youtube" and wants_play
                    add("browser.search", {"query": query, "site": site, **({"play_first": True} if play else {}), **bargs},
                        f"{'Play' if play else 'Search'} “{query}” on {site.title()}" + (f" in {bname}" if bargs else ""))
                    continue
            if SEARCH_VERB.search(low) and not site_m and not FILES.search(low) and not FILENAME.search(clause) \
                    and (bargs or re.search(r"\b(web|internet|online|google)\b", low) or re.match(r"^\s*search\b", low)):
                words = [w for w in re.findall(r"[\w'&.+#-]+", clause) if w.lower() not in SEARCH_FILLER | {"web", "internet", "online"}]
                if words:
                    q = " ".join(words)
                    add("browser.search", {"query": q, "site": "google", **bargs}, f"Search the web for “{q}”")
                    continue
            if B_NEW_TAB.search(low):
                url = find_url(clause)
                add("browser.control", {"action": "new_tab", **({"url": url} if url else {}), **bargs},
                    f"Open a new tab{' with ' + (urlparse(url).netloc or url) if url else ''} in {bname}")
                continue
            if B_TAB.search(low) and B_CLOSE.search(low) and not re.search(r"\btabs\b", low):
                add("browser.control", {"action": "close_tab", **bargs}, f"Close the current tab in {bname}")
                continue
            if B_NEXT_TAB.search(low):
                add("browser.control", {"action": "next_tab", **bargs}, f"Go to the next tab in {bname}")
                continue
            if B_PREV_TAB.search(low):
                add("browser.control", {"action": "previous_tab", **bargs}, f"Go to the previous tab in {bname}")
                continue
            sw = next((mt for p_ in B_SWITCH if (mt := p_.search(clause))), None)
            if sw:
                q = " ".join(w for w in sw.group("q").split() if w.lower() not in STOPWORDS | {"us", "uss", "is", "wo", "woh"})
                if q:
                    add("browser.control", {"action": "switch_tab", "query": q, **bargs}, f"Switch to the “{q}” tab")
                    continue
            if B_RELOAD.search(low):
                add("browser.control", {"action": "reload", **bargs}, f"Reload the page in {bname}")
                continue
            if B_BACK.search(low):
                add("browser.control", {"action": "back", **bargs}, f"Go back a page in {bname}")
                continue
            if B_FWD.search(low):
                add("browser.control", {"action": "forward", **bargs}, f"Go forward a page in {bname}")
                continue
            if B_VIDEO.search(low) and (M_PAUSE.search(low) or M_PLAY.search(low)) and not MEDIA_NOUN.search(low.replace("music", "")):
                act = "pause" if M_PAUSE.search(low) else "play"
                add("browser.media", {"action": act, **bargs}, f"{act.title()} the video in {bname}")
                continue
            if B_READ.search(low) and not FILENAME.search(clause):
                add("browser.read_page", bargs, f"Read the current page in {bname}")
                continue
            # bare "play kesariya" / "kesariya bajao" (no site, no project) -> find it on Spotify
            if MUSIC_VERB.search(low) and not MEDIA_NOUN.search(low) and not site_m and not B_VIDEO.search(low) \
                    and not pm and not SERVER.search(low) and not find_app(clause, m.apps) and "Spotify" in m.apps:
                words = [w for w in re.findall(r"[\w'&.-]+", clause) if w.lower() not in MEDIA_FILLER]
                if words:
                    q = " ".join(words)
                    add("media.search", {"query": q}, f"Find “{q}” on Spotify")
                    continue
            # ---- music (Spotify / Apple Music)
            if MEDIA_NOUN.search(low) and not SERVER.search(low.replace("music", "")) and not OPEN.search(low):
                player = "Music" if re.search(r"\bapple music\b|\bmusic app\b", low) else None
                pargs = {"player": player} if player else {}
                if M_WHAT.search(low) and re.search(r"\b(chal raha|chal rha|baj raha|playing|chal rahi)\b", low):
                    add("media.control", {"action": "status", **pargs}, "Check which song is playing")
                    continue
                if M_NEXT.search(low):
                    add("media.control", {"action": "next", **pargs}, "Skip to the next song")
                    continue
                if M_PREV.search(low):
                    add("media.control", {"action": "previous", **pargs}, "Go back to the previous song")
                    continue
                if M_PAUSE.search(low):
                    add("media.control", {"action": "pause", **pargs}, "Pause the music")
                    continue
                if re.search(r"\b(resume|continue|dobara|wapas|wapis|phir se|fir se)\b", low):
                    add("media.control", {"action": "play", **pargs}, "Resume the music")
                    continue
                if M_PLAY.search(low):
                    words = [w for w in re.findall(r"[\w'&.-]+", clause) if w.lower() not in MEDIA_FILLER]
                    query = " ".join(words).strip()
                    if query and player is None:
                        add("media.search", {"query": query}, f"Find “{query}” on Spotify")
                    else:
                        add("media.control", {"action": "play", **pargs}, "Play / resume the music")
                    continue
            # ---- stop
            if STOP.search(low) and (SERVER.search(low) or PROCS.search(low) or pm or "sab" in low or "all" in low):
                args = {"project": p.id} if p and (pm or SERVER.search(low)) else {}
                add("process.stop", args, f"Stop the {'dev server of ' + p.name if args else 'processes'} Perry started")
                continue
            # ---- tests / build / lint / typecheck
            script = None
            if TESTS.search(low):
                script = "test"
            elif BUILD.search(low):
                script = "build"
            elif LINT.search(low):
                script = "lint"
            elif TYPECHECK.search(low) and not ERRORS.search(low):
                script = "typecheck"
            if script and not (OPEN.search(low) and not START.search(low) and script == "build"):
                if need(f"run {script}"):
                    add("dev.run_script", {"project": p.id, "script": script},
                        f"Run the '{script}' script of {p.name} and report the result")
                continue
            # ---- dev server
            if (SERVER.search(low) and (START.search(low) or OPEN.search(low) and "server" in low)) or \
               re.search(r"\b(npm|pnpm|yarn|bun) (run )?(dev|start)\b", low):
                if need("start the dev server"):
                    add("dev.start_server", {"project": p.id}, f"Start {p.name}'s development server")
                    if ERRORS.search(low):
                        add("process.logs", {"project": p.id}, f"Check {p.name}'s server output for errors")
                continue
            # ---- errors / logs
            if ERRORS.search(low):
                if need("check errors"):
                    add("process.logs", {"project": p.id}, f"Check {p.name}'s server output for errors")
                continue
            # ---- git
            if COMMITS.search(low) and (GIT.search(low) or RECENT.search(low)):
                if need("show commits"):
                    nums = {"ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
                            "paanch": 5, "panch": 5, "five": 5, "das": 10, "ten": 10}
                    mn = re.search(r"\b(\d{1,2}|" + "|".join(nums) + r")\s+(?:commits?|changes)\b", low)
                    limit = min(20, int(mn.group(1)) if mn and mn.group(1).isdigit() else nums.get(mn.group(1), 5) if mn else 5)
                    add("git.log", {"project": p.id, "limit": limit}, f"Show the last {limit} commits of {p.name}")
                continue
            if GIT.search(low) or (GIT_CHANGES.search(low) and (pm or PROJECT_WORD.search(low) or p)):
                if need("check git status"):
                    add("git.status", {"project": p.id}, f"Check git status of {p.name}")
                continue
            # ---- tabs / processes
            if TABS.search(low):
                add("browser.tabs", {"browser": browser_ctx["name"]} if browser_ctx["name"] else {},
                    f"List open tabs{' in ' + browser_ctx['name'] if browser_ctx['name'] else ''}")
                continue
            if PROCS.search(low) and SHOW.search(low):
                add("process.list", {}, "List processes Perry started")
                continue
            # ---- files
            if FIND.search(low) and (FILES.search(low) or FILENAME.search(clause)):
                q = _query_token(clause)
                if q:
                    args = {"query": q, **({"project": p.id} if p else {})}
                    add("files.find", args, f"Find files named like “{q}”" + (f" in {p.name}" if p else ""))
                    continue
            if FILENAME.search(clause) and (READ.search(low) or OPEN.search(low) or SHOW.search(low)):
                fname = FILENAME.search(clause).group(1)
                args = {"path": fname, **({"project": p.id} if p else {})}
                add("files.read", args, f"Read {fname}" + (f" from {p.name}" if p else ""))
                continue
            if FILES.search(low) and SHOW.search(low):
                if need("list files"):
                    add("files.list", {"project": p.id, "path": "."}, f"List the files in {p.name}")
                continue
            if SCRIPTS.search(low) and (SHOW.search(low) or pm):
                if need("inspect the project"):
                    add("project.info", {"project": p.id}, f"Read {p.name}'s scripts and setup")
                continue
            # ---- focus / open
            app = find_app(clause, m.apps)
            if FOCUS.search(low) and app:
                add("app.focus", {"app": app}, f"Switch to {app}")
                continue
            # Only open when asked to. A bare project mention ("Dineo") may open it, but a
            # longer sentence whose verb we didn't recognise must not turn into an action.
            bare_mention = pm is not None and not app and len(low.split()) <= 3 and not SERVER.search(low)
            if OPEN.search(low) or bare_mention:
                url = find_url(clause)
                if pm or (PROJECT_WORD.search(low) and p and not app and not url):
                    if p:
                        add("project.open", {"project": p.id, "target": "editor"},
                            f"Open {p.name} in {m.editor or 'the editor'}")
                    continue
                target = app if app in BROWSER_NAMES else browser_ctx["name"]
                if url and target:
                    add("url.open", {"url": url, "browser": target}, f"Open {urlparse(url).netloc or url} in {target}")
                    continue
                if url and not (app and not DOMAIN.search(clause) and not LOCALHOST.search(clause)):
                    add("url.open", {"url": url}, f"Open {urlparse(url).netloc or url} in the browser")
                    continue
                if app:
                    add("app.open", {"app": app}, f"Open {app}")
                    continue
                if url:
                    add("url.open", {"url": url}, f"Open {urlparse(url).netloc} in the browser")
                    continue
            if app and len(low.split()) <= 2 and not re.search(r"\b(what|kya|kaisa|how)\b", low):
                add("app.open", {"app": app}, f"Open {app}")
                continue
            notes.append(clause)

        plan = Plan(planner=self.name, project_id=current.id if current else None)
        if needs_project and not steps:
            names = ", ".join(p.name for p in projects) or "none configured"
            plan.reply_without_action = (
                f"Kaunsa project? Mujhe batao kis project ke liye ({names}). "
                if projects else "Is desktop par koi project configure nahi hai. `perry-agent projects add` se add karo."
            )
            return plan
        if not steps:
            plan.reply_without_action = (
                "Ye command samajh nahi aaya. Aise bol sakte ho: “Dineo project kholo”, “git status check karo”, "
                "“Chrome mein YouTube kholo”, “battery kitni hai”."
            )
            plan.understanding = "No supported action recognised."
            return plan
        plan.steps = steps
        plan.understanding = "; ".join(s.reason for s in steps)
        if notes:
            plan.understanding += f" (ignored: {', '.join(notes[:3])})"
        return plan
