// Pairs through the real PWA UI (as an iPhone) using a code from `perry-agent pair`.
//   node scripts/pair_ui_check.mjs http://localhost:8787 ABCD-EFGH out/ui
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, code, outDir = "out/ui"] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const port = 9700 + Math.floor(Math.random() * 200);
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", ["--headless=new",
  `--remote-debugging-port=${port}`, "--no-first-run", `--user-data-dir=${mkdtempSync(join(tmpdir(), "jvp-"))}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pending = new Map();
for (let i = 0; i < 40; i++) {
  try {
    const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page");
    ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; }); break;
  } catch { await sleep(250); }
}
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (e) => (await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true })).result?.value;
const shot = async (n) => { const { data } = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(join(outDir, n + ".png"), Buffer.from(data, "base64")); console.log("saved", n); };
const waitText = async (t, ms = 30000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await js(`document.body.innerText.includes(${JSON.stringify(t)})`)) return true; await sleep(300); } throw new Error("timeout: " + t); };

await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send("Emulation.setUserAgentOverride", { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1" });
await send("Page.navigate", { url: `${base}/pair?code=${code}` });
await sleep(1200);
await shot("p1-code-prefilled");
await js(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Pair this phone')).click()`);
await waitText("Confirm on");
const match = await js(`document.querySelector('.font-mono.text-\\\\[64px\\\\]')?.textContent`);
console.log("phone shows match number:", match);
await shot("p2-match-number");
await waitText("Paired", 30000);
await waitText("Kya karna hai", 15000).catch(() => {});
await sleep(1500);
await shot("p3-console");
console.log("token stored:", !!(await js(`localStorage.getItem('perry.controller.token')`)));
console.log("header:", await js(`document.querySelector('header').innerText.replace(/\\n/g,' | ')`));
ws.close(); chrome.kill(); process.exit(0);
