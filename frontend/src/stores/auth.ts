import { defineStore } from "pinia";
import { login as apiLogin, me as apiMe } from "@/api";
import { clearTokens, setTokens } from "@/api/http";
import type { UserProfile } from "@/types";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    profile: JSON.parse(localStorage.getItem("profile") || "null") as UserProfile | null,
    token: localStorage.getItem("access_token") || "",
  }),
  getters: {
    isLoggedIn: (s) => Boolean(s.token && s.profile),
    role: (s) => s.profile?.role ?? null,
    isAdmin: (s) => s.profile?.role === "admin",
    isStudent: (s) => s.profile?.role === "student",
    displayName: (s) => s.profile?.name || s.profile?.username || "未登录",
  },
  actions: {
    async signIn(username: string, password: string) {
      const tokens = await apiLogin(username, password);
      setTokens(tokens.access_token, tokens.refresh_token);
      this.token = tokens.access_token;
      await this.loadProfile();
    },
    async loadProfile() {
      const profile = await apiMe();
      this.profile = profile;
      localStorage.setItem("profile", JSON.stringify(profile));
      return profile;
    },
    signOut() {
      clearTokens();
      this.token = "";
      this.profile = null;
    },
  },
});
