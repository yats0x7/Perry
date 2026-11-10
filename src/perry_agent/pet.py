"""Perry's desktop pet: a small 1980s TV set that floats above your windows and acts out
what Perry is doing (listening, thinking, waiting for approval, running a command, searching,
playing music, speaking, done, failed, offline, keeping the Mac awake).

A borderless, transparent, always-on-top NSWindow hosts a WKWebView; the character is SVG and
the motion is CSS, so there are no image assets. Drag it anywhere (the position is remembered),
click it for the current status and Perry's last reply, double-click to pause or resume Perry.
"""

from __future__ import annotations

import json
import logging
import time

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSScreen,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from .config import perry_home

W, H = 220, 210
log = logging.getLogger("perry.pet")


# ---- state ---------------------------------------------------------------------------------

def _kind(tool: str | None) -> str:
    t = tool or ""
    if t in ("browser.search", "files.find", "media.search"):
        return "search"
    if t.startswith("media."):
        return "music"
    if t.startswith(("browser.", "url.", "app.")):
        return "browser"
    if t.startswith("system."):
        return "settings"
    if t.startswith("git."):
        return "git"
    if t.startswith(("files.", "notes.", "project.")):
        return "files"
    return "command"


def derive_state(link) -> dict:
    """Map the agent's live status to one pet state."""
    now = time.time()
    if link is None:
        return {"state": "offline", "text": "Not paired yet"}
    if link.paused:
        return {"state": "paused", "text": "Paused · double-click to resume"}
    st = link.status
    if st.get("state") != "online":
        return {"state": "offline", "text": "Mac is offline · reconnecting"}
    t = st.get("task") or {}
    reply = t.get("reply") or ""
    if st.get("running"):
        tool = st["running"]
        return {"state": "working", "kind": _kind(tool), "tool": tool, "text": f"Running {tool}", "reply": reply}
    if t:
        age, s = now - t.get("ts", 0), t.get("status")
        if s == "listening" and age < 20:
            return {"state": "listening", "text": "Hearing you"}
        if s in ("thinking", "planning", "responding") and age < 60:
            return {"state": "thinking", "text": "Planning"}
        if s == "awaiting_approval" and age < 300:
            return {"state": "needs_you", "text": "Waiting for your approval on the phone"}
        if s == "executing" and age < 300:
            return {"state": "working", "kind": _kind(t.get("tool")), "tool": t.get("tool"), "text": "On air"}
        talk = min(14.0, 2.5 + len(reply) / 14)
        if s == "speaking" and age < talk:
            return {"state": "speaking", "text": "Speaking", "reply": reply}
        if s == "speaking" and age < talk + 3:
            return {"state": "done", "text": "Done", "reply": reply}
        if s == "completed" and age < 5:
            return {"state": "done", "text": "Done", "reply": reply}
        if s == "failed" and age < 10:
            return {"state": "failed", "text": "Something failed · click to read", "reply": reply}
    awake = any(p.running for p in link.procs.find("system", "keep-awake"))
    return {"state": "awake" if awake else "idle", "text": f"On air as {st.get('name') or 'this Mac'}", "reply": reply}


# ---- window ------------------------------------------------------------------------------------

class _Bridge(NSObject):
    def initWithPet_(self, pet):
        self = objc.super(_Bridge, self).init()
        if self is None:
            return None
        self.pet = pet
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            self.pet._on_message(dict(message.body()))
        except Exception:  # noqa: BLE001
            pass


