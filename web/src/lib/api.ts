// Thin client for the Perry server. The controller token lives only in this browser
// (localStorage) and is sent as a Bearer header / first WebSocket frame — never in URLs.

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "perry.controller.token";

// One-time carry-over from the app's previous name so existing phones stay paired.
try {
  for (const [k, v] of Object.entries(localStorage)) {
    if (k.startsWith("jarvis.")) {
      const nk = "perry." + k.slice("jarvis.".length);
      if (localStorage.getItem(nk) === null) localStorage.setItem(nk, v);
      localStorage.removeItem(k);
    }
  }
} catch { /* storage unavailable */ }

export const store = {
  get token(): string | null {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set token(v: string | null) {
    try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
  },
  pref(key: string, fallback: string): string {
    try { return localStorage.getItem(`perry.pref.${key}`) ?? fallback; } catch { return fallback; }
  },
  setPref(key: string, v: string) {
    try { localStorage.setItem(`perry.pref.${key}`, v); } catch { /* ignore */ }
  },
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}

export async function api<T = any>(path: string, init: RequestInit = {}, token = store.token): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { ...init, headers });
  } catch {
    throw new ApiError("Can't reach the Perry server. Check your connection.", 0);
  }
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { detail: text }; }
  if (!res.ok) {
    const msg = body?.error ?? (typeof body?.detail === "string" ? body.detail : null) ?? `Request failed (${res.status})`;
    throw new ApiError(msg, res.status, body?.code);
  }
  return body as T;
}

export const absoluteUrl = (path: string) => (path.startsWith("http") ? path : API_BASE + path);

export function wsUrl(path: string): string {
  const base = API_BASE || window.location.origin;
  return base.replace(/^http/, "ws") + path;
}

export function deviceName(): string {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android"
    : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Device";
  const br = /EdgA?\//.test(ua) ? "Edge" : /CriOS|Chrome\//.test(ua) ? "Chrome" : /FxiOS|Firefox\//.test(ua) ? "Firefox"
    : /Safari\//.test(ua) ? "Safari" : "Browser";
  return `${os} · ${br}`;
}
