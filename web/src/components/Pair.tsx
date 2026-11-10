import { useEffect, useRef, useState } from "react";
import { api, deviceName, store } from "../lib/api";

type Phase = "enter" | "claiming" | "confirm" | "done" | "rejected";

/** Pair this phone with a computer: the computer shows a QR/code, the phone claims it,
 *  both screens show the same 2-digit number, and the computer's owner confirms. */
export function Pair({ initialCode, onPaired, onCancel }: {
  initialCode?: string;
  onPaired: (token: string) => void;
  onCancel?: () => void;
}) {
  const [code, setCode] = useState(initialCode ? clean(initialCode) : "");
  const [phase, setPhase] = useState<Phase>("enter");
  const [err, setErr] = useState<string | null>(null);
  const [match, setMatch] = useState<{ number: string; desktop: string } | null>(null);
  const poll = useRef<number | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const existing = store.token;

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  function clean(v: string) {
    return v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  }

  async function claim() {
    setErr(null);
    setPhase("claiming");
    try {
      const r = await api<{ claim_id: string; controller_token: string | null; match_code: string; desktop_name: string }>(
        "/api/pairing/claim",
        { method: "POST", body: JSON.stringify({ code: `${code.slice(0, 4)}-${code.slice(4)}`, name: deviceName() }) },
        existing,
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
            setTimeout(() => onPaired(token), 600);
          } else if (st.status === "rejected" || st.status === "expired") {
            clearInterval(poll.current!);
            setPhase("rejected");
            setErr(st.status === "expired" ? "The code expired before the Mac confirmed it." : "The Mac declined this phone.");
          }
        } catch { /* keep polling through blips */ }
      }, 1200);
    } catch (e: any) {
      setPhase("enter");
      setErr(e.message);
    }
  }

  return (
    <div className="studio flex min-h-full flex-col safe-top safe-bottom">
      <div className="flex flex-1 flex-col px-5 pt-10">
        <h1 className="text-[44px] font-extrabold leading-none tracking-[0.14em]">PERRY</h1>
        <p className="mt-2 text-[15px] text-mist">One assistant. Any phone. Any computer.</p>

        {(phase === "enter" || phase === "claiming") && (
          <div className="cut-in mt-10">
            <p className="text-[15px] leading-snug">On the Mac, start pairing:</p>
            <pre className="mt-2 whitespace-pre-wrap break-all bg-studio-deep px-3 py-3 font-mono text-[14px] leading-snug">
              perry-agent pair --server {window.location.origin}
            </pre>
            <p className="mt-2 text-[15px] text-mist">Scan the QR it shows with this phone’s camera, or enter its code here.</p>

            <label className="mt-7 block" onClick={() => input.current?.focus()}>
              <span className="text-[15px] font-semibold">Pairing code</span>
              <span className="relative mt-2 grid grid-cols-8 gap-1.5">
                {Array.from({ length: 8 }).map((_, i) => (
                  <span
                    key={i}
                    className={`grid h-12 place-items-center border-b-2 bg-studio-deep text-[19px] font-bold ${
                      i === code.length && phase === "enter" ? "border-ivory bg-studio-lift" : code[i] ? "border-ivory" : "border-rule-strong"
                    } ${i === 4 ? "ml-1.5" : ""}`}
                  >
                    {code[i] ?? ""}
                  </span>
                ))}
                <input
                  ref={input}
                  value={code}
                  onChange={(e) => setCode(clean(e.target.value))}
                  onKeyDown={(e) => { if (e.key === "Enter" && code.length === 8) claim(); }}
                  inputMode="text"
                  autoCapitalize="characters"
                  autoComplete="one-time-code"
                  aria-label="Pairing code, 8 characters"
                  className="absolute inset-0 opacity-0"
                />
              </span>
            </label>
            {err && <p className="mt-3 text-[15px] text-fault">{err}</p>}
          </div>
        )}

        {(phase === "confirm" || phase === "done") && match && (
          <div className="cut-in -mx-5 mt-12 border-t-[3px] border-saffron bg-ivory px-5 pb-6 pt-4 text-ink">
            <p className="text-[15px]">On <b className="font-extrabold">{match.desktop}</b>, confirm it shows</p>
            <p className="mt-3 text-[96px] font-extrabold leading-none tracking-[0.04em]">{match.number}</p>
            <p className="mt-4 flex items-center gap-2 text-[15px]">
              <span className={`h-2 w-2 ${phase === "done" ? "bg-[#1f8f5f]" : "tally-blink bg-saffron"}`} aria-hidden />
              {phase === "done" ? "Paired. Opening Perry." : "Waiting for the Mac to confirm…"}
            </p>
          </div>
        )}

        {phase === "rejected" && (
          <div className="cut-in mt-10">
            <p className="text-[15px] text-fault">{err}</p>
            <button
              onClick={() => { setPhase("enter"); setCode(""); setErr(null); }}
              className="mt-4 border-2 border-ivory px-5 py-3 text-[15px] font-bold"
            >
              Enter a new code
            </button>
          </div>
        )}

        <p className="mt-auto pb-4 pt-10 text-[15px] leading-snug text-haze">
          Pairing needs a one-time code from your Mac and a confirmation on it. Being on the same Wi-Fi is never enough.
        </p>
      </div>

      {(phase === "enter" || phase === "claiming") && (
        <div className="grid gap-2.5 bg-studio-deep px-5 pb-2 pt-4">
          <button
            disabled={code.length !== 8 || phase === "claiming"}
            onClick={claim}
            className="bg-ivory py-3.5 text-[19px] font-bold text-ink disabled:bg-studio-lift disabled:text-haze"
          >
            {phase === "claiming" ? "Pairing…" : "Pair this phone"}
          </button>
          {onCancel && <button onClick={onCancel} className="py-2 text-[15px] text-mist">Cancel</button>}
        </div>
      )}
    </div>
  );
}
