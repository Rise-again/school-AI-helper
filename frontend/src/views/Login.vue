<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "" });

async function submit() {
  if (!form.username || !form.password) return;
  loading.value = true;
  try {
    await auth.signIn(form.username, form.password);
    ElMessage.success("登录成功");
    const redirect = (route.query.redirect as string) || "";
    router.replace(redirect || { name: auth.isAdmin ? "knowledge" : "chat" });
  } catch {
    /* 错误提示已由拦截器统一处理 */
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <h1>校园智能助手</h1>
      <p class="sub">海南热带海洋学院 · 校园问答与教务服务</p>

      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="学号或管理员账号" size="large" autofocus />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
          登录
        </el-button>
      </el-form>

      <div class="tip">
        没有账号？
        <router-link to="/guest">以访客身份咨询</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100%;
  display: grid;
  place-items: center;
  background: linear-gradient(160deg, #f8fafc 0%, #eef2f7 100%);
  padding: 20px;
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 32px 28px 24px;
}
h1 {
  font-size: 22px;
  margin: 0 0 6px;
}
.sub {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 24px;
}
.tip {
  margin-top: 18px;
  font-size: 13px;
  color: #6b7280;
  text-align: center;
}
.tip a {
  color: var(--el-color-primary);
  text-decoration: none;
}
</style>
