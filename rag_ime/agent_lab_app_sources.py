"""Freeze explicitly selected application sources; never run them at intake."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .agent_lab_project_artifacts import _text
from .agent_lab_projects import AgentLabProjectValidationError


SOURCE_SCHEMA = 'paw.lab-app-source.v1'
EXPORT_RECIPE_VERSION = 'paw.lab-app-export.v2'
_ACTION_ID = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
_BLOCKED_FILES = {'auth.json', 'credentials.json', 'pi-providers.json', 'models.json', 'package-lock.json'}
_EXPORT_FILES = {'app.json', 'app.py', 'readme.md', 'paw-app.json'}


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 500 or '\\' in value:
        raise AgentLabProjectValidationError('应用文件需要相对路径。')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'.', '..'} or part.startswith('.') for part in value.split('/')):
        raise AgentLabProjectValidationError('应用文件不能越过源码目录或包含隐藏文件。')
    if path.name.lower() in _BLOCKED_FILES or path.suffix.lower() in {'.env', '.pem', '.key', '.sqlite', '.db'}:
        raise AgentLabProjectValidationError('此文件属于凭据、本机配置或数据库，不能打包到应用。')
    return path.as_posix()


def _read(root: Path, value: Any) -> tuple[str, str]:
    path = _relative(value)
    candidate = root
    for part in PurePosixPath(path).parts:
        candidate /= part
        if candidate.is_symlink(): raise AgentLabProjectValidationError('应用源文件不能是符号链接。')
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        raise AgentLabProjectValidationError(f'应用文件不存在：{path}')
    if candidate.stat().st_size > 500_000: raise AgentLabProjectValidationError(f'应用文件超过 500 KB：{path}')
    try: content = candidate.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc: raise AgentLabProjectValidationError(f'应用文件不能作为 UTF-8 文本读取：{path}') from exc
    if '\0' in content: raise AgentLabProjectValidationError('应用文件包含二进制内容。')
    return path, content


def validate_input_schema(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - {'type','properties','required','additionalProperties'} or value.get('type') != 'object':
        raise AgentLabProjectValidationError('应用输入 schema 需要一个对象。')
    properties = value.get('properties')
    if not isinstance(properties, dict) or len(properties) > 40:
        raise AgentLabProjectValidationError('应用输入最多包含 40 个字段。')
    for key, field in properties.items():
        if not _ACTION_ID.fullmatch(key) or not isinstance(field, dict) or set(field) - {'type','title','description','enum','maxLength','minimum','maximum'}:
            raise AgentLabProjectValidationError('应用输入字段格式无效。')
        kind = field.get('type')
        if kind not in {'string','number','integer','boolean'}: raise AgentLabProjectValidationError('应用字段支持文本、数字、整数和布尔值。')
        for name in {'title','description'} & field.keys(): _text(field[name], '输入说明', 2000)
        if 'maxLength' in field and (kind != 'string' or type(field['maxLength']) is not int or not 1 <= field['maxLength'] <= 24_000):
            raise AgentLabProjectValidationError('文本长度上限无效。')
        for name in {'minimum','maximum'} & field.keys():
            if kind not in {'number','integer'} or type(field[name]) not in {int,float} or not float('-inf') < field[name] < float('inf'):
                raise AgentLabProjectValidationError('数字范围无效。')
        if 'enum' in field:
            choices = field['enum']
            if kind != 'string' or not isinstance(choices, list) or not 1 <= len(choices) <= 100 or any(not isinstance(item,str) for item in choices):
                raise AgentLabProjectValidationError('可选值需要文本列表。')
    required = value.get('required', [])
    if not isinstance(required, list) or any(not isinstance(item,str) for item in required) or set(required) - properties.keys():
        raise AgentLabProjectValidationError('必填字段需要属于当前输入。')
    return {'type':'object','properties':copy.deepcopy(properties),'required':required,'additionalProperties':False}


def freeze_source(workspace: Path, directory: str, default_model: dict[str,str]) -> dict:
    workspace = workspace.resolve(strict=True)
    directory = _relative(directory)
    root = workspace
    for part in PurePosixPath(directory).parts:
        root /= part
        if root.is_symlink(): raise AgentLabProjectValidationError('应用目录不能是符号链接。')
    if not root.is_dir() or not root.resolve().is_relative_to(workspace): raise AgentLabProjectValidationError('应用源码需要位于此项目的执行目录内。')
    root = root.resolve()
    _, encoded = _read(root, 'app.json')
    try: value = json.loads(encoded)
    except ValueError as exc: raise AgentLabProjectValidationError('app.json 不是有效 JSON。') from exc
    fields = {'schemaVersion','title','description','html','skill','context','actions','model'}
    if not isinstance(value, dict) or set(value) - fields or value.get('schemaVersion') != SOURCE_SCHEMA:
        raise AgentLabProjectValidationError('app.json 需要 paw.lab-app-source.v1 格式。')
    title = _text(value.get('title'), '应用名称', 100)
    description = _text(value.get('description', ''), '应用说明', 3000, empty=True)
    context = value.get('context', [])
    if not isinstance(context, list) or len(context) > 32: raise AgentLabProjectValidationError('应用材料最多 32 份。')
    files = dict(_read(root, path) for path in [value.get('html'), value.get('skill'), *context])
    if any(path.lower() in _EXPORT_FILES for path in files):
        raise AgentLabProjectValidationError('app.json、app.py、README.md 和 paw-app.json 是导出运行器的保留文件名，请将业务材料换一个文件名。')
    if not str(value['html']).endswith('.html') or not str(value['skill']).endswith('SKILL.md'):
        raise AgentLabProjectValidationError('应用需要 HTML 入口和 SKILL.md 方法文件。')
    if sum(len(text.encode()) for text in files.values()) > 2_000_000:
        raise AgentLabProjectValidationError('应用源文件合计超过 2 MB。')
    actions = value.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
        raise AgentLabProjectValidationError('应用需要 1–16 项声明的操作。')
    normalized = []
    for action in actions:
        if not isinstance(action, dict) or set(action) != {'id','title','prompt','inputSchema'} or not isinstance(action['id'],str) or not _ACTION_ID.fullmatch(action['id']):
            raise AgentLabProjectValidationError('应用操作需要 id、title、prompt 和 inputSchema。')
        normalized.append({'id':action['id'],'title':_text(action['title'],'操作名称',120),
                           'prompt':_text(action['prompt'],'操作方法',30_000),'inputSchema':validate_input_schema(action['inputSchema'])})
    if len({item['id'] for item in normalized}) != len(normalized): raise AgentLabProjectValidationError('应用操作标识不能重复。')
    model = value.get('model', default_model)
    if not isinstance(model, dict) or set(model) - {'provider','model','thinkingLevel','prompt'}:
        raise AgentLabProjectValidationError('应用模型配置无效。')
    model = {key:_text(model.get(key, default_model.get(key)), '模型配置', 240) for key in ['provider','model','thinkingLevel']}
    if model['thinkingLevel'] not in {'off','minimal','low','medium','high','xhigh','max'}:
        raise AgentLabProjectValidationError('应用推理强度无效。')
    spec = {'schemaVersion':SOURCE_SCHEMA,'title':title,'description':description,'html':_relative(value['html']),
            'skill':_relative(value['skill']),'context':[_relative(path) for path in context],'actions':normalized,'model':model}
    runtime = Path(__file__).with_name('agent_lab_app_runtime.py').read_text(encoding='utf-8')
    digest = hashlib.sha256(json.dumps({'spec':spec,'files':files,'runtimeSource':runtime,'exportRecipeVersion':EXPORT_RECIPE_VERSION},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'spec':spec,'files':files,'runtimeSource':runtime,'runtimeSha256':hashlib.sha256(runtime.encode()).hexdigest(),
            'contentHash':digest,'sourceDirectory':directory,'exportRecipeVersion':EXPORT_RECIPE_VERSION}


def export_zip(version: dict, target: str) -> tuple[str, bytes]:
    if target not in {'standalone','paw'}: raise AgentLabProjectValidationError('不支持此导出目标。')
    spec, files = version['spec'], dict(version['files'])
    files['app.json'] = json.dumps(spec, ensure_ascii=False, indent=2)+'\n'
    files['app.py'] = version['runtimeSource']
    files['README.md'] = f"""# {spec['title']}

