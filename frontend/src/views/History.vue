<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deleteConversation, listConversations, renameConversation } from "@/api";
import type { Conversation } from "@/types";

const rows = ref<Conversation[]>([]);
const loading = ref(false);
const total = ref(0);
const page = ref(1);
const size = ref(10);

async function load() {
  loading.value = true;
  try {
    const data = await listConversations(page.value, size.value);
    rows.value = data.items;
    total.value = data.total;
  } finally {
    loading.value = false;
  }
}

async function rename(row: Conversation) {
  const { value } = await ElMessageBox.prompt("新的会话名称", "重命名", {
    inputValue: row.title,
    inputValidator: (v) => Boolean(v?.trim()) || "名称不能为空",
  });
  await renameConversation(row.id, value.trim());
  ElMessage.success("已重命名");
  load();
}

async function remove(row: Conversation) {
  await ElMessageBox.confirm(`删除「${row.title}」？消息与引用会一并删除。`, "确认删除", {
    type: "warning",
  });
  await deleteConversation(row.id);
  ElMessage.success("已删除");
  load();
}

onMounted(load);
</script>

<template>
  <div class="page">
    <h2 class="page-title">历史记录</h2>
    <p class="page-desc">所有会话按更新时间倒序，删除会话会级联清理消息与引用。</p>

    <el-skeleton v-if="loading && !rows.length" :rows="5" animated class="card" />

    <el-table v-else v-loading="loading" :data="rows" class="card" stripe>
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="role_mode" label="角色" width="100">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ row.role_mode === "admin" ? "管理员" : "学生" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="180">
        <template #default="{ row }">{{ new Date(row.updated_at).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="rename(row)">重命名</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有历史会话" :image-size="70" />
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
  </div>
</template>
