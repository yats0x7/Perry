"""Shell-command guard shared by the server policy and the desktop agent.

Terminal commands are a user-requested capability. Every command is shown verbatim on the phone
and needs explicit approval, and the categories below are refused outright, before approval, on
both the server and the desktop. This is a guard-rail for honest mistakes and mis-hearings, not a
sandbox: Perry runs commands as the logged-in user.
"""

from __future__ import annotations

import re

_BLOCKS: list[tuple[str, str]] = [
    (r"(^|[;&|`(]\s*|\s)(sudo|su|doas)\s", "it needs an admin password, which Perry can't type — run it yourself in Terminal"),
    (r"\brm\s+(-\w*[rRf]\w*\s+)", "recursive or forced deletes (rm -r / rm -f) are blocked"),
    (r"\b(mkfs\w*|newfs_\w+|fdisk)\b", "disk formatting is blocked"),
    (r"\bdiskutil\s+(erase\w*|partition\w*|zero\w*|secureErase|reformat|apfs\s+delete\w*)", "erasing or partitioning disks is blocked"),
    (r"\bdd\b.*\bof=", "raw disk writes (dd of=) are blocked"),
    (r">\s*/dev/r?disk", "raw disk writes are blocked"),
    (r":\(\)\s*\{", "fork bombs are blocked"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|fish|python\d*|perl|ruby|node)\b",
     "piping a download straight into a shell is blocked"),
    (r"\b(shutdown|reboot|halt)\b", "use “restart / shut down the Mac” instead (it asks for approval)"),
    (r"\b(csrutil|nvram|kextload|kextunload|spctl\s+--master-disable)\b", "changing system security settings is blocked"),
    (r"\b(chmod|chown)\s+-R\b.*\s(/|~|\$HOME)/?(\s|$)", "recursive permission changes on / or your home folder are blocked"),
    (r"\bchmod\s+[0-7]*777\s+(/|~|\$HOME)/?(\s|$)", "opening up permissions on / or your home folder is blocked"),
    (r"with administrator privileges", "admin-privilege AppleScript is blocked"),
    (r"\blaunchctl\s+(bootout|unload|remove|disable)\b", "unloading system services is blocked"),
    (r"\bsecurity\s+(delete-\w+|dump-keychain|find-generic-password|find-internet-password|export)\b", "keychain access is blocked"),
    (r"\bkillall\s+(-\d+\s+)?(loginwindow|WindowServer|launchd|kernel_task)\b", "killing core system processes is blocked"),
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", "force-push is blocked — push normally"),
    (r"(\.ssh/|\bid_rsa\b|\bid_ed25519\b|\.aws/credentials|\.gnupg/|\.perry/|\.netrc\b|\.npmrc\b|(^|[\s/'\"])\.env\b)",
     "touching keys, credentials, .env files or Perry's own config is blocked"),
    (r"\bperry-(agent|server)\b", "Perry won't modify or restart itself from a voice command"),
]
_COMPILED = [(re.compile(p, re.I), why) for p, why in _BLOCKS]

MAX_LEN = 600


def check_command(command: str) -> str | None:
    """Return a human-readable reason if the command is refused, else None."""
    cmd = command.strip()
    if not cmd:
        return "the command is empty"
    if len(cmd) > MAX_LEN:
        return f"the command is longer than {MAX_LEN} characters"
    if "\n" in cmd or "\r" in cmd:
        return "multi-line commands are not allowed — one command per step"
    for rx, why in _COMPILED:
        if rx.search(cmd):
            return why
    return None
