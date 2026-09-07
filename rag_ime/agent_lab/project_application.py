"""App composition for general Lab projects; domain adapters stay optional."""
from __future__ import annotations

import sqlite3
import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .golden import AgentLabGoldenStore
from .projects import AgentLabProjectStore, AgentLabProjectValidationError
from .apps import AgentLabAppStore


class AgentLabProjectApplication:
    def __init__(self, db_path: str | Path, *, session_application: Any,
                 current_model: Callable[[], dict[str, str]], scope_id: str = "local",
                 read_golden: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
                 command_golden: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
                 knowledge: Any = None, start_knowledge: Callable | None = None,
                 cancel_knowledge: Callable | None = None, read_experiments: Callable | None = None,
                 read_trials: Callable | None = None) -> None:
        self.db_path = Path(db_path)
        self.sessions = session_application
        self.current_model = current_model
        self.read_golden = read_golden
        self.command_golden = command_golden
        self.knowledge, self.start_knowledge, self.cancel_knowledge = knowledge, start_knowledge, cancel_knowledge
        self.read_experiments = read_experiments
        self.read_trials = read_trials
        self.apps = AgentLabAppStore(self.db_path,scope_id=scope_id,freeze_knowledge=getattr(knowledge, 'app_resources', None))
        self.store = AgentLabProjectStore(self.db_path, scope_id=scope_id,
                                         bind_execution=self._bind, create_guide=self._guide,
                                         prepare_app=lambda conn,project,value:self.apps.prepare(conn,project,value,self.current_model()))

    def read(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if not isinstance(payload, Mapping) or set(payload) - {"projectId", "materialSetId", "artifactId", "artifactRevision"}:
            raise AgentLabProjectValidationError("项目读取参数无效。")
        revision = payload.get("artifactRevision")
        if revision == "":
            revision = None
        if isinstance(revision, str) and revision.isascii() and revision.isdecimal():
            revision = int(revision)
        result = self.store.read(payload.get("projectId", ""), material_set_id=payload.get("materialSetId", ""),
                                 artifact_id=payload.get("artifactId", ""), artifact_revision=revision)
        if not payload.get("projectId") and self.read_experiments is not None:
            from .history import public_history_collections
            try:
                result["historyCollections"] = public_history_collections(self.read_experiments())
            except (OSError, ValueError, sqlite3.Error):
                result["historyUnavailable"] = True
        result["availableAdapters"] = [{"adapterId": "golden.context_qa", "title": "资料问答评测",
                                        "description": "从选定文本材料建立标准，由现有 Golden/Pi 执行。创建绑定本身不启动模型。",
                                        'input':{'targetCount':'1–100 之间的整数，默认 12','sourceIds':'可选；此项目 document/history/failure 来源的 sourceId 列表','scenario':'可选；本次评测的任务说明'}}]
        if self.knowledge is not None:
            result["availableAdapters"].append({"adapterId": "golden.knowledge_qa", "title": "知识库回答评测",
                "description": "绑定已完成的 Knowledge 索引和可选的原始评测集；回答前真实检索，参考答案只交给评审。",
                "input": {"indexId": "本项目已完成的索引任务 ID", "datasetId": "可选的原始评测集任务 ID；不传则起草待审核标准",
                          "targetCount": "2–100，默认 12", "profile": "mode,topK,threshold,rerank,candidateDepth,contextChars"}})
            if result.get("project"):
                result["knowledge"] = self.knowledge.read(result["project"]["projectId"])
        if result.get('project'):
            result['commandGuide'] = {
                'publish_artifact':{'new':'直接提供 title,kind,view,content；不包在 artifact 对象里。','update':'artifactId + expectedArtifactRevision，附要修改的字段；只改内容可只给 content。','views':{'markdown':'content 是正文字符串','html':'content 是自包含 HTML 字符串','code':'content={source,language,filename?}','table':'content={columns:[{key,label}],rows:[{列key:值}],caption?}','form':'content={fields:[{key,label,type,required?,options?}],values:{字段key:值},description?}','json':'任意有效 JSON 内容'},'actions':'可选 [{actionId,label,prompt}]；点击会把项目输入发给当前 Guide。'},
                'bind_execution':'input={adapterId, input:适配器参数, artifactId?,artifactRevision?}；绑定不启动模型。',
                'execution':'execution_read 先取绑定 suite 的 revision；draft input 可为 {}，后台生成后需由前端核对和标注，模型不能冒充人工审核。',
                'read_app':'op=read，提供 appId，可选 appVersion、appCallId。默认返回本项目应用版本与调用摘要；appCallId 按需读取实际输入、输出、用量和回执。不启动调用。',
                'prepare_app':{'input':'{directory:相对 executionWorkspace.path 的应用目录, appId?:已有应用标识}',
                    'sourceFile':'app.json','schemaVersion':'paw.lab-app-source.v1','requiredFields':['schemaVersion','title','html','skill','context','actions'],
                    'fields':{'description':'可选的应用说明','html':'自包含 HTML 文件相对路径','skill':'本应用 SKILL.md 方法文件相对路径','context':'要随应用冻结的文本材料相对路径数组','model':'可选 {provider,model,thinkingLevel}；不提供时冻结当前项目默认模型','knowledge':'可选 {indexId,profile?,queryField?}，冻结本项目已完成的 Knowledge 索引。当前支持 lexical 且 rerank=false；原始问题和答案不会进入应用。','actions':'[{id,title,prompt,kind?:completion|retrieval,inputSchema:{type:object,properties:{字段:{type:string|number|integer|boolean,title?,enum?,maxLength?,minimum?,maximum?}},required:[字段]}}]'},
                    'browserApi':'HTML 调用 await window.pawApp.invoke(actionId, values, {onProgress,signal})，获得 {text,usage,receipt?,sources?,knowledge?}。可选 AbortSignal 请求停止，仍等待原调用回执。capabilities.cancel 表示支持停止；ready() 声明应用自己呈现进度。旧两参数调用仍可用。调用失败会 reject 带 state/requestId 的 Error。',
                    'interaction':{'required':'生成 App 时同时设计输入确认、运行中、完成、无结果和失败恢复。不能只放 loading 后等待最终答案。采用 agent-lab-project/assets/portable-app.html 的反馈行为并适配领域界面。',
                        'progress':'onProgress({stage,events?,sources?,knowledge?,text?,streamPartial?,startedAtMs?,updatedAtMs?})；stage: queued/context_ready/retrieving/sources_ready/model_starting/model_wait/thinking/answering/completed/failed/cancelled/interrupted/unconfirmed。events 只记录实际阶段。此回调是公开进度投影，只有 invoke resolve 才能确认完成。',
                        'sources':'实际召回后立刻展示 sources 的 title/uri/text，可展开原文；knowledge.retrievedChunks 是召回数，sources.length 是采用数。context_ready/sourceKind=provided_context 表示直接提供的应用资料，不能说成召回。回答流更新时保持来源展开状态。',
                        'conversation':'对话型 App 默认用紧凑消息流、底部输入、可展开过程和引用，不堆等高结果卡片。真实追问需声明可选 conversation 字符串字段，并把已完成前文作为不可信上下文发送；原问题与新问题分开。研究阶段必须来自实际工具或执行器，不能编排假动画。',
                        'feedback':'按真实 stage 显示检索、连接、等待、思考、输出。只有收到 thinking 才显示思考中。text 标记为尚未完成；streamPartial 时说明过程不完整。不得编造百分比、思考内容、相关度。',
                        'recovery':'保留输入与证据，运行时防重复点击，中断时停止动画并核对原调用。history 恢复结果不触发新模型调用、不覆盖进行中的结果。',
                        'acceptance':'PAW 与独立导出各检查慢调用期间来源可见、阶段变化、输出、失败及历史恢复。区分真实模型与受控测试。'},
                    'runtime':'自定义 HTML + 声明的知识检索或文本模型操作；PAW 通过普通 Pi Session 执行，独立包通过配置的 OpenAI-compatible 服务执行。此封装没有外部业务写入工具，不能声称支持未接入的订单、支付等操作。',
                    'externalWorkspace':'可选 {title,url}，连接已存在的浏览器工作台。URL 仅支持无凭据的 HTTPS 或本机 HTTP，不含查询参数和片段。工作台在独立页面中运行，与问答共享 App 入口；不会获得问答桥接权限或自动执行。服务源码和登录态不随应用导出，必须另行启动。',
                    'output':'返回 application 与不可变版本；前端“应用交付”可试用、添加至 PAW、导出独立或 PAW 应用包。准备不等于安装或效果验证。'},
            }
        return result

    def command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(payload, Mapping) and payload.get("action") == "knowledge":
            return self._knowledge_command(payload)
        if isinstance(payload, Mapping) and payload.get("action") == "import_history":
            from .history import prepare_history_import
            # Snapshot before entering the project transaction. The callback is
            # evaluated only after checking the durable original receipt.
            try:
                experiments = self.read_experiments() if self.read_experiments else []
            except (OSError, ValueError, sqlite3.Error):
                experiments = []
            return self.store.command(payload, history_import=lambda value: prepare_history_import(value, experiments))
        return self.store.command(payload)

    def _knowledge_command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from .knowledge_data import KnowledgeIntakeError
        from .trials import AgentLabTrialConflict, AgentLabTrialServiceUnavailable
        from .projects import AgentLabProjectConflict, AgentLabProjectUnavailable
        if (self.knowledge is None or self.start_knowledge is None or self.cancel_knowledge is None
                or set(payload) != {"action", "projectId", "expectedRevision", "clientRequestId", "input"}
                or type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 1
                or not isinstance(payload["clientRequestId"], str) or not 1 <= len(payload["clientRequestId"]) <= 240
                or not isinstance(payload["input"], Mapping)):
            raise AgentLabProjectValidationError("知识库操作需要当前项目和有效参数。")
        project = self.store.read(payload["projectId"])["project"]
        value = dict(payload["input"])
        try:
            if value.get("operation") in {"upload_begin", "upload_chunk", "upload_seal"}:
                result = self.knowledge.upload(project["projectId"], payload["clientRequestId"], value)
            elif value.get("operation") == "cancel":
                if set(value) != {"operation", "jobId"} or not any(job["jobId"] == value["jobId"] for job in self.knowledge._jobs(project["projectId"])):
                    raise AgentLabProjectValidationError("只能停止此项目的知识库任务。")
                result = self.cancel_knowledge(value["jobId"])
            else:
                if "projectId" in value:
                    raise AgentLabProjectValidationError("知识库操作的项目身份不能由输入替换。")
                # Resources have immutable job identities, independent of brief
                # edits. A stale project revision cannot retarget these inputs.
                result = self.start_knowledge(payload["clientRequestId"], {**value, "projectId": project["projectId"]})
        except KnowledgeIntakeError as exc:
            raise AgentLabProjectValidationError(str(exc)) from exc
        except AgentLabTrialConflict as exc:
            raise AgentLabProjectConflict("此请求已用于另一项知识库操作。请核对原操作。") from exc
        except AgentLabTrialServiceUnavailable as exc:
            raise AgentLabProjectUnavailable() from exc
        return {"ok": True, "project": project, **({"job": result["job"]} if "job" in result else {"upload": result["upload"]}), "clientRequestId": payload["clientRequestId"],
                "replayed": bool(result.get("replayed", False))}

    def _bind(self, conn: sqlite3.Connection, project: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        if request["adapterId"] == "scene.trial":
            from .history import SCENES
            value = request["input"]
            if set(value) != {"sceneId"} or value["sceneId"] not in {row[0] for row in SCENES}:
                raise AgentLabProjectValidationError("请选择已登记的场景。")
            return {"ownerRef": {"kind": "scene_trial", "id": value["sceneId"]},
                    "summary": "历史证据已经保留；执行是否可用以 Trial 服务当前登记的环境为准。新运行单独记录。"}
        if request["adapterId"] == "golden.knowledge_qa" and self.knowledge is not None:
            from .knowledge_data import KnowledgeIntakeError
            try:
                value = self.knowledge.golden_inputs(project, request["input"])
            except KnowledgeIntakeError as exc:
                raise AgentLabProjectValidationError(str(exc)) from exc
            suite = AgentLabGoldenStore(self.db_path, default_model=self.current_model()).create_in_transaction(conn, value)
            return {"ownerRef": {"kind": "golden_suite", "id": suite["suiteId"]},
                    "summary": "已冻结知识库索引与检索配置；题目等待核对，尚未调用模型。"}
        if request["adapterId"] != "golden.context_qa":
            raise AgentLabProjectValidationError("此执行适配器尚未接入。项目成果仍可使用自己的结构和展示形式。")
        value = request["input"]
        if set(value) - {"targetCount", "sourceIds", "scenario"}:
            raise AgentLabProjectValidationError("资料问答绑定参数无效。")
        materials = project["materialSet"]["materials"]
        ids = value.get("sourceIds")
        available = {item["sourceId"] for item in materials if item["kind"] in {"document", "history", "failure"}}
        if ids is not None and (not isinstance(ids, list) or not ids
                                or any(not isinstance(item, str) for item in ids) or set(ids) - available):
            raise AgentLabProjectValidationError("请选择此项目中的业务文档、历史任务或失败材料。")
        selected = set(ids) if ids is not None else available
        sources = [{key: item[key] for key in ("sourceId", "title", "kind", "uri", "text")}
                   for item in materials if item["sourceId"] in selected]
        if not sources:
            raise AgentLabProjectValidationError("请先添加可供问答标准引用的业务材料。")
        suite = AgentLabGoldenStore(self.db_path, default_model=self.current_model()).create_in_transaction(conn, {
            "title": project["title"], "scenario": value.get("scenario", project["description"]),
            "sources": sources, "targetCount": value.get("targetCount", 12),
        })
        return {"ownerRef": {"kind": "golden_suite", "id": suite["suiteId"]}, "summary": "已绑定材料版本；尚未执行评测。"}

    def _guide(self, conn: sqlite3.Connection, project: dict[str, Any]) -> dict[str, Any]:
        # Candidate files belong to a managed project workspace. Imported source
        # paths remain material connections, not writable Session roots.
        scope = hashlib.sha256(self.store.scope_id.encode()).hexdigest()[:16]
        workspace = self.db_path.parent / "lab-workspaces" / scope / project["projectId"]
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace = workspace.resolve()
        session = self.sessions.create_in_transaction({
            "title": f'Lab · {project["title"][:90]}', "mode": "coordinator",
            "toolProfileVersion": "control-center-v1", "executionMode": "workspace_managed",
            "workspaceRoots": [str(workspace)], "_internalWorkspaceScopeGrant": True,
            "projectContextEnabled": True, "piSkillsEnabled": True, "codexSkillsEnabled": False,
            "surfaceKind": "extension_app", "ownerAppId": "extension:agent-lab",
            "surfaceKey": f'project.{project["projectId"]}.guide',
        }, conn)
        return {"sessionId": str(session["id"]), "workspace": {"kind": "managed", "path": str(workspace), "createdAtMs": int(time.time() * 1000)}}

    def tool(self, session: Mapping[str, Any], operation: str, args: Mapping[str, Any]) -> dict[str, Any]:
        key = str(session.get("surfaceKey", ""))
        if (session.get("surfaceKind") != "extension_app" or session.get("ownerAppId") != "extension:agent-lab"
                or not key.startswith("project.") or not key.endswith(".guide")):
            raise AgentLabProjectValidationError("此工具需要由对应 Lab 项目的 Agent 调用。")
        project_id = key[len("project."):-len(".guide")]
        project = self.store.read(project_id)["project"]
        if project["guideSessionId"] != session.get("id"):
            raise AgentLabProjectValidationError("引导会话与当前项目绑定不一致。")
        value = {key: item for key, item in args.items() if key not in {"op", "_sessionId"}}
        if operation == "read":
            if set(value) - {"artifactId", "artifactRevision", "materialSetId", "appId", "appVersion", "appCallId"}:
                raise AgentLabProjectValidationError("项目读取参数无效。")
            if set(value) & {"appId", "appVersion", "appCallId"}:
                if not value.get('appId') or set(value) & {"artifactId", "artifactRevision", "materialSetId"}:
                    raise AgentLabProjectValidationError("应用读取需要 appId；请与成果或材料读取分别执行。")
                observed = self.apps.read({'projectId':project_id,'appId':value['appId'],
                    **({'version':value['appVersion']} if 'appVersion' in value else {}),
                    **({'callId':value['appCallId']} if 'appCallId' in value else {})})
                observed['version'] = {key:item for key,item in observed['version'].items() if key != 'html'}
                observed['calls'] = [{key:item for key,item in call.items() if key != 'result'} for call in observed.get('calls',[])]
                return {'ok':True,'projectId':project_id,'application':observed}
            observed = self.read({"projectId": project_id, **value})
            # The UI owns the user's project catalog. A bound Guide receives
            # only its current project, including in the response summaries.
            observed['items'] = [item for item in observed.get('items', []) if item['projectId'] == project_id]
            return observed
        if operation in {"execution_read", "execution_command"}:
            return self._execution(project, operation, value)
        if operation != "command" or value.get("action") in {"create", "import_history", "ensure_guide", "knowledge"}:
            raise AgentLabProjectValidationError("此操作不属于当前项目的成果工作。")
        if "projectId" in value:
            raise AgentLabProjectValidationError("项目身份由当前 Agent 绑定，不能由工具参数替换。")
        command_input = value.get("input")
        if value.get("action") == "import_materials" and isinstance(command_input, Mapping) and "path" in command_input:
            requested_path = command_input["path"]
            if not isinstance(requested_path, str):
                raise AgentLabProjectValidationError("本地材料路径无效。")
            path = Path(requested_path).expanduser().resolve()
            roots = [Path(str(root)).expanduser().resolve() for root in session.get("workspaceRoots", [])]
            if not any(path.is_relative_to(root) for root in roots):
                raise AgentLabProjectValidationError("此材料位于当前 Session 的工作空间之外，请通过项目接入添加。")
        return self.command({"projectId": project_id, **value})

    def _execution(self, project: dict[str, Any], operation: str, value: dict[str, Any]) -> dict[str, Any]:
        fields = {"bindingId"} if operation == "execution_read" else {"bindingId", "action", "expectedRevision", "clientRequestId", "input"}
        if set(value) - fields:
            raise AgentLabProjectValidationError("执行操作参数无效。")
        binding = next((item for item in project["bindings"] if item["bindingId"] == value.get("bindingId")), None)
        if binding is None:
            raise AgentLabProjectValidationError("执行绑定不属于当前项目。")
        if binding["adapterId"] == "scene.trial" and binding["ownerRef"]["kind"] == "scene_trial":
            if operation != "execution_read" or self.read_trials is None:
                raise AgentLabProjectValidationError("请在项目运行页选择本次场景配置并启动验证。")
            observed = self.read_trials()
            scene_id = binding["ownerRef"]["id"]
            return {"ok": True, "binding": binding, "execution": {
                "schemaVersion": observed["schemaVersion"],
                "registered": scene_id in observed.get("registeredSceneIds", []),
                "jobs": [job for job in observed.get("jobs", []) if job.get("sceneId") == scene_id],
            }}
        if binding["adapterId"] not in {"golden.context_qa", "golden.knowledge_qa"} or binding["ownerRef"]["kind"] != "golden_suite":
            raise AgentLabProjectValidationError("此绑定的执行适配器尚未接入。")
        suite_id = binding["ownerRef"]["id"]
        if operation == "execution_read" and self.read_golden:
            observed = self.read_golden({"suiteId": suite_id})
            suite = observed.get("suite")
            if not isinstance(suite, Mapping) or suite.get("suiteId") != suite_id:
                raise AgentLabProjectValidationError("绑定的执行记录暂未读到。")
            if binding["adapterId"] == "golden.knowledge_qa":
                suite = dict(suite)
                suite["holdoutCaseCount"] = sum(item.get("split") == "holdout" for item in suite.get("cases", []))
                suite["cases"] = [item for item in suite.get("cases", []) if item.get("split") == "development"]
                # Frontend standards remain inspectable by the user; the Guide
                # cannot turn held-out answers or old draft results into tuning
                # inputs through this execution-read tool.
                suite["jobs"] = [{key: value for key, value in job.items() if key != "result"} for job in suite.get("jobs", [])]
                suite["holdoutReferencesVisible"] = False
            # The legacy catalog can include unrelated suites; a project Tool
            # returns only its own binding, never that cross-project catalog.
            return {"ok": True, "binding": binding, "execution": {"ok": True, "suite": suite, "items": [suite]}}
        # Model-written text cannot manufacture a human review or sample label.
        # Those actions remain direct user interactions in the standards view.
        if operation == "execution_command" and self.command_golden:
            if value.get("action") not in {"draft", "judge_config", "calibrate", "freeze", "experiment", "cancel", "resume"}:
                raise AgentLabProjectValidationError("此执行操作需要在对应成果界面完成，不能由模型生成审核标签。")
            return self.command_golden({key: item for key, item in {**value, "suiteId": suite_id}.items() if key != "bindingId"})
        raise AgentLabProjectValidationError("当前运行环境没有接入此执行服务。")
