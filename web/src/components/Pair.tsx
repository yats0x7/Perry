import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { api, deviceName, store } from "../lib/api";
import { Laptop, Spinner } from "./icons";

type Phase = "enter" | "claiming" | "confirm" | "done" | "rejected";

/** Pair this phone with a computer: the computer shows a QR/code, the phone claims it,
 *  both screens show the same 2-digit number, and the computer's owner confirms. */
export function Pair({ initialCode, onPaired, onCancel }: {
  initialCode?: string;
  onPaired: (token: string) => void;
  onCancel?: () => void;
}) {
  const [code, setCode] = useState(initialCode ?? "");
  const [phase, setPhase] = useState<Phase>("enter");
  const [err, setErr] = useState<string | null>(null);
  const [match, setMatch] = useState<{ number: string; desktop: string } | null>(null);
  const poll = useRef<number | null>(null);
  const existing = store.token;

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  const formatted = (v: string) => {
    const c = v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
    return c.length > 4 ? `${c.slice(0, 4)}-${c.slice(4)}` : c;
  };

  async function claim() {
    setErr(null);
    setPhase("claiming");
    try {
      const r = await api<{ claim_id: string; controller_token: string | null; match_code: string; desktop_name: string }>(
        "/api/pairing/claim", { method: "POST", body: JSON.stringify({ code, name: deviceName() }) }, existing,
      );
      const token = r.controller_token ?? existing!;
      setMatch({ number: r.match_code, desktop: r.desktop_name });
      setPhase("confirm");
      poll.current = window.setInterval(async () => {
        try {
          const st = await api<{ status: string }>(`/api/pairing/claims/${r.claim_id}`, {}, token);
          if (st.status === "confirmed") {
            clearInterval(poll.current!);
            setPhase("done");
            store.token = token;
            setTimeout(() => onPaired(token), 700);
          } else if (st.status === "rejected" || st.status === "expired") {
            clearInterval(poll.current!);
            setPhase("rejected");
            setErr(st.status === "expired" ? "The code expired before it was confirmed." : "Pairing was declined on the computer.");
          }
        } catch { /* keep polling through blips */ }
      }, 1200);
    } catch (e: any) {
      setPhase("enter");
      setErr(e.message);
    }
  }

  return (
    <div className="app-bg flex min-h-full flex-col items-center justify-center px-6 safe-top safe-bottom">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}
        className="w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center text-center">
          <div className="orb relative mb-6 h-16 w-16" data-state={phase === "confirm" || phase === "claiming" ? "busy" : "idle"} />
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Perry</h1>
          <p className="mt-1.5 text-[15px] text-dim">One assistant. Any phone. Any computer.</p>
        </div>

        {(phase === "enter" || phase === "claiming") && (
          <div className="space-y-5">
            <div className="rounded-2xl border border-line bg-panel p-4 text-[13.5px] leading-relaxed text-dim">
              <div className="mb-2 flex items-center gap-2 text-fg"><Laptop className="text-ember" /> On your computer, run</div>
              <code className="block break-all rounded-lg bg-ink/70 px-3 py-2 font-mono text-[12.5px] text-fg">
                perry-agent pair --server {window.location.origin}
              </code>
              <p className="mt-2">Scan the QR it shows with your phone camera, or type the code below.</p>
            </div>
            <label className="block">
              <span className="mb-2 block text-[12px] font-medium uppercase tracking-[0.08em] text-mute">Pairing code</span>
              <input
                value={code}
                onChange={(e) => setCode(formatted(e.target.value))}
                placeholder="XXXX-XXXX"
                inputMode="text"
                autoCapitalize="characters"
                autoComplete="one-time-code"
                className="w-full rounded-xl border border-line-strong bg-panel px-4 py-3.5 text-center font-mono text-[22px] tracking-[0.18em] outline-none placeholder:text-mute focus:border-ember/60"
              />
            </label>
            {err && <p className="text-[13.5px] text-bad">{err}</p>}
            <button
              disabled={code.replace("-", "").length !== 8 || phase === "claiming"}
              onClick={claim}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-ember py-3.5 text-[15px] font-semibold text-ink transition active:scale-[0.99] disabled:opacity-40"
            >
              {phase === "claiming" ? <Spinner /> : null} Pair this phone
            </button>
            {onCancel && (
              <button onClick={onCancel} className="w-full py-2 text-[14px] text-dim">Cancel</button>
            )}
          </div>
        )}

        {(phase === "confirm" || phase === "done") && match && (
          <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}
            className="rounded-2xl border border-line bg-panel p-6 text-center">
            <p className="text-[14px] text-dim">Confirm on <span className="text-fg">{match.desktop}</span> that it shows</p>
            <div className="my-5 font-mono text-[64px] font-semibold leading-none tracking-[0.06em] text-ember">{match.number}</div>
            {phase === "confirm" ? (
              <p className="flex items-center justify-center gap-2 text-[13.5px] text-dim"><Spinner /> Waiting for the computer…</p>
            ) : (
              <p className="text-[14px] text-ok">Paired. Opening Perry…</p>
            )}
          </motion.div>
        )}

        {phase === "rejected" && (
          <div className="space-y-4 text-center">
            <p className="text-[14px] text-bad">{err}</p>
            <button onClick={() => { setPhase("enter"); setCode(""); setErr(null); }}
              className="rounded-xl border border-line-strong px-5 py-2.5 text-[14px]">Try again</button>
          </div>
        )}
        <p className="mt-10 text-center text-[11.5px] leading-relaxed text-mute">
          Pairing needs a one-time code from your computer and a confirmation on it. Being on the same Wi-Fi is never enough.
        </p>
      </motion.div>
    </div>
  );
}
