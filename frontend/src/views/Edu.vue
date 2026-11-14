<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { School } from "@element-plus/icons-vue";
import {
  bindEdu,
  getEduCredits,
  getEduGrades,
  getEduSchedule,
  getEduStatus,
  unbindEdu,
} from "@/api";
import type { CreditSummary, GradeItem, ScheduleSlot } from "@/types";

type PageState = "loading" | "unavailable" | "unbound" | "ready";

const state = ref<PageState>("loading");
const boundAccount = ref("");
const tab = ref("schedule");

const schedule = ref<ScheduleSlot[]>([]);
const grades = ref<GradeItem[]>([]);
const terms = ref<string[]>([]);
const term = ref("");
const credits = ref<CreditSummary | null>(null);
const loadingData = ref(false);

const bindForm = ref({ student_no: "", password: "" });
const binding = ref(false);

const EDU_SYSTEM = "http://zfjw.hntou.edu.cn/jwglxt/xtgl/login_slogin.html";

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const SECTIONS = Array.from({ length: 12 }, (_, i) => i + 1);

/** 课表按节次行 × 星期列摆放；同一格多门课用换行隔开 */
const scheduleRows = computed(() => {
  const cells = new Map<string, ScheduleSlot[]>();
  for (const slot of schedule.value) {
    for (const sec of slot.sections) {
      const key = `${sec}-${slot.weekday}`;
      const list = cells.get(key) ?? [];
      list.push(slot);
      cells.set(key, list);
    }
  }
  return SECTIONS.map((sec) => ({
    section: sec,
    cells: WEEKDAYS.map((_, idx) => cells.get(`${sec}-${idx + 1}`) ?? []),
  }));
});

function apiStatus(err: unknown): number | undefined {
  return (err as { status?: number } | null)?.status;
}

async function loadAll() {
  loadingData.value = true;
  try {
    const [s, g, c] = await Promise.all([getEduSchedule(), getEduGrades(), getEduCredits()]);
    schedule.value = s;
    grades.value = g.items;
    terms.value = g.terms;
    term.value = g.terms[0] ?? "";
    credits.value = c;
  } catch (err) {
    if ([404, 501].includes(apiStatus(err) ?? 0)) {
      state.value = "unavailable";
    } else {
      ElMessage.error("教务数据加载失败，请稍后重试");
    }
  } finally {
    loadingData.value = false;
  }
}

async function init() {
  try {
    const status = await getEduStatus();
    if (!status.bound) {
      state.value = "unbound";
      return;
    }
    boundAccount.value = status.student_no ?? "";
    state.value = "ready";
    await loadAll();
  } catch (err) {
    // 404/501：P5 还没接，页面保持"未接入"引导态
    state.value = "unavailable";
  }
}

async function submitBind() {
  const { student_no, password } = bindForm.value;
  if (!student_no.trim() || !password) {
    ElMessage.warning("请填写学号与教务密码");
    return;
  }
  binding.value = true;
  try {
    await bindEdu({ student_no: student_no.trim(), password });
    ElMessage.success("绑定成功");
    bindForm.value = { student_no: "", password: "" };
    state.value = "ready";
    boundAccount.value = student_no.trim();
    await loadAll();
  } finally {
    binding.value = false;
  }
}

async function submitUnbind() {
  await ElMessageBox.confirm("解绑后需要重新输入教务密码才能查询，确定解绑？", "解绑教务账号", {
    type: "warning",
  });
  await unbindEdu();
  ElMessage.success("已解绑");
  schedule.value = [];
  grades.value = [];
  credits.value = null;
  state.value = "unbound";
}

async function changeTerm(value: string) {
  const result = await getEduGrades(value);
  grades.value = result.items;
}

onMounted(init);
</script>

