import { createRouter, createWebHashHistory, type RouteRecordRaw } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/Login.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/guest",
    name: "guest",
    component: () => import("@/views/GuestChat.vue"),
    meta: { public: true, title: "访客咨询" },
  },
  {
    path: "/",
    component: () => import("@/layouts/AppLayout.vue"),
    children: [
      { path: "", redirect: "/chat" },
      {
        path: "chat",
        name: "chat",
        component: () => import("@/views/Chat.vue"),
        meta: { title: "智能问答", roles: ["student", "admin"] },
      },
      {
        path: "history",
        name: "history",
        component: () => import("@/views/History.vue"),
        meta: { title: "历史记录", roles: ["student", "admin"] },
      },
      {
        path: "edu",
        name: "edu",
        component: () => import("@/views/Edu.vue"),
        meta: { title: "教务查询", roles: ["student"] },
      },
      {
        path: "knowledge",
        name: "knowledge",
        component: () => import("@/views/Knowledge.vue"),
        meta: { title: "知识库管理", roles: ["admin"] },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("@/views/NotFound.vue"),
    meta: { public: true, title: "页面不存在" },
  },
];

const router = createRouter({
  // hash 模式：平台自定义服务只映射一个端口，没有静态资源回退，history 模式刷新会 404
  history: createWebHashHistory(),
  routes,
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (to.meta.title) document.title = `${to.meta.title} · 校园智能助手`;

  if (to.meta.public) {
    if (to.name === "login" && auth.isLoggedIn) return { name: "chat" };
    return true;
  }

  if (!auth.isLoggedIn) {
    return { name: "login", query: { redirect: to.fullPath } };
  }

  // 角色越权：直接拦回首页，而不是让后端返回 403
  const roles = (to.meta.roles as string[] | undefined) ?? [];
  if (roles.length && auth.role && !roles.includes(auth.role)) {
    return { name: auth.isAdmin ? "knowledge" : "chat" };
  }
  return true;
});

export default router;
