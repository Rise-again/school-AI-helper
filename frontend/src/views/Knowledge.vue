<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import { UploadFilled } from "@element-plus/icons-vue";
import {
  deleteKbFile,
  listKbChunks,
  listKbFiles,
  reindexKbFile,
  uploadKbFile,
} from "@/api";
import type { KbChunk, KbFile } from "@/types";

const rows = ref<KbFile[]>([]);
const loading = ref(false);
const uploading = ref(false);
const filterStatus = ref("");
const page = ref(1);
const size = ref(10);
const total = ref(0);

const drawerVisible = ref(false);
const chunkFile = ref<KbFile | null>(null);
const chunks = ref<KbChunk[]>([]);
const chunkLoading = ref(false);
const chunkPage = ref(1);
const chunkSize = ref(10);
const chunkTotal = ref(0);

let timer: number | null = null;

const statusMap: Record<string, { text: string; type: "info" | "success" | "warning" | "danger" }> = {
  pending: { text: "排队中", type: "info" },
  parsing: { text: "解析中", type: "warning" },
  success: { text: "已完成", type: "success" },
  failed: { text: "失败", type: "danger" },
};

const hasRunning = computed(() =>
  rows.value.some((r) => r.parse_status === "pending" || r.parse_status === "parsing"),
);

async function load() {
  loading.value = true;
  try {
    const data = await listKbFiles(page.value, size.value, filterStatus.value || undefined);
    rows.value = data.items;
    total.value = data.total;
  } finally {
    loading.value = false;
  }
}

/** 解析是后台任务：有排队/解析中的文件时每 3 秒刷新一次 */
function schedulePoll() {
  if (timer) window.clearTimeout(timer);
  if (hasRunning.value) {
    timer = window.setTimeout(async () => {
      await load();
      schedulePoll();
    }, 3000);
  }
}

async function onUpload(file: UploadFile) {
  if (!file.raw) return;
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", file.raw);
    form.append("source_dept", "后台导入");
    await uploadKbFile(form);
    ElMessage.success("已上传，正在解析");
    await load();
    schedulePoll();
  } finally {
    uploading.value = false;
  }
}

async function remove(row: KbFile) {
  await ElMessageBox.confirm(`删除「${row.filename}」及其向量？`, "确认删除", { type: "warning" });
  await deleteKbFile(row.id);
  ElMessage.success("已删除");
  load();
}

async function reindex(row: KbFile) {
  await reindexKbFile(row.id);
  ElMessage.success("已开始重建");
  await load();
  schedulePoll();
}

async function openChunks(row: KbFile) {
  drawerVisible.value = true;
  chunkFile.value = row;
  chunkPage.value = 1;
  await loadChunks();
}

async function loadChunks() {
  if (!chunkFile.value) return;
  chunkLoading.value = true;
  try {
    const data = await listKbChunks(chunkFile.value.id, chunkPage.value, chunkSize.value);
    chunks.value = data.items;
    chunkTotal.value = data.total;
  } finally {
    chunkLoading.value = false;
  }
}

onMounted(async () => {
  await load();
  schedulePoll();
});
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer);
});
</script>

<template>
  <div class="page">
    <h2 class="page-title">知识库管理</h2>
    <p class="page-desc">支持 PDF / Word / Excel / PPT / HTML / 图片；扫描件自动转 OCR，解析约 30 秒一页。</p>

    <el-upload
      class="uploader"
      drag
      :auto-upload="false"
      :show-file-list="false"
      :on-change="onUpload"
      :disabled="uploading"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">
        {{ uploading ? "上传中…" : "把文件拖到这里，或<em>点击选择</em>" }}
      </div>
      <template #tip>
        <div class="el-upload__tip">单文件不超过 50MB</div>
      </template>
    </el-upload>

    <div class="toolbar">
      <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px" @change="load">
        <el-option label="已完成" value="success" />
        <el-option label="解析中" value="parsing" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="filename" label="文件" min-width="220" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ (row.size_bytes / 1024 / 1024).toFixed(1) }} MB</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusMap[row.parse_status]?.type" effect="plain" size="small">
            {{ statusMap[row.parse_status]?.text || row.parse_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="切片" width="80" />
      <el-table-column prop="parse_channel" label="通道" width="120" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="row.parse_status !== 'success'" @click="openChunks(row)">
            切片
          </el-button>
          <el-button link @click="reindex(row)">重建</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有入库文件" :image-size="70" />
      </template>
    </el-table>

    <el-pagination
      v-if="total > size"
      v-model:current-page="page"
      :page-size="size"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 14px; justify-content: flex-end"
      @current-change="load"
    />

    <el-drawer v-model="drawerVisible" :title="chunkFile?.filename" size="46%">
      <div v-loading="chunkLoading" class="chunks">
        <div v-for="c in chunks" :key="c.id" class="chunk">
          <div class="chunk-head">
            <el-tag size="small" type="info">#{{ c.ordinal }}</el-tag>
            <span class="meta">{{ c.token_count }} token</span>
            <span class="meta">{{ (c.meta?.heading_path as string) || "—" }}</span>
          </div>
          <div class="chunk-body">{{ c.content }}</div>
        </div>
        <el-empty v-if="!chunks.length && !chunkLoading" description="没有切片数据" :image-size="60" />
      </div>
      <el-pagination
        v-if="chunkTotal > chunkSize"
        v-model:current-page="chunkPage"
        :page-size="chunkSize"
        :total="chunkTotal"
        layout="prev, pager, next"
        style="margin-top: 12px; justify-content: center"
        @current-change="loadChunks"
      />
    </el-drawer>
  </div>
</template>

<style scoped>
.uploader {
  margin-bottom: 16px;
}
.uploader :deep(.el-upload-dragger) {
  padding: 22px;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.chunks {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chunk {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
}
.chunk-head {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.meta {
  font-size: 12px;
  color: #6b7280;
}
.chunk-body {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  color: #374151;
  max-height: 220px;
  overflow-y: auto;
}
</style>
