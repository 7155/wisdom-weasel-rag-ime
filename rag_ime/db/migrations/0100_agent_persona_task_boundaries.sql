ALTER TABLE agent_personas
ADD COLUMN suitable_tasks_json TEXT NOT NULL DEFAULT '["用户定义的陪伴与协作任务"]';

ALTER TABLE agent_personas
ADD COLUMN unsuitable_tasks_json TEXT NOT NULL DEFAULT '["超出已连接工具、权限或证据范围的任务"]';