class PetWindow:
    def __init__(self, on_toggle_pause) -> None:
        self.on_toggle_pause = on_toggle_pause
        self._pos_file = perry_home() / "pet-position.json"
        x, y = self._initial_origin()
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setHasShadow_(False)
        self.win.setLevel_(NSFloatingWindowLevel)
        self.win.setCollectionBehavior_((1 << 0) | (1 << 4))  # all Spaces, stationary in Exposé
        self.win.setReleasedWhenClosed_(False)

        cfg = WKWebViewConfiguration.alloc().init()
        ucc = WKUserContentController.alloc().init()
        self.bridge = _Bridge.alloc().initWithPet_(self)
        ucc.addScriptMessageHandler_name_(self.bridge, "perry")
        cfg.setUserContentController_(ucc)
        self.web = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, W, H), cfg)
        self.web.setValue_forKey_(False, "drawsBackground")
        self.web.loadHTMLString_baseURL_(PET_HTML, None)
        self.win.setContentView_(self.web)
        self._last: str | None = None
        self._ready_at = time.time() + 0.8

    def _initial_origin(self) -> tuple[float, float]:
        try:
            p = json.loads(self._pos_file.read_text())
            return float(p["x"]), float(p["y"])
        except Exception:  # noqa: BLE001
            f = NSScreen.mainScreen().visibleFrame()
            return f.origin.x + f.size.width - W - 24, f.origin.y + 16

    def show(self) -> None:
        self.win.orderFrontRegardless()

    def hide(self) -> None:
        self.win.orderOut_(None)

    @property
    def visible(self) -> bool:
        return bool(self.win.isVisible())

    def update(self, state: dict) -> None:
        payload = json.dumps(state)
        if payload == self._last or time.time() < self._ready_at:
            return
        prev = json.loads(self._last)["state"] if self._last else None
        if prev != state["state"]:
            log.info("pet: %s%s", state["state"], f" ({state['kind']})" if state.get("kind") else "")
        self._last = payload
        self.web.evaluateJavaScript_completionHandler_(f"window.setState && setState({payload})", None)

    def _on_message(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "drag":
            f = self.win.frame()
            self.win.setFrameOrigin_((f.origin.x + float(msg.get("dx", 0)), f.origin.y - float(msg.get("dy", 0))))
        elif kind == "dragend":
            o = self.win.frame().origin
            self._pos_file.write_text(json.dumps({"x": o.x, "y": o.y}))
        elif kind == "pause":
            self.on_toggle_pause()
            self._last = None  # force a redraw with the new state


PET_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden;user-select:none;-webkit-user-select:none;cursor:grab;
  font-family:-apple-system,BlinkMacSystemFont,sans-serif}
#stage{position:absolute;left:0;right:0;bottom:0;height:150px;display:grid;place-items:end center}
#bubble{position:absolute;left:8px;right:8px;top:4px;background:#f2ebdd;color:#0d2149;font-size:12px;line-height:1.3;
  padding:7px 9px;border-top:3px solid #1f6f78;display:none;box-shadow:0 4px 14px rgba(0,0,0,.25)}
