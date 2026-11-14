import http from "./http";
import type {
  Conversation,
  CreditSummary,
  EduStatus,
  Envelope,
  GradeResult,
  KbChunk,
  KbFile,
  Message,
  Page,
  ScheduleSlot,
  TokenPair,
  UserProfile,
} from "@/types";

// ---------- 鉴权 ----------
export async function login(username: string, password: string) {
  const { data } = await http.post<Envelope<TokenPair>>("/auth/login", { username, password });
  return data.data;
}

export async function me() {
  const { data } = await http.get<Envelope<UserProfile>>("/me");
  return data.data;
}

// ---------- 会话 ----------
export async function listConversations(page = 1, size = 50) {
  const { data } = await http.get<Envelope<Page<Conversation>>>("/conversations", {
    params: { page, size },
  });
  return data.data;
}

export async function createConversation(title?: string) {
  const { data } = await http.post<Envelope<Conversation>>("/conversations", { title });
  return data.data;
}

export async function renameConversation(id: number, title: string) {
  const { data } = await http.patch<Envelope<Conversation>>(`/conversations/${id}`, { title });
  return data.data;
}

export async function deleteConversation(id: number) {
  await http.delete(`/conversations/${id}`);
}

export async function listMessages(id: number, page = 1, size = 200) {
  const { data } = await http.get<Envelope<Page<Message>>>(`/conversations/${id}/messages`, {
    params: { page, size },
  });
  return data.data;
}

// ---------- 知识库 ----------
export async function listKbFiles(page = 1, size = 20, status?: string) {
  const { data } = await http.get<Envelope<Page<KbFile>>>("/kb/files", {
    params: { page, size, status },
  });
  return data.data;
}

export async function uploadKbFile(form: FormData) {
  const { data } = await http.post<Envelope<KbFile>>("/kb/files", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data.data;
}

export async function listKbChunks(fileId: number, page = 1, size = 20) {
  const { data } = await http.get<Envelope<Page<KbChunk>>>(`/kb/files/${fileId}/chunks`, {
    params: { page, size },
  });
  return data.data;
}

export async function reindexKbFile(fileId: number) {
  const { data } = await http.post<Envelope<KbFile>>(`/kb/files/${fileId}/reindex`);
  return data.data;
}

export async function deleteKbFile(fileId: number) {
  await http.delete(`/kb/files/${fileId}`);
}


/** 取知识库原文件（带鉴权），调用方负责转成 objectURL 打开。 */
export async function downloadKbFile(fileId: number) {
  const resp = await http.get(`/kb/files/${fileId}/download`, { responseType: "blob" });
  return resp.data as Blob;
}

// ---------- 教务（P5 未接入前会返回 404，页面据此显示"未接入"） ----------
export async function getEduStatus() {
  const { data } = await http.get<Envelope<EduStatus>>("/edu/status", { silent: true } as never);
  return data.data;
}

export async function bindEdu(payload: { student_no: string; password: string }) {
  const { data } = await http.post<Envelope<EduStatus>>("/edu/bind", payload);
  return data.data;
}

export async function unbindEdu() {
  await http.delete("/edu/bind");
}

export async function getEduSchedule() {
  const { data } = await http.get<Envelope<{ items: ScheduleSlot[] }>>("/edu/schedule", {
    silent: true,
  } as never);
  return data.data.items;
}

export async function getEduGrades(term?: string) {
  const { data } = await http.get<Envelope<GradeResult>>("/edu/grades", {
    params: term ? { term } : undefined,
    silent: true,
  } as never);
  return data.data;
}

export async function getEduCredits() {
  const { data } = await http.get<Envelope<CreditSummary>>("/edu/credits", { silent: true } as never);
  return data.data;
}
