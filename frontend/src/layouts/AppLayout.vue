<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChatDotRound, Clock, School, Collection, SwitchButton } from "@element-plus/icons-vue";
import { ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const menus = computed(() => {
  const items = [{ name: "chat", label: "智能问答", icon: ChatDotRound }];
  items.push({ name: "history", label: "历史记录", icon: Clock });
  if (auth.isStudent) items.push({ name: "edu", label: "教务查询", icon: School });
  if (auth.isAdmin) items.push({ name: "knowledge", label: "知识库管理", icon: Collection });
  return items;
});

async function signOut() {
  await ElMessageBox.confirm("确定退出登录？", "提示", { type: "warning" });
  auth.signOut();
  router.push({ name: "login" });
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="brand">校园智能助手</div>
      <el-menu :default-active="String(route.name)" router class="menu">
        <el-menu-item v-for="m in menus" :key="m.name" :index="m.name" :route="{ name: m.name }">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="title">{{ route.meta.title }}</span>
        <el-dropdown trigger="click">
          <span class="user">
            {{ auth.displayName }}
            <el-tag size="small" type="info" effect="plain" style="margin-left: 6px">
              {{ auth.isAdmin ? "管理员" : "学生" }}
            </el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="signOut">
                <el-icon><SwitchButton /></el-icon> 退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100%;
}
.aside {
  background: #fff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  font-weight: 600;
  font-size: 15px;
  border-bottom: 1px solid #f1f2f4;
}
.menu {
  border-right: none;
}
.header {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.title {
  font-weight: 600;
  font-size: 15px;
}
.user {
  cursor: pointer;
  font-size: 14px;
  outline: none;
}
.main {
  padding: 0;
  overflow: auto;
}
@media (max-width: 640px) {
  .aside {
    width: 64px !important;
  }
  .brand {
    font-size: 0;
    justify-content: center;
  }
  .brand::first-letter {
    font-size: 16px;
  }
  .menu :deep(.el-menu-item span) {
    display: none;
  }
}
</style>
