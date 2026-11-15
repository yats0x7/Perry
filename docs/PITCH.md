# Perry: talk to your Mac from any phone

Yatharth Katta · Great Indian AI Internship Challenge · github.com/yats0x7/Perry

## The problem

A lot of us in India think and talk in Hinglish, but our computers only take clicks and typed English.
And the moment you walk away from the desk the computer is out of reach. You can't start the dev server
from the couch, stop the Mac from sleeping halfway through a download, or pause the music from the next
room. Remote desktop apps need the same ecosystem or a tiny copy of the screen on your phone, and
voice assistants either don't understand mixed Hindi and English or won't touch real work like git and terminals.

## What Perry does

You open Perry in your phone's browser (Android or iPhone, nothing to install from a store), tap and say
something like "Perry, mera Dineo project kholo, git status check karo aur dev server start karo". Perry
writes down what it heard, shows you the plan step by step, waits for one tap on Approve for anything
that changes your machine, runs it on your Mac and tells you out loud what happened, in Hinglish.

It covers projects and dev servers (open, git status, start, stop, read the errors), the browser in your own
Chrome, Brave or Safari (search YouTube or Instagram, "play the second video", count and close tabs), music
(Spotify and Apple Music), and Mac settings like volume, brightness, dark mode, battery and keep awake.

## How it works

Phone PWA → Perry server → a small agent on the Mac. The Mac agent only makes outbound connections, so
there's no port forwarding, and you pair once with a QR code and a 2-digit number shown on both screens.
Speech goes through **Gnani Prisma v2.5** (it handles code-switched Hinglish and Devanagari Hindi) and replies
are spoken back with **Gnani Timbre v2.5** in the Poorvi Hinglish voice. A rule planner tuned on real Prisma
transcripts handles common commands instantly and even matches project names by sound when Prisma mishears
them. Anything the rules can't parse goes to an LLM (gpt-5.4-mini) as a fallback.

## Why it's safe

The model never decides what's allowed. Every plan passes a fixed policy: risky steps need approval, the
approved plan is locked with a digest so it can't be swapped after you tap, output from commands can't
inject new steps, and a shell guard refuses things like `rm -rf`, `sudo`, `curl | sh` and disk wipes outright.
There's a pause switch in the Mac menu bar, and every action is written to an audit log.

## Where it is now

Working end to end on macOS with live Gnani speech both ways: 158 automated tests, an 18/18 score on the
planner benchmark, a menu-bar app, and a small desktop pet (a TV set) that acts out what Perry is doing.
Next up are Windows and Linux agents, playing songs by name through the Spotify API, and filling forms in the browser.

Setup steps, architecture and security notes are in the README and docs folder.
