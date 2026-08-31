export default {
  new: { desc: '创建新会话' },
  login: { desc: '在浏览器中登录拓知' },
  plan: { desc: '切换计划模式 开/关' },
  swarm: { desc: '切换 swarm 模式；/swarm <任务> 直接在 swarm 下执行' },
  auto: { desc: '完全自主，智能体不再提问' },
  compact: { desc: '压缩会话历史' },
  export: {
    desc: '将当前会话和排障日志下载为 ZIP 压缩包',
    noSession: '请先打开一个会话再导出。',
  },
  status: { desc: '查看会话状态' },
};