<template>
  <div class="page">
    <h2 class="page-title">教务查询</h2>
    <p class="page-desc">课表、成绩与学分统计。数据来自学校正方教务系统，仅本人可见。</p>

    <el-skeleton v-if="state === 'loading'" :rows="5" animated class="card" />

    <el-result
      v-else-if="state === 'unavailable'"
      icon="info"
      title="教务服务尚未接入"
      sub-title="教务查询依赖学校正方系统的登录会话，后端正在开发中（P5 阶段）。页面已按接口契约实现，接入后无需改动前端。"
    >
      <template #extra>
        <el-button type="primary" :icon="School" tag="a" :href="EDU_SYSTEM" target="_blank">
          前往教务系统
        </el-button>
      </template>
    </el-result>

    <div v-else-if="state === 'unbound'" class="card bind-card">
      <h3>绑定教务账号</h3>
      <p class="hint">
        绑定后可直接查询课表、成绩与学分。密码用 RSA 加密后转发给教务系统，服务端只保存登录会话，不保存明文密码。
      </p>
      <el-form label-width="90px" style="max-width: 420px">
        <el-form-item label="学号">
          <el-input v-model="bindForm.student_no" placeholder="请输入学号" maxlength="20" />
        </el-form-item>
        <el-form-item label="教务密码">
          <el-input v-model="bindForm.password" type="password" show-password placeholder="请输入教务系统密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="binding" @click="submitBind">绑定</el-button>
          <el-button tag="a" :href="EDU_SYSTEM" target="_blank">去教务系统</el-button>
        </el-form-item>
      </el-form>
    </div>

    <template v-else>
      <div class="toolbar">
        <span class="account">已绑定：{{ boundAccount || "本人账号" }}</span>
        <el-button link type="danger" @click="submitUnbind">解绑</el-button>
      </div>

      <el-tabs v-model="tab" class="card">
        <el-tab-pane label="课表" name="schedule">
          <el-skeleton v-if="loadingData" :rows="6" animated />
          <el-table v-else :data="scheduleRows" border size="small" class="timetable">
            <el-table-column prop="section" label="节次" width="70" align="center" />
            <el-table-column
              v-for="(day, idx) in WEEKDAYS"
              :key="idx"
              :label="day"
              min-width="130"
            >
              <template #default="{ row }">
                <div v-for="(slot, i) in row.cells[idx]" :key="i" class="slot">
                  <div class="slot-course">{{ slot.course }}</div>
                  <div class="slot-meta">{{ slot.location }} {{ slot.weeks }}</div>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loadingData && !schedule.length" description="本学期暂无课表数据" :image-size="70" />
        </el-tab-pane>

        <el-tab-pane label="成绩" name="grades">
          <div class="filter">
            <el-select v-model="term" placeholder="选择学期" style="width: 200px" @change="changeTerm">
              <el-option v-for="t in terms" :key="t" :label="t" :value="t" />
            </el-select>
          </div>
          <el-table v-loading="loadingData" :data="grades" stripe>
            <el-table-column prop="course" label="课程" min-width="220" show-overflow-tooltip />
            <el-table-column prop="credit" label="学分" width="90" align="center" />
            <el-table-column prop="score" label="成绩" width="90" align="center" />
            <el-table-column prop="gpa" label="绩点" width="90" align="center" />
            <template #empty>
              <el-empty description="该学期暂无成绩" :image-size="70" />
            </template>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="学分" name="credits">
          <el-skeleton v-if="loadingData" :rows="4" animated />
          <template v-else-if="credits">
            <el-row :gutter="14" class="stats">
              <el-col :xs="12" :sm="6">
                <div class="stat"><div class="num">{{ credits.required }}</div><div class="lab">应修学分</div></div>
              </el-col>
              <el-col :xs="12" :sm="6">
                <div class="stat"><div class="num">{{ credits.earned }}</div><div class="lab">已修学分</div></div>
              </el-col>
              <el-col :xs="12" :sm="6">
                <div class="stat"><div class="num">{{ credits.gpa.toFixed(2) }}</div><div class="lab">平均绩点</div></div>
              </el-col>
              <el-col :xs="12" :sm="6">
                <div class="stat">
                  <div class="num">{{ Math.max(credits.required - credits.earned, 0) }}</div>
                  <div class="lab">待修学分</div>
                </div>
              </el-col>
            </el-row>
            <el-table :data="credits.categories" stripe style="margin-top: 16px">
              <el-table-column prop="name" label="课程类别" min-width="180" />
              <el-table-column prop="required" label="应修" width="110" align="center" />
              <el-table-column prop="earned" label="已修" width="110" align="center" />
            </el-table>
          </template>
          <el-empty v-else description="暂无学分数据" :image-size="70" />
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<style scoped>
.bind-card h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.hint {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 16px;
  line-height: 1.7;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.account {
  font-size: 13px;
  color: #6b7280;
}
.timetable :deep(.cell) {
  padding: 4px 6px;
}
.slot {
  font-size: 12px;
  line-height: 1.5;
  padding: 2px 0;
}
.slot-course {
  font-weight: 500;
  color: #1f2937;
}
.slot-meta {
  color: #6b7280;
}
.filter {
  margin-bottom: 12px;
}
.stats .stat {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 16px;
  text-align: center;
}
.stats .num {
  font-size: 22px;
  font-weight: 600;
  color: #1d4ed8;
}
.stats .lab {
  font-size: 12px;
  color: #6b7280;
  margin-top: 4px;
}
</style>
