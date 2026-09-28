/** Shared status colors for TaskFlowDag (no React — safe for node + parent). */

export const STATUS_COLOR: Record<string, string> = {
  pending: "#4a665c",
  ready: "#ffb454",
  running: "#3dffa8",
  success: "#7eaea0",
  waiting_for_user: "#fbbf24",
  failed: "#ff6b6b",
  retrying: "#ffb454",
  cancelled: "#6b7280",
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "等待",
  ready: "就绪",
  running: "执行中",
  success: "完成",
  waiting_for_user: "待审批",
  failed: "失败",
  retrying: "重试",
  cancelled: "已取消",
};
