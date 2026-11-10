"""Builds the spoken/visible reply from the *actual* step results.

Replies are composed from structured fields only (branch names, counts, URLs, exit
codes). Raw tool output — terminal logs, file contents, web pages — is shown on screen
but never spoken or interpreted as instructions.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from perry_protocol import Plan, PlanStep, StepStatus, TaskStatus


def _spoken_url(url: str | None) -> str:
    if not url:
        return ""
    u = urlparse(url)
    host = (u.hostname or "").replace("127.0.0.1", "localhost").replace("0.0.0.0", "localhost")
    return f"{host} port {u.port}" if u.port else host


def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _short_err(e: str | None) -> str:
    e = (e or "kuch gadbad hui").strip()
    e = re.sub(r"\s+", " ", e)
    return e[:140]


def _step_line(step: PlanStep, style: str) -> str | None:
    o = step.output or {}
    en = style == "english"
    t = step.tool
    if step.status == StepStatus.FAILED:
        what = step.reason.rstrip(".")
        return (f"I couldn't {what[0].lower() + what[1:]}: {_short_err(step.error)}." if en
                else f"{what} nahi ho paaya: {_short_err(step.error)}.")
    if step.status != StepStatus.SUCCEEDED:
        return None
    if t == "project.open":
        return (f"Opened {o.get('project')} in {o.get('opened_with')}." if en
                else f"{o.get('project')} project {o.get('opened_with')} mein khol diya.")
    if t == "git.status":
        branch = o.get("branch") or "unknown"
        if o.get("clean"):
            s = (f"Git is clean on branch {branch}." if en else f"Git status clean hai, branch {branch} pe.")
        else:
            m, u, st = len(o.get("modified", [])), len(o.get("untracked", [])), len(o.get("staged", []))
            parts = []
            if m:
                parts.append(_n(m, "modified file", "modified files"))
            if st:
                parts.append(_n(st, "staged file", "staged files"))
            if u:
                parts.append(_n(u, "untracked file", "untracked files"))
            joined = ", ".join(parts[:-1]) + (" and " if en else " aur ") + parts[-1] if len(parts) > 1 else parts[0]
            verb = "hai" if m + st + u == 1 else "hain"
            s = (f"On branch {branch} there {'is' if m + st + u == 1 else 'are'} {joined}." if en
                 else f"Branch {branch} pe {joined} {verb}.")
        if o.get("behind"):
            s += (f" It is {o['behind']} commits behind remote." if en
                  else f" Remote se {o['behind']} commits peeche hai.")
        return s
    if t == "git.log":
        c = (o.get("commits") or [{}])[0]
        return (f"Latest commit: {c.get('subject', '')}." if en
                else f"Latest commit hai: {c.get('subject', '')}.")
    if t in ("dev.start_server", "dev.run_script") and o.get("passed") is None:
        errs = len(o.get("error_lines") or [])
        where = _spoken_url(o.get("url"))
        if o.get("already_running"):
            s = (f"The dev server was already running{' on ' + where if where else ''}." if en
                 else f"Dev server pehle se chal raha hai{', ' + where + ' pe' if where else ''}.")
        elif o.get("status") == "exited":
            s = (f"The server stopped with exit code {o.get('exit_code')}." if en
                 else f"Server start nahi hua, exit code {o.get('exit_code')} aaya.")
        elif where:
            s = (f"The development server is running on {where}." if en
                 else f"Development server start ho gaya, {where} pe chal raha hai.")
        else:
            s = ("The server is starting but isn't ready yet." if en
                 else "Server start ho raha hai, abhi ready nahi hua.")
        if errs and o.get("status") != "exited":
            s += (f" I see {_n(errs, 'error line', 'error lines')} in its output." if en
                  else f" Output mein {errs} error lines dikh rahi hain, screen pe check karo.")
        return s
    if t == "dev.run_script":
        name = o.get("script", "script")
        if o.get("passed"):
            return f"{name} passed." if en else f"{name} successfully chal gaya, sab pass."
        return (f"{name} failed with exit code {o.get('exit_code')}." if en
                else f"{name} fail ho gaya, exit code {o.get('exit_code')}. Details screen pe hain.")
    if t == "process.logs":
        errs = len(o.get("error_lines") or [])
        code = o.get("probe_status")
        if code and code >= 500:
            return (f"Yes — the page returns HTTP {code}, and there are {_n(errs, 'error line', 'error lines')} in the output. Details are on your screen." if en
                    else f"Haan, errors aa rahe hain. Page load karne pe HTTP {code} aaya, aur output mein {errs} error lines hain. Details screen pe hain.")
        if o.get("probe_error") and not code:
            if errs:
                return (f"Yes — the page didn't load and there are {_n(errs, 'error line', 'error lines')} in the output. Details are on your screen." if en
                        else f"Haan, errors aa rahe hain. Page load nahi hua, aur output mein {errs} error lines hain. Details screen pe hain.")
            return ("The server didn't answer when I loaded the page." if en
                    else "Page load karne pe server ne response nahi diya. Output screen pe dekho.")
        if errs:
            return (f"There are {_n(errs, 'error line', 'error lines')} in the output — they're on your screen." if en
                    else f"Haan, output mein {errs} error lines hain. Screen pe dikha di hain.")
        return ("No errors in the output so far." if en else "Abhi tak koi errors nahi aa rahe, sab theek hai.")
    if t == "process.stop":
        n = len(o.get("stopped") or [])
        return (f"Stopped {_n(n, 'process', 'processes')}." if en else f"{n} process band kar diya.")
    if t == "process.list":
        n = len([p for p in o.get("processes", []) if p.get("status") == "running"])
        return (f"{_n(n, 'process is', 'processes are')} running." if en else f"{n} process chal rahe hain.")
    if t == "app.open":
        return f"Opened {o.get('app')}." if en else f"{o.get('app')} khol diya."
    if t == "app.focus":
        return f"Switched to {o.get('app')}." if en else f"{o.get('app')} pe switch kar diya."
    if t == "url.open":
        host = urlparse(o.get("url", "")).hostname or "link"
        where = o.get("browser")
        return (f"Opened {host}{' in ' + where if where else ''}." if en
                else f"{host} khol diya{', ' + where + ' mein' if where else ''}.")
    if t == "project.info":
        scripts = ", ".join(o.get("runnable_scripts") or []) or "none"
        return (f"{o.get('project')} uses {o.get('framework') or 'no detected framework'}; scripts: {scripts}." if en
                else f"{o.get('project')} mein {o.get('framework') or 'koi framework detect nahi hua'} hai, scripts hain: {scripts}.")
    if t == "files.list":
        n = len(o.get("entries") or [])
        return f"There are {n} items in that folder." if en else f"Folder mein {n} items hain."
    if t == "files.find":
        n = len(o.get("matches") or [])
        return f"Found {_n(n, 'match', 'matches')}." if en else f"{n} files mili hain."
    if t == "files.read":
        name = (o.get("path") or "").rsplit("/", 1)[-1]
        return f"Here is {name}." if en else f"{name} screen pe dikha di hai."
    if t == "notes.create":
        return "Saved the note." if en else "Note save kar diya."
    if t == "browser.tabs":
        n = len(o.get("tabs") or [])
        return f"{_n(n, 'tab is', 'tabs are')} open." if en else f"{n} tabs khule hain."
    if t == "media.control":
        song = " — ".join(x for x in (o.get("track"), o.get("artist")) if x)
        act, player, st = o.get("action"), o.get("player", "Spotify"), o.get("state")
        if st == "not running":
            return f"{player} isn't running." if en else f"{player} abhi chal nahi raha hai."
        if act == "pause":
            return f"Paused {player}." if en else f"{player} pause kar diya."
        if act in ("next", "previous"):
            return (f"Now playing {song}." if en else f"Ab chal raha hai: {song}.") if song else ("Done." if en else "Ho gaya.")
        if act == "status":
            if not song:
                return f"Nothing is loaded in {player}." if en else f"{player} mein abhi koi gaana nahi hai."
            return (f"{song} is {st}." if en else
                    f"{song} {'chal raha hai' if st == 'playing' else 'paused hai'}.")
        return (f"Playing {song} on {player}." if en else f"{player} pe {song} chala diya.") if song else \
            (f"Resumed {player}." if en else f"{player} resume kar diya.")
    if t == "media.play_track":
        song = " — ".join(x for x in (o.get("track"), o.get("artist")) if x) or "the song"
        return f"Playing {song} on Spotify." if en else f"Spotify pe {song} chala diya."
    if t == "media.search":
        q = o.get("query")
        return (f"I opened Spotify's search for “{q}” — tap the song to play it." if en
                else f"Spotify mein “{q}” search khol diya hai, jo gaana chahiye us pe play dabao.")
    if t == "browser.search":
        site = (o.get("site") or "web").title().replace("Youtube", "YouTube").replace("Github", "GitHub")
        if o.get("played"):
            return (f"Playing “{o['played'][:70]}” on YouTube." if en else f"YouTube pe “{o['played'][:70]}” chala diya.")
        base = (f"Searched {site} for “{o.get('query')}”" if en else f"{site} pe “{o.get('query')}” search kar diya")
        base += (f" in {o['browser']}" if en else f", {o['browser']} mein") if o.get("browser") else ""
        base += "."
        note = o.get("note") or ""
        if "Apple Events" in note:
            b = o.get("browser") or "the browser"
            base += (f" To let me start videos, turn on “Allow JavaScript from Apple Events” in {b}'s Developer menu." if en
                     else f" Video khud chalane ke liye {b} mein “Allow JavaScript from Apple Events” on karna hoga. Abhi results khule hain.")
        elif note:
            base += (" The first video didn't start, so pick one from the results." if en
                     else " Pehla video khud start nahi hua, results mein se chun lo.")
        return base
    if t == "browser.control":
        b, title, act = o.get("browser", "browser"), (o.get("title") or "")[:60], o.get("action")
        lines = {
            "new_tab": ("Opened a new tab in {b}.", "{b} mein naya tab khol diya."),
            "close_tab": ("Closed the tab.", "Tab band kar diya."),
            "reload": ("Reloaded the page.", "Page reload kar diya."),
            "back": ("Went back to {title}.", "Pichle page pe aa gaye: {title}."),
            "forward": ("Went forward to {title}.", "Agle page pe aa gaye: {title}."),
            "next_tab": ("Switched to {title}.", "{title} wale tab pe aa gaye."),
            "previous_tab": ("Switched to {title}.", "{title} wale tab pe aa gaye."),
            "switch_tab": ("Switched to {title}.", "{title} wale tab pe switch kar diya."),
            "focus": ("Brought {b} to the front.", "{b} saamne le aaya."),
        }
        if act == "close_tab" and o.get("closed"):
            c = o["closed"][:60]
            return f"Closed the “{c}” tab." if en else f"“{c}” tab band kar diya."
        en_l, hi_l = lines.get(act, ("Done.", "Ho gaya."))
        return (en_l if en else hi_l).format(b=b, title=title or b)
    if t == "browser.media":
        stt = o.get("state")
        if stt == "no-media":
            return "There's no video on this page." if en else "Is page pe koi video nahi mila."
        return ("Paused the video." if en else "Video pause kar diya.") if stt == "paused" else \
            ("The video is playing." if en else "Video chala diya.")
    if t == "browser.read_page":
        title = (o.get("title") or "this page")[:70]
        return (f"I read “{title}” — the text is on your screen." if en
                else f"“{title}” page padh liya, text screen pe dikha diya hai.")
    if t == "system.status":
        b = o.get("battery") or {}
        parts_en, parts_hi = [], []
        if b.get("present"):
            charging = "charging" in (b.get("state") or "") or b.get("source") == "AC Power"
            parts_en.append(f"battery is at {b.get('percent')}%{' and charging' if charging else ''}")
            parts_hi.append(f"battery {b.get('percent')}% hai{', charge ho rahi hai' if charging else ''}")
        if o.get("volume") is not None:
            parts_en.append("sound is muted" if o.get("muted") else f"volume is {o['volume']}%")
            parts_hi.append("sound mute hai" if o.get("muted") else f"volume {o['volume']}% pe hai")
        if o.get("brightness") is not None:
            parts_en.append(f"brightness is {o['brightness']}%")
            parts_hi.append(f"brightness {o['brightness']}%")
        if o.get("keep_awake"):
            parts_en.append("and I'm keeping it awake")
            parts_hi.append("aur Mac ko jaga ke rakha hai")
        return ("Your Mac's " + ", ".join(parts_en) + ".") if en else ("Mac ki " + ", ".join(parts_hi) + ".")
    if t == "system.control":
        a = o.get("action", "")
        if a.startswith("volume"):
            return f"Volume is now {o.get('volume')}%." if en else f"Volume ab {o.get('volume')}% hai."
        if a == "mute":
            return "Muted." if en else "Mac mute kar diya."
        if a == "unmute":
            return f"Unmuted, volume {o.get('volume')}%." if en else f"Unmute kar diya, volume {o.get('volume')}% hai."
        if a.startswith("brightness"):
            return f"Brightness is now {o.get('brightness')}%." if en else f"Brightness ab {o.get('brightness')}% hai."
        if a == "keep_awake":
            until = o.get("keep_awake_until")
            return ((f"I'll keep the Mac awake until {until}." if until else "I'll keep the Mac awake until you tell me to stop.")
                    if en else (f"Mac {until} tak jaga rahega." if until else "Theek hai, Mac ab sleep nahi hoga jab tak aap na bolo."))
        if a == "allow_sleep":
            return "The Mac can sleep normally again." if en else "Ab Mac normal tarah se sleep ho sakta hai."
        if a.startswith("dark_mode"):
            on = o.get("dark_mode")
            return (f"Dark mode is {'on' if on else 'off'}." if en else f"Dark mode {'on' if on else 'off'} kar diya.")
        if a == "display_sleep":
            return "Display is off." if en else "Screen band kar di."
        if a == "screenshot":
            return "Screenshot saved to your Desktop." if en else "Screenshot le liya, Desktop pe save hai."
    if t == "system.power":
        a = o.get("action")
        en_map = {"sleep": "Putting the Mac to sleep.", "lock": "Locked the Mac.", "restart": "Restarting the Mac.",
                  "shutdown": "Shutting down the Mac."}
        hi_map = {"sleep": "Mac ko sula raha hoon.", "lock": "Mac lock kar diya.", "restart": "Mac restart ho raha hai.",
                  "shutdown": "Mac shut down ho raha hai."}
        return en_map.get(a, "Done.") if en else hi_map.get(a, "Ho gaya.")
    if t == "terminal.run":
        code = o.get("exit_code")
        if o.get("background"):
            return "Started it in the background." if en else "Command background mein chala diya."
        if code is None:
            return "The command timed out." if en else "Command time out ho gaya."
        if code == 0:
            return ("Done — the output is on your screen." if en else "Command chal gaya, output screen pe hai.")
        return (f"The command failed with exit code {code}; the output is on your screen." if en
                else f"Command fail hua, exit code {code}. Output screen pe hai.")
    if t == "system.notify":
        return "Notification shown." if en else "Notification dikha diya."
    return None


def compose_reply(plan: Plan | None, status: TaskStatus, style: str, error: str | None = None) -> str:
    en = style == "english"
    if status == TaskStatus.REJECTED:
        return "Okay, I didn't run anything." if en else "Theek hai, maine kuch nahi chalaya."
    if status == TaskStatus.CANCELLED:
        done = [s for s in (plan.steps if plan else []) if s.status == StepStatus.SUCCEEDED]
        return ("Stopped. " if en else "Task rok diya. ") + (" ".join(filter(None, (_step_line(s, style) for s in done))))
    if plan and plan.reply_without_action:
        return plan.reply_without_action
    if error and not (plan and plan.steps):
        return (f"Something went wrong: {_short_err(error)}" if en else f"Kuch gadbad ho gayi: {_short_err(error)}")
    lines = [l for l in (_step_line(s, style) for s in (plan.steps if plan else [])) if l]
    skipped = [s for s in (plan.steps if plan else []) if s.status == StepStatus.SKIPPED]
    if skipped:
        lines.append(f"Skipped {len(skipped)} remaining steps." if en
                     else f"Baaki {len(skipped)} steps skip kar diye.")
    if not lines:
        return "Done." if en else "Ho gaya."
    did_something = any(s.risk.value != "read" and not (s.tool == "media.control" and s.args.get("action") == "status")
                        for s in plan.steps)
    opener = "" if en or not did_something else ("Ho gaya! " if all(s.status == StepStatus.SUCCEEDED for s in plan.steps) else "")
    return opener + " ".join(lines)
