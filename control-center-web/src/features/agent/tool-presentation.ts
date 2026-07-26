const toolNames: Record<string, string> = {
  ime_overview: '当前状态',
  ime_input: '输入法与词库',
  ime_voice: '语音输入',
  ime_planning: '任务与安排',
  ime_memory: '我的记忆',
  agent_role_book: '伙伴记忆',
  ime_knowledge: '知识库',
  ime_models: '模型与连接',
  ime_runtime: '运行检查',
  ime_configuration: '设置与记录',
  ime_agents: '多人协作',
  ime_browser: '浏览网页',
  ime_plugins: '扩展能力',
  agent_plan: '任务清单',
  agent_schedule: '定时提醒',
  desktop_semantic: '操作当前应用',
  room_state: '查看协作状态',
  room_post: '发送协作消息',
  room_commit: '提交工作结果',
  room_collaborate: '邀请伙伴协作',
  skill_load: '读取技能说明',
  tool_load: '读取工具说明',
  workspace_list: '浏览项目文件',
  workspace_read: '读取项目文件',
  workspace_search: '搜索项目内容',
  workspace_patch: '修改项目文件',
  workspace_shell: '运行项目命令',
  read: '读取文件',
  read_file: '读取文件',
  write: '写入文件',
  write_file: '写入文件',
  workspace_write_file: '写入文件',
  edit: '编辑文件',
  edit_file: '编辑文件',
  workspace_edit_file: '编辑文件',
  bash: '运行命令',
  shell: '运行命令',
  grep: '搜索文本',
  find: '查找文件',
  ls: '浏览目录',
  todo: '待办事项',
  write_todos: '待办事项',
  update_plan: '更新计划',
};

const toolIntents: Record<string, string> = {
  ime_overview: '帮我看看当前状态',
  ime_input: '帮我调整输入法或词库',
  ime_voice: '帮我检查语音输入',
  ime_planning: '帮我整理任务与安排',
  ime_memory: '帮我从记忆里找找',
  agent_role_book: '帮我查看伙伴记忆',
  ime_knowledge: '帮我从知识库里查找',
  ime_models: '帮我检查模型与连接',
  ime_runtime: '帮我检查运行状态',
  ime_configuration: '帮我查看设置或变更记录',
  ime_agents: '请伙伴和我一起完成',
  ime_browser: '帮我查看当前网页',
  agent_plan: '帮我整理任务清单',
  workspace_list: '帮我看看项目里有哪些文件',
  workspace_read: '帮我读取这个项目文件',
  workspace_search: '帮我在项目里搜索',
  workspace_patch: '帮我修改这个项目文件',
  workspace_shell: '帮我运行这条项目命令',
};

export function publicToolName(toolId: string, fallback = ''): string {
  const normalizedId = toolId.trim().toLowerCase();
  const mapped = toolNames[normalizedId];
  if (mapped) return mapped;
  const readableFallback = fallback.trim();
  return isReadableToolName(readableFallback) ? readableFallback : '工具操作';
}

export function toolIntentPrompt(toolId: string, fallback = ''): string {
  const normalizedId = toolId.trim().toLowerCase();
  return toolIntents[normalizedId] ?? `帮我用${publicToolName(normalizedId, fallback)}处理`;
}

function isReadableToolName(value: string): boolean {
  return Boolean(value)
    && value.length <= 64
    && !/pathId|schema|receipt|operation|policy|profile|\/api\/|https?:\/\//i.test(value);
}
