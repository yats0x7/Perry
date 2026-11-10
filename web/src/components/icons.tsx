import type { SVGProps } from "react";

const base = (p: SVGProps<SVGSVGElement>) => ({
  width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, ...p,
});

export const Mic = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
);
export const Send = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M5 12h13M13 6l6 6-6 6" /></svg>
);
export const Stop = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none" /></svg>
);
export const Check = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="m5 12.5 4.2 4.2L19 7" /></svg>
);
export const Cross = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
export const Minus = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M7 12h10" /></svg>
);
export const Chevron = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="m9 6 6 6-6 6" /></svg>
);
export const Laptop = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="4" y="5" width="16" height="11" rx="1.5" /><path d="M2 19h20" /></svg>
);
export const Play = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none" /></svg>
);
export const Pause = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M8 5v14M16 5v14" strokeWidth={2.4} /></svg>
);
export const Shield = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M12 3 5 6v5c0 4.5 3 8.2 7 10 4-1.8 7-5.5 7-10V6z" /><path d="m9 12 2 2 4-4" /></svg>
);
export const Wave = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2" /></svg>
);
export const Menu = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M5 9h14M5 15h14" /></svg>
);
export const Spinner = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} className={"spin " + (p.className ?? "")}><path d="M12 3a9 9 0 1 0 9 9" /></svg>
);
export const Speaker = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 9h3l5-4v14l-5-4H4z" /><path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12" /></svg>
);
export const SpeakerOff = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 9h3l5-4v14l-5-4H4z" /><path d="m16 10 5 5M21 10l-5 5" /></svg>
);
