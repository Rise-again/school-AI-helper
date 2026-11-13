<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Plus, Promotion, VideoPause, Link } from "@element-plus/icons-vue";
import { createConversation, downloadKbFile, listConversations, listMessages } from "@/api";
import { streamChat } from "@/api/stream";
import type { Citation, Conversation } from "@/types";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  meta?: { intent: string; degraded: string; evidence: number };
}

const conversations = ref<Conversation[]>([]);
const activeId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const input = ref("");
const sending = ref(false);
const loadingConv = ref(false);
const scroller = ref<HTMLElement | null>(null);
let currentStream: { abort: () => void } | null = null;

const activeTitle = computed(
  () => conversations.value.find((c) => c.id === activeId.value)?.title ?? "新的对话",
);

async function loadConversations() {
  const page = await listConversations();
  conversations.value = page.items;
  if (!activeId.value && page.items.length) {
    await selectConversation(page.items[0].id);
  }
}

async function selectConversation(id: number) {
  if (sending.value) return;
  activeId.value = id;
  const page = await listMessages(id);
  messages.value = page.items
    .filter((m) => m.role !== "system")
    .map((m) => ({ id: String(m.id), role: m.role as "user" | "assistant", content: m.content }));
  scrollToBottom();
}

async function newConversation() {
  if (sending.value) return;
  const conv = await createConversation();
  conversations.value.unshift(conv);
  activeId.value = conv.id;
  messages.value = [];
}

function scrollToBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
  });
}

async function send() {
  const text = input.value.trim();
  if (!text || sending.value) return;

  if (!activeId.value) {
    const conv = await createConversation(text.slice(0, 20));
    conversations.value.unshift(conv);
    activeId.value = conv.id;
  }

  const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: text };
  const reply: ChatMessage = {
    id: `a-${Date.now()}`,
    role: "assistant",
    content: "",
    streaming: true,
  };
  messages.value.push(userMsg, reply);
  input.value = "";
  sending.value = true;
  scrollToBottom();

  const token = localStorage.getItem("access_token") || "";
  currentStream = streamChat(
    `/conversations/${activeId.value}/messages`,
    { content: text },
    {
      onMeta: (m) => {
        reply.meta = { intent: m.intent, degraded: m.degraded, evidence: m.evidence_count };
      },
      onDelta: (t) => {
        reply.content += t;
        scrollToBottom();
      },
      onCitations: (items) => {
        reply.citations = items;
        scrollToBottom();
      },
      onDone: () => {
        reply.streaming = false;
        sending.value = false;
        currentStream = null;
        refreshConversationList();
      },
      onError: (msg) => {
        reply.streaming = false;
        reply.content = reply.content || `出错了：${msg}`;
        sending.value = false;
        currentStream = null;
        ElMessage.error(msg);
      },
    },
    { token },
  );
}

function stop() {
  currentStream?.abort();
  currentStream = null;
  sending.value = false;
  const last = messages.value[messages.value.length - 1];
  if (last?.streaming) last.streaming = false;
  ElMessage.info("已停止生成");
}

/** 打开引用原文：外部链接直接开；知识库文件走鉴权下载再打开 */
async function openSource(c: Citation) {
  if (c.url) {
    window.open(c.url, "_blank", "noopener");
    return;
  }
  if (!c.kb_file_id) return;
  try {
    const blob = await downloadKbFile(c.kb_file_id);
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch {
    ElMessage.error("原文打开失败，请稍后重试");
  }
}

function refreshConversationList() {
  listConversations().then((page) => {
    conversations.value = page.items;
  });
}

onMounted(loadConversations);
</script>

<template>
  <div class="chat">
    <aside class="conv-list">
      <el-button class="new-btn" type="primary" plain :icon="Plus" @click="newConversation">
        新建对话
      </el-button>
      <el-scrollbar class="conv-scroll">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === activeId }"
          @click="selectConversation(c.id)"
        >
          {{ c.title || "未命名会话" }}
        </div>
        <el-empty v-if="!conversations.length" description="还没有会话" :image-size="60" />
      </el-scrollbar>
    </aside>

    <section class="main">
      <div class="main-head">{{ activeTitle }}</div>

      <div ref="scroller" class="messages">
        <el-empty
          v-if="!messages.length"
          description="问点什么吧，比如「考试作弊怎么处理」"
          :image-size="80"
        />

        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div class="bubble">
            <div class="content">{{ m.content }}<span v-if="m.streaming" class="cursor">▋</span></div>

            <div v-if="m.citations?.length" class="cites">
              <div v-for="(c, i) in m.citations" :key="i" class="cite">
                <el-icon><Link /></el-icon>
                <span class="cite-text">
                  [{{ i + 1 }}] {{ c.snippet }}
                </span>
                <el-tag v-if="c.page_no" size="small" type="info">第 {{ c.page_no }} 页</el-tag>
                <el-button
                  v-if="c.url || c.kb_file_id"
                  link
                  type="primary"
                  @click="openSource(c)"
                >
                  查看原文
                </el-button>
              </div>
            </div>

            <div v-if="m.role === 'assistant' && m.meta?.degraded" class="degraded">
              <el-tag size="small" type="warning" effect="plain">
                {{ m.meta.degraded === "edu_pending" ? "教务未接入" : "已降级" }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          maxlength="500"
          show-word-limit
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="send"
        />
        <div class="actions">
          <el-button v-if="sending" :icon="VideoPause" @click="stop">停止</el-button>
          <el-button v-else type="primary" :icon="Promotion" :disabled="!input.trim()" @click="send">
            发送
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  height: 100%;
  min-height: 0;
}
.conv-list {
  width: 220px;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 10px;
}
.new-btn {
  width: 100%;
}
.conv-scroll {
  flex: 1;
}
.conv-item {
  padding: 9px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: #374151;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-item:hover {
  background: #f3f4f6;
}
.conv-item.active {
  background: #eef2ff;
  color: #1d4ed8;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.main-head {
  height: 44px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  font-size: 14px;
  font-weight: 500;
  border-bottom: 1px solid #f1f2f4;
  background: #fff;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.msg {
  display: flex;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  font-size: 14px;
  line-height: 1.7;
}
.msg.user .bubble {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
}
.content {
  white-space: pre-wrap;
  word-break: break-word;
}
.cursor {
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.cites {
  margin-top: 10px;
  border-top: 1px dashed #e5e7eb;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cite {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}
.cite-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.degraded {
  margin-top: 8px;
}
.composer {
  border-top: 1px solid #e5e7eb;
  background: #fff;
  padding: 12px 18px 16px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
@media (max-width: 768px) {
  .conv-list {
    display: none;
  }
  .bubble {
    max-width: 90%;
  }
}
</style>
