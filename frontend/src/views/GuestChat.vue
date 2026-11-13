<script setup lang="ts">
import { nextTick, ref } from "vue";
import { Link } from "@element-plus/icons-vue";
import { streamChat } from "@/api/stream";
import type { Citation } from "@/types";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
}

const input = ref("");
const turns = ref<Turn[]>([]);
const sending = ref(false);
const scroller = ref<HTMLElement | null>(null);

function scroll() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
  });
}

function send() {
  const text = input.value.trim();
  if (!text || sending.value) return;
  turns.value.push({ role: "user", content: text });
  const reply: Turn = { role: "assistant", content: "", streaming: true };
  turns.value.push(reply);
  input.value = "";
  sending.value = true;
  scroll();

  streamChat("/chat/anonymous", { content: text }, {
    onDelta: (t) => {
      reply.content += t;
      scroll();
    },
    onCitations: (items) => {
      reply.citations = items;
    },
    onDone: () => {
      reply.streaming = false;
      sending.value = false;
    },
    onError: (msg) => {
      reply.content = reply.content || `出错了：${msg}`;
      reply.streaming = false;
      sending.value = false;
    },
  });
}
</script>

<template>
  <div class="guest">
    <header class="head">
      <div>
        <h1>访客咨询</h1>
        <p>招生政策、办事流程、校园百科，无需登录即可提问。对话不会保存。</p>
      </div>
      <router-link to="/login">
        <el-button text type="primary">登录</el-button>
      </router-link>
    </header>

    <div ref="scroller" class="turns">
      <el-empty v-if="!turns.length" description="试试问：新生报到需要带什么材料？" :image-size="80" />
      <div v-for="(t, i) in turns" :key="i" class="msg" :class="t.role">
        <div class="bubble">
          <div class="content">{{ t.content }}<span v-if="t.streaming" class="cursor">▋</span></div>
          <div v-if="t.citations?.length" class="cites">
            <div v-for="(c, idx) in t.citations" :key="idx" class="cite">
              <el-icon><Link /></el-icon>
              <span class="cite-text">[{{ idx + 1 }}] {{ c.snippet }}</span>
              <el-link v-if="c.url" :href="c.url" target="_blank" type="primary" :underline="false">原文</el-link>
            </div>
          </div>
        </div>
      </div>
    </div>

    <footer class="composer">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        resize="none"
        maxlength="500"
        show-word-limit
        placeholder="输入问题，Enter 发送（每 IP 每分钟限 10 次）"
        @keydown.enter.exact.prevent="send"
      />
      <div class="actions">
        <el-button type="primary" :loading="sending" :disabled="!input.trim()" @click="send">
          发送
        </el-button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.guest {
  height: 100%;
  display: flex;
  flex-direction: column;
  max-width: 860px;
  margin: 0 auto;
  padding: 0 16px;
}
.head {
  padding: 22px 0 12px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
h1 {
  font-size: 20px;
  margin: 0 0 4px;
}
.head p {
  margin: 0;
  color: #6b7280;
  font-size: 13px;
}
.turns {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 16px;
}
.msg {
  display: flex;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 80%;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px 14px;
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
.composer {
  border-top: 1px solid #e5e7eb;
  padding: 12px 0 16px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
@media (max-width: 640px) {
  .bubble {
    max-width: 92%;
  }
}
</style>
