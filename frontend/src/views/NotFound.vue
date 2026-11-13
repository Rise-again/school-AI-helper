<template>
  <div class="page">
    <el-result icon="warning" title="页面不存在" sub-title="地址可能输错了，或者这个页面还没做">
      <template #extra>
        <el-button type="primary" @click="$router.replace('/')">回到首页</el-button>
      </template>
    </el-result>
  </div>
</template>
