<script setup lang="ts">
import { School } from "@element-plus/icons-vue";
</script>

<template>
  <div class="page">
    <h2 class="page-title">教务查询</h2>
    <p class="page-desc">课表、成绩与学分统计。</p>

    <el-result icon="info" title="教务系统正在接入">
      <template #sub-title>
        <p>该功能依赖学校正方教务系统的账号绑定，目前仍在开发中（P5 阶段）。</p>
        <p>接入后可以在这里直接查看本人课表、成绩与学分，无需再跳转。</p>
      </template>
      <template #extra>
        <el-button type="primary" :icon="School" tag="a" href="http://zfjw.hntou.edu.cn/jwglxt/xtgl/login_slogin.html" target="_blank">
          前往教务系统
        </el-button>
      </template>
    </el-result>
  </div>
</template>
