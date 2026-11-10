// Drives headless Chrome (CDP) through the PWA at iPhone size and saves screenshots.
//   node scripts/ui_check.mjs http://localhost:8787 <controller-token> "<command>" out/ui
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base = "http://localhost:8787", token = "", command = "", outDir = "out/ui"] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = 9333 + Math.floor(Math.random() * 300);
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, "--no-first-run",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "jv-"))}`, "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params }));
});
for (let i = 0; i < 40; i++) {
  try {
    const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    const page = targets.find((t) => t.type === "page");
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
    break;
  } catch { await sleep(250); }
}
const consoleLines = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); }
  if (m.method === "Runtime.consoleAPICalled") consoleLines.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
  if (m.method === "Runtime.exceptionThrown") consoleLines.push("EXCEPTION " + m.params.exceptionDetails.exception?.description);
};
await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send("Emulation.setUserAgentOverride", { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1" });
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result.value;
const shot = async (name) => {
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(outDir, name + ".png"), Buffer.from(data, "base64"));
  console.log("saved", join(outDir, name + ".png"));
};
const waitFor = async (expr, ms = 30000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await evalJs(expr)) return true; await sleep(250); }
  throw new Error("timeout waiting for " + expr);
};
const click = (text) => evalJs(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim().includes(${JSON.stringify(text)})); if (b) b.click(); return !!b; })()`);

await send("Page.navigate", { url: base + "/" });
await sleep(1200);
await shot("1-pair");
if (token) {
  await evalJs(`localStorage.setItem('perry.controller.token', ${JSON.stringify(token)}); location.reload(); true`);
  await sleep(1800);
  await shot("2-home");
}
if (command) {
  await evalJs(`(() => { const i = document.querySelector('input[placeholder="Type a command…"]');
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(i, ${JSON.stringify(command)});
    i.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
  await sleep(200);
  await evalJs(`document.querySelector('button[aria-label="Send"]').click(); true`);
  try {
    await waitFor(`[...document.querySelectorAll('button')].some(b => b.textContent.includes('Approve & run')) || document.body.innerText.includes('Ho gaya')`, 20000);
  } catch (e) { console.log(String(e)); }
  await sleep(400);
  await shot("3-approval");
  if (await click("Approve & run")) {
    await waitFor(`!document.body.innerText.includes('Running on')`, 60000).catch(() => {});
    await sleep(1500);
    await shot("4-done");
    await evalJs(`(() => { const rows = [...document.querySelectorAll('li button')]; rows[rows.length-1]?.click(); return true })()`);
    await sleep(600);
    await shot("5-expanded");
  }
}
console.log("console:", consoleLines.slice(-10));
ws.close(); chrome.kill();
process.exit(0);