#bubble b{display:block;font-size:10px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:2px}
svg{overflow:visible;filter:drop-shadow(0 3px 4px rgba(0,0,0,.28))}
svg *{transform-box:fill-box}
.bob{animation:bob 3.2s ease-in-out infinite}@keyframes bob{50%{transform:translateY(-2px)}}
.sway{transform-origin:50% 100%;animation:sway 4s ease-in-out infinite}@keyframes sway{50%{transform:rotate(5deg)}}
.blink{transform-origin:center;animation:blink 4s infinite}@keyframes blink{0%,94%,100%{transform:scaleY(1)}96%{transform:scaleY(.1)}}
.perk{transform-origin:50% 100%;animation:perk .2s steps(2) infinite}@keyframes perk{50%{transform:translateY(-2px) rotate(-3deg)}}
.lvl rect,.wave rect{transform-origin:bottom;animation:lvl .45s steps(3) infinite}
.wave rect{transform-origin:center;animation-duration:.33s}
.lvl rect:nth-child(2),.wave rect:nth-child(odd){animation-delay:.12s}.lvl rect:nth-child(3){animation-delay:.24s}
@keyframes lvl{0%{transform:scaleY(.3)}50%{transform:scaleY(1)}100%{transform:scaleY(.5)}}
.static{animation:static .25s steps(4) infinite}@keyframes static{25%{transform:translate(-3px,2px)}50%{transform:translate(2px,-2px)}75%{transform:translate(-1px,3px)}}
.tblink{animation:tb 1s steps(1) infinite}@keyframes tb{60%{opacity:.25}}
.sweep{animation:sweep 1.4s steps(6) infinite}@keyframes sweep{from{transform:translateX(-40px)}to{transform:translateX(40px)}}
.hop{animation:hop 1.6s cubic-bezier(.2,.8,.2,1) infinite}@keyframes hop{0%,40%,100%{transform:translateY(0)}20%{transform:translateY(-10px)}}
.wipe{animation:wipe 2s steps(5) infinite}@keyframes wipe{0%{clip-path:inset(0 100% 0 0)}30%,100%{clip-path:inset(0 0 0 0)}}
.droop{transform-origin:50% 100%;transform:rotate(14deg)}
.dim{opacity:.72}
.jit{animation:jit .5s steps(2) infinite}@keyframes jit{50%{transform:translateY(-2px)}}
.steam path{animation:steam 2s ease-out infinite;opacity:0}.steam path:nth-child(2){animation-delay:1s}
@keyframes steam{0%{opacity:0;transform:translateY(4px)}40%{opacity:.9}100%{opacity:0;transform:translateY(-8px)}}
.drop{animation:drop 1.4s ease-in infinite}@keyframes drop{100%{transform:translateY(10px);opacity:0}}
.note{animation:note 1.8s ease-out infinite;opacity:0}.note.n2{animation-delay:.9s}@keyframes note{0%{opacity:0;transform:translateY(4px)}30%{opacity:1}100%{opacity:0;transform:translate(6px,-14px)}}
.mag{animation:mag 1.6s ease-in-out infinite}@keyframes mag{50%{transform:translate(-14px,4px)}}
.zz text{animation:note 2.4s ease-out infinite;opacity:0}.zz text:nth-child(2){animation-delay:1.2s}
@media (prefers-reduced-motion: reduce){*{animation:none!important}}
</style></head><body>
<div id="bubble"></div><div id="stage"></div>
<script>
const D="#0d2149",I="#f2ebdd",K="#6f86b8",SAF="#f28c28",RED="#e0334a",OK="#3fd39a",TEAL="#1f6f78";
const ant=(cls='sway')=>`<g class="${cls}"><line x1="50" y1="30" x2="32" y2="8" stroke="${K}" stroke-width="2.5" stroke-linecap="round"/><line x1="50" y1="30" x2="70" y2="6" stroke="${K}" stroke-width="2.5" stroke-linecap="round"/><circle cx="32" cy="8" r="3.2" fill="${K}"/><circle cx="70" cy="6" r="3.2" fill="${K}"/></g>`;
const tv=(screen,tally='#8a9cc2',antenna=ant(),extra='')=>`
<svg width="132" height="140" viewBox="-14 -2 128 112">${antenna}
 <rect x="10" y="28" width="80" height="62" rx="9" fill="${I}" stroke="${D}" stroke-width="2.5"/>
 <clipPath id="sc"><rect x="17" y="35" width="56" height="48" rx="6"/></clipPath>
 <rect x="17" y="35" width="56" height="48" rx="6" fill="${D}"/>
 <g clip-path="url(#sc)">${screen}</g>
 <rect x="78" y="38" width="7" height="7" fill="${tally}" class="${[SAF,RED].includes(tally)?'tblink':''}"/>
 <circle cx="81.5" cy="56" r="3" fill="none" stroke="${D}" stroke-width="2"/><circle cx="81.5" cy="68" r="3" fill="none" stroke="${D}" stroke-width="2"/>
 <rect x="22" y="90" width="7" height="10" rx="2" fill="${K}"/><rect x="71" y="90" width="7" height="10" rx="2" fill="${K}"/>${extra}</svg>`;
