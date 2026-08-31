export default {
  new: { desc: 'Create a new session' },
  login: { desc: 'Sign in to TopoMind in the browser' },
  plan: { desc: 'Toggle plan mode on/off' },
  swarm: { desc: 'Toggle swarm mode; /swarm <task> runs a task in swarm' },
  auto: { desc: 'Fully autonomous — the agent never asks questions' },
  compact: { desc: 'Compact the conversation history' },
  export: {
    desc: 'Download this session and troubleshooting logs as a ZIP',
    noSession: 'Open a session before exporting it.',
  },
  status: { desc: 'View session status' },
} as const;
