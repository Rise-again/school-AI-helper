<script setup lang="ts">
import { useRouter } from "vue-router";

const router = useRouter();

function goHome() {
  router.replace({ name: "chat" });
}
</script>

<template>
  <div class="page">
    <el-result icon="warning" title="403 · 没有访问权限">
      <template #sub-title>
        <p>当前账号的角色无权访问这个页面。</p>
        <p>学生只能使用问答、历史与教务；知识库管理仅管理员可用。</p>
      </template>
      <template #extra>
        <el-button type="primary" @click="goHome">返回首页</el-button>
        <el-button @click="router.back()">返回上一页</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.page {
  padding-top: 8vh;
}
</style>