const eyes=(dy=0,cls='blink')=>`<g class="${cls}"><rect x="33" y="${54+dy}" width="6" height="9" rx="1.5" fill="${I}"/><rect x="51" y="${54+dy}" width="6" height="9" rx="1.5" fill="${I}"/></g>`;
const focus=`<rect x="33" y="52" width="6" height="5" rx="1" fill="${I}"/><rect x="51" y="52" width="6" height="5" rx="1" fill="${I}"/>`;
const smile=`<path d="M38 70 Q45 75 52 70" stroke="${I}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`;
const bar=`<rect x="17" y="70" width="56" height="9" fill="${TEAL}"/><rect class="sweep" x="35" y="70" width="18" height="9" fill="${I}" opacity=".6"/>`;
const label=t=>`<g transform="translate(30 -2)"><rect width="74" height="16" rx="3" fill="${D}" stroke="${SAF}" stroke-width="1.4"/><text x="37" y="11.5" text-anchor="middle" font-size="9" font-family="ui-monospace,Menlo,monospace" fill="${SAF}">${t}</text></g>`;
const PROPS={
 command:()=>'',
 search:()=>`<g transform="translate(74 70)"><g class="mag"><circle cx="10" cy="10" r="9" fill="rgba(242,235,221,.35)" stroke="${D}" stroke-width="3"/><line x1="17" y1="17" x2="26" y2="26" stroke="${D}" stroke-width="4" stroke-linecap="round"/></g></g>`,
 music:()=>`<text class="note" x="92" y="40" font-size="18" fill="${K}">♪</text><text class="note n2" x="100" y="30" font-size="14" fill="${K}">♫</text>`,
 browser:()=>'',settings:()=>'',git:()=>'',files:()=>'',
};
const SHORT={command:'running',search:'searching',music:'music',browser:'browser',settings:'settings',git:'git',files:'files'};
const VIEWS={
 idle:()=>[`bob`,tv(eyes()+smile)],
 listening:()=>[``,tv(eyes(-4)+`<g class="lvl">${[30,38,46,54].map(x=>`<rect x="${x}" y="70" width="5" height="8" fill="${RED}"/>`).join('')}</g>`,RED,ant('perk'))],
 thinking:()=>[``,tv(`<g class="static" opacity=".55">${Array.from({length:60},(_,i)=>`<rect x="${17+(i*37)%56}" y="${35+(i*23)%48}" width="3" height="2" fill="#a9b7d3"/>`).join('')}</g>`+eyes(-6,''))],
 needs_you:()=>[`jit`,tv(eyes(-2,'')+smile,SAF,ant(),`<g transform="translate(64 66) rotate(8)"><rect width="30" height="22" fill="${I}" stroke="${D}" stroke-width="2"/><rect width="30" height="3" fill="${SAF}"/><text x="15" y="16" text-anchor="middle" font-size="10" font-weight="800" fill="${D}" font-family="sans-serif">OK?</text></g>`)],
 working:(s)=>[``,tv(bar+focus,SAF,ant(),label(SHORT[s.kind]||'running')+(PROPS[s.kind]||PROPS.command)())],
 speaking:()=>[`bob`,tv(eyes()+`<g class="wave">${[[34,68,7],[39,66,11],[44,68,7],[49,66,11],[54,68,7]].map(([x,y,h])=>`<rect x="${x}" y="${y}" width="3" height="${h}" fill="${I}"/>`).join('')}</g>`)],
 done:()=>[`hop`,tv(`<g class="wipe"><rect x="17" y="66" width="56" height="13" fill="${TEAL}"/><path d="M27 72 l4 4 l8 -8" stroke="${I}" stroke-width="2.5" fill="none" stroke-linecap="round"/></g><path d="M33 56 q3 -4 6 0 M51 56 q3 -4 6 0" stroke="${I}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,OK)],
 failed:()=>[``,tv(['#f2ebdd','#f2c94c','#3fb6c4','#3fd39a','#c86fd1','#e0334a','#1f4fb0'].map((c,i)=>`<rect x="${17+i*8}" y="35" width="8" height="48" fill="${c}"/>`).join(''),'#8a9cc2',ant(),`<path class="drop" d="M90 30 q3 5 0 7 q-3 -2 0 -7z" fill="#3fb6c4"/>`)],
 offline:()=>[`dim`,tv(`<rect x="17" y="35" width="56" height="48" fill="${I}"/><text x="45" y="57" text-anchor="middle" font-size="7" font-weight="800" fill="${D}">रुकावट के लिए</text><text x="45" y="67" text-anchor="middle" font-size="7" font-weight="800" fill="${D}">खेद है</text>`,'#8a9cc2',ant('droop'))],
 paused:()=>[`dim`,tv(`<rect x="34" y="50" width="7" height="20" fill="${I}"/><rect x="49" y="50" width="7" height="20" fill="${I}"/>`,'#8a9cc2',ant('droop'),`<g class="zz"><text x="90" y="24" font-size="13" font-weight="800" fill="${K}">z</text><text x="99" y="14" font-size="10" font-weight="800" fill="${K}">z</text></g>`)],
 awake:()=>[`bob`,tv(eyes()+smile,OK,ant(),`<g transform="translate(-12 70)"><g class="steam"><path d="M8 -2 q-2 -4 0 -7" stroke="${K}" stroke-width="1.6" fill="none"/><path d="M13 -2 q2 -4 0 -7" stroke="${K}" stroke-width="1.6" fill="none"/></g><path d="M3 0 h16 l-2 13 h-12z" fill="${I}" stroke="${D}" stroke-width="2"/><path d="M19 3 q5 0 4 5 q-1 3 -5 2" stroke="${D}" stroke-width="2" fill="none"/><rect x="5" y="2" width="12" height="3" fill="#c8945a"/></g>`)],
};
let cur={state:'offline',text:'Starting…'};
const stage=document.getElementById('stage'), bubble=document.getElementById('bubble');
let autoOpened=false;
function render(){const [cls,svg]=(VIEWS[cur.state]||VIEWS.idle)(cur);stage.innerHTML=`<div class="${cls}">${svg}</div>`;
  const wants=cur.state==='failed'||cur.state==='needs_you';
  if(wants&&bubble.style.display!=='block'){bubble.style.display='block';autoOpened=true;}
  else if(!wants&&autoOpened){bubble.style.display='none';autoOpened=false;}
  if(bubble.style.display==='block')fillBubble();}
function fillBubble(){bubble.innerHTML=`<b>Perry</b>${esc(cur.text||'')}${cur.reply?`<div style="margin-top:4px">${esc(cur.reply)}</div>`:''}`;}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
window.setState=s=>{const prev=cur.state;cur=s;if(prev!==s.state||s.state==='working')render();else if(bubble.style.display==='block')fillBubble();};
render();
const post=m=>{try{window.webkit.messageHandlers.perry.postMessage(m)}catch(e){}};
let drag=null,moved=false;
document.addEventListener('mousedown',e=>{drag={x:e.screenX,y:e.screenY};moved=false;document.body.style.cursor='grabbing'});
document.addEventListener('mousemove',e=>{if(!drag)return;const dx=e.screenX-drag.x,dy=e.screenY-drag.y;
  if(Math.abs(dx)+Math.abs(dy)>2)moved=true;if(moved){post({t:'drag',dx,dy});drag={x:e.screenX,y:e.screenY};}});
document.addEventListener('mouseup',()=>{if(drag&&moved)post({t:'dragend'});drag=null;document.body.style.cursor='grab'});
document.addEventListener('click',()=>{if(moved)return;autoOpened=false;bubble.style.display=bubble.style.display==='block'?'none':'block';fillBubble();});
document.addEventListener('dblclick',()=>post({t:'pause'}));
</script></body></html>"""
