const bundledSkillPresentation: Readonly<Record<string, { name: string; description: string }>> = {
  'agent-eval-room-optimizer': { name: '实验执行', description: '按实验约定评测 Agent、工具、流程、检索或记忆。' },
  'agent-lab-project': { name: 'Lab 项目交付', description: '从业务描述和材料出发，制作适合项目的成果与界面。' },
  'alignment-and-decision': { name: '需求与决策', description: '澄清影响范围、验收和成本等关键选择。' },
  'bootstrap-project-context': { name: '项目上下文', description: '为缺少可靠入口的项目建立或补齐根目录说明。' },
  'ego-browser': { name: '网页操作', description: '使用 PAW 内置浏览器阅读网页、填写表单和验证页面。' },
  'facilitate-room': { name: 'Room 协作主持', description: '组织伙伴分工、整合结果，并完成协作验收。' },
  'implementation-planning': { name: '实施规划', description: '把已确认的改动拆成有依赖关系、可验证的步骤。' },
  'improve-codebase-architecture': { name: '架构改进', description: '根据代码证据找出值得实施的架构改进。' },
  'independent-review': { name: '独立审查', description: '对照原始要求与项目标准，审查已有改动和结果。' },
  'memory-curation': { name: '记忆整理', description: '审阅证据，为长期记忆准备可审查的更新。' },
  'orchestrate-session': { name: '子 Agent 协作', description: '委派边界明确的辅助工作，由当前对话整合结果。' },
  'organize-work-documents': { name: '工作文档整理', description: '整理用户原始要求、来源链接和已接受的工作记录。' },
  'pawos-app-builder': { name: '制作 PAW 应用', description: '制作、验证和维护拥有独立界面的 PAW 扩展应用。' },
  'pawos-system': { name: 'PAW 系统使用', description: '解释和操作 PAW 的应用、对话、协作、记忆与系统设置。' },
  'plugin-creator': { name: '插件获取与制作', description: '查找、检查或制作可复用的技能、扩展、提示词与主题包。' },
  'project-maintainer': { name: '安装与维护', description: '维护 PAW 的安装、更新、恢复和托管运行环境。' },
  'rag-retrieval-optimization': { name: '知识检索优化', description: '构建和优化文档解析、索引与检索流程，并验证效果。' },
  'systematic-debugging': { name: '故障定位', description: '先复现并定位故障原因，再验证修复。' },
  'test-driven-implementation': { name: '实现与回归测试', description: '为明确的行为改动建立回归检查，再完成实现。' },
  'trace-agent-diagnostics': { name: '运行诊断', description: '根据对话和运行记录定位失败、评估执行质量并提出修复。' },
};

export function presentSkill(skill: { name?: unknown; skillId?: unknown; description?: unknown; sourceKind?: unknown }) {
  const name = typeof skill.name === 'string' && skill.name
    ? skill.name : typeof skill.skillId === 'string' && skill.skillId ? skill.skillId : '未命名技能';
  const original = { name, description: typeof skill.description === 'string' ? skill.description : '' };
  return (skill.sourceKind === 'bundled' ? bundledSkillPresentation[name] : undefined) ?? original;
}
