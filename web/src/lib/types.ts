export type Risk = "read" | "low" | "execute" | "write";
export type StepStatus =
  | "planned" | "approved" | "running" | "succeeded" | "failed" | "skipped" | "cancelled" | "rejected";
export type TaskStatus =
  | "thinking" | "planning" | "awaiting_approval" | "executing" | "responding"
  | "completed" | "failed" | "cancelled" | "rejected";

export interface PlanStep {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  risk: Risk;
  requires_approval: boolean;
  status: StepStatus;
  output?: Record<string, any> | null;
  error?: string | null;
  started_at?: number | null;
  finished_at?: number | null;
  progress: string[];
}

export interface Plan {
  steps: PlanStep[];
  understanding: string;
  planner: string;
  reply_without_action?: string | null;
  project_id?: string | null;
}

export interface Task {
  id: string;
  desktop_id: string | null;
  desktop_name?: string | null;
  source: "voice" | "text";
  input_text: string;
  transcript?: { model?: string; language?: string; request_id?: string; latency_ms?: number } | null;
  style: string;
  status: TaskStatus;
  plan?: Plan | null;
  plan_digest?: string | null;
  response_text?: string | null;
  speech?: { status: "ready" | "unavailable"; url?: string; voice?: string; model?: string; reason?: string } | null;
  error?: string | null;
  timeline: { ts: number; event: string; [k: string]: unknown }[];
  created_at: number;
  updated_at: number;
}

export interface Desktop {
  id: string;
  name: string;
  platform: string;
  online: boolean;
  last_seen_at?: number | null;
  connected_at?: number | null;
  paired_at?: number | null;
  platform_supported?: boolean | null;
  platform_version?: string | null;
  projects: { id: string; name: string; scripts: string[]; has_git: boolean }[];
  tools: { id: string; title: string; risk: Risk }[];
  editor?: string | null;
}

export interface Health {
  gnani_configured: boolean;
  stt_model: string;
  tts_model: string;
  planner: string;
  approval_mode: string;
}

export const TERMINAL: TaskStatus[] = ["completed", "failed", "cancelled", "rejected"];
