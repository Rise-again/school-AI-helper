import http from "./http";
import type {
  Conversation,
  Envelope,
  KbChunk,
  KbFile,
  Message,
  Page,
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
