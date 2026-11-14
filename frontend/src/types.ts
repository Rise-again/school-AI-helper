/** 与后端 schemas 对齐的类型定义（P6-01 验收：类型与接口契约一致）。 */

export type Role = "student" | "admin";

export interface Envelope<T> {
  code: number;
  message: string;
  data: T;
  trace_id: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserProfile {
  id: number;
  username: string;
  role: Role;
  student_no?: string | null;
  name?: string | null;
}

export interface Conversation {
  id: number;
  title: string;
  role_mode: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  tokens?: number | null;
  latency_ms?: number | null;
  created_at: string;
  citations?: Citation[];
}

export interface Citation {
  kb_file_id: number | null;
  chunk_id: string | null;
  filename?: string | null;
  page_no: number | null;
  url: string | null;
  snippet: string;
  score: number | null;
}

export interface KbFile {
  id: number;
  filename: string;
  file_type: string;
  size_bytes: number;
  parse_channel: string | null;
  parse_status: "pending" | "parsing" | "success" | "failed";
  chunk_count: number;
  version: number;
  source_dept: string | null;
  source_url: string | null;
  effective_from: string | null;
  effective_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface KbChunk {
  id: number;
  ordinal: number;
  content: string;
  token_count: number;
  vector_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

/** SSE 事件负载 */
export interface StreamMeta {
  intent: string;
  evidence_count: number;
  degraded: string;
  prompt_version: string;
}

export interface StreamDone {
  latency_ms: number;
  chars: number;
  message_id?: number;
}

export type StreamEvent =
  | { type: "meta"; data: StreamMeta }
  | { type: "delta"; data: { text: string } }
  | { type: "replace"; data: { text: string } }
  | { type: "citation"; data: { items: Citation[] } }
  | { type: "done"; data: StreamDone }
  | { type: "error"; data: { message: string } };

// ---------- 教务（P5 后端接入后生效，前端先按契约实现） ----------
export interface EduStatus {
  bound: boolean;
  student_no?: string | null;
  updated_at?: string | null;
}

export interface ScheduleSlot {
  weekday: number; // 1=周一 … 7=周日
  sections: number[]; // 节次，如 [1,2]
  course: string;
  teacher?: string;
  location?: string;
  weeks?: string;
}

export interface GradeItem {
  course: string;
  credit: number;
  score: string;
  gpa?: number;
  term: string;
}

export interface GradeResult {
  terms: string[];
  items: GradeItem[];
}

export interface CreditCategory {
  name: string;
  required: number;
  earned: number;
}

export interface CreditSummary {
  required: number;
  earned: number;
  gpa: number;
  categories: CreditCategory[];
}