{spec['description']}

这是独立可运行的应用源码包，使用 Python 3.10+ 标准库，不需要 PAW 后端。

在此目录运行 `python3 app.py`，打开终端输出的本机地址。
调用模型前，在当前终端设置 `APP_API_BASE_URL`（HTTPS、以 API v1 路径结尾）和
`APP_API_KEY`。不要把凭据写入源码。`APP_MODEL`、`APP_REASONING_EFFORT` 可选；
默认模型为 `{spec['model']['model']}`，推理强度 `{spec['model']['thinkingLevel']}`。
模型服务需要支持 OpenAI Chat Completions 协议。修改模型或方法后需要重新验证效果。

HTML 使用 `window.pawApp.invoke(actionId, input)`，返回包含 `text` 与 `usage` 的结果。
页面和输入结构属于此应用。SKILL.md 与材料均为此冻结版本的副本。
本版本只执行声明的文本生成操作；没有订单、支付、发货或其他外部业务写入接口。

运行地址默认仅为本机。调用输入与回执保存在本目录的 `.app-state.sqlite3`，文件权限为仅当前用户可读写。
请求按 requestId 持久去重；刷新或重启不会自动重放。未收到完成回执的旧调用保持“结果未确认”，
请先核对模型服务记录。浏览器在连接中断后再次提交同样的输入时，会核对原请求。
`window.pawApp.history()` 可读取最近 20 次调用，应用界面可据此恢复输入或结果。
默认最多同时运行 4 次调用，最多保留 5000 条记录；归档记录后可以开启新记录。
请保管好本机记录文件，不要把它与凭据一同发布。若用于正式服务，需要自行配置认证和部署环境。

源版本指纹：`{version['contentHash']}`。打包验证仅证明文件与运行合同，不代表业务质量。
"""
    if target == 'paw':
        files['paw-app.json'] = json.dumps({'schemaVersion':'paw.lab-app-package.v1','source':'app.json',
                                           'contentHash':version['contentHash'],'runtime':'pi-completion'},indent=2)+'\n'
        files['README.md'] += '\nPAW 应用包：本机可直接在 Lab 交付页添加至 PAW。迁移时将源码解压到另一 Lab 项目的执行目录，再让项目 Agent 准备这个应用。\n'
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path, text in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, text.encode())
    return f"lab-app-v{version['version']}-{target}.zip", output.getvalue()
