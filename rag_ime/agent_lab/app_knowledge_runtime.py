"""Frozen App search adapter; shipped with the unchanged KnowledgeStore owner.

Only a package-local cache is writable. This module never calls a Provider.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import types
from pathlib import Path

_LOCK = threading.RLock()
_READY: dict[str, tuple[object, dict]] = {}


def materialize(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, text in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in {'knowledge', 'knowledge_owner', 'knowledge_runtime.py'}:
            raise ValueError('知识库应用资源路径无效。')
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise ValueError('知识库应用资源不能是符号链接。')
        if not path.exists():
            with path.open('x', encoding='utf-8') as out:
                os.chmod(path, 0o600)
                out.write(text)
        elif path.read_text(encoding='utf-8') != text:
            raise ValueError('冻结的知识库应用资源发生变化，请重新准备此版本。')


def _open(root: Path, knowledge: dict) -> tuple[object, dict]:
    path = root / knowledge['snapshotFile']
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 80 * 1024 * 1024:
        raise ValueError('知识库应用缺少完整的检索快照。')
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != knowledge['snapshotSha256']:
        raise ValueError('知识库快照与此应用版本不一致。')
    key = str(root.resolve()) + ':' + knowledge['snapshotSha256']
    with _LOCK:
        if key in _READY:
            return _READY[key]
        snapshot = json.loads(encoded)
        owner_root = root / 'knowledge_owner'
        names = ('store.py', 'models.py', 'permissions.py')
        source_hash = hashlib.sha256(b''.join((owner_root / name).read_bytes() for name in names)).hexdigest()
        if source_hash != knowledge['ownerSha256']:
            raise ValueError('冻结的 Knowledge 检索组件发生变化。')
        namespace = 'paw_app_knowledge_' + source_hash
        if namespace not in sys.modules:
            package = types.ModuleType(namespace)
            package.__path__ = [str(owner_root)]
            sys.modules[namespace] = package
        store_type = importlib.import_module(namespace + '.store').KnowledgeStore
        cache_parent = root / '.knowledge-cache'
        cache_parent.mkdir(mode=0o700, exist_ok=True)
        cache = cache_parent / knowledge['snapshotSha256']
        if not (cache / 'ready').is_file():
            temporary = Path(tempfile.mkdtemp(prefix='building-', dir=cache_parent))
            try:
                store = store_type(temporary / 'knowledge.sqlite')
                store.import_search_snapshot(snapshot)
                with store.connection() as connection:
                    connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                (temporary / 'ready').write_text(knowledge['snapshotSha256'])
                try:
                    temporary.rename(cache)
                except FileExistsError:
                    if not (cache / 'ready').is_file():
                        raise ValueError('知识库应用缓存未完成，请稍后重试。')
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        store = store_type(cache / 'knowledge.sqlite')
        snapshot.pop('chunks', None)
        snapshot.pop('documents', None)
        if len(_READY) >= 4:
            _READY.pop(next(iter(_READY)))
        _READY[key] = (store, snapshot)
        return _READY[key]


def retrieve(root: Path, knowledge: dict, values: dict) -> dict:
    query = values.get(knowledge['queryField'])
    if not isinstance(query, str) or not query.strip() or len(query) > 20000:
        raise ValueError('请输入有效的知识库问题。')
    profile = knowledge['profile']
    if profile['mode'] != 'lexical' or profile['rerank']:
        raise ValueError('此独立检索包只支持已冻结的关键词配置。')
    store, snapshot = _open(root, knowledge)
    top_k = profile['topK']
    multiplier = snapshot['base']['retrievalConfig']['candidateMultiplier']
    hits = store.search(query, base_ids=[snapshot['base']['id']], limit=min(100, top_k * multiplier), agent_only=True)
    hits = [hit for hit in hits if hit.score >= profile['threshold']][:top_k]
    # Match KnowledgeLibraryService's single-library lexical final ordering.
    hits.sort(key=lambda hit: (-hit.score, hit.base_id, hit.chunk_id))
    sources, remaining = [], profile['contextChars']
    for hit in hits:
        if remaining <= 0:
            break
        source = snapshot['sources'][hit.document_id]
        content = hit.content[:remaining]
        sources.append({**source, 'chunkId': hit.chunk_id, 'text': content, 'score': hit.score})
        remaining -= len(content)
    selected = {source['chunkId'] for source in sources}
    retrieval_hits = [{**snapshot['sources'][hit.document_id], 'chunkId':hit.chunk_id,
                       'preview':hit.content[:180], 'score':hit.score, 'usedInContext':hit.chunk_id in selected} for hit in hits]
    return {'query': query, 'sources': sources, 'retrievalHits':retrieval_hits, 'snapshotSha256': knowledge['snapshotSha256'],
            'indexId': knowledge['sourceIndexId'], 'profile': profile,
            'documentCount': knowledge['documentCount'], 'retrievedChunks': len(hits),
            'contextChars': sum(len(source['text']) for source in sources), 'modelCalls': 0}


def retrieval_result(value: dict) -> dict:
    sources = value['sources']
    text = '\n\n'.join(f"[{row['sourceId']}] {row['title']}\n{row['text']}\n{row['uri']}" for row in sources)
    return {'text': text or '未检索到符合条件的知识库证据。', 'sources': sources,
            'knowledge': {key: item for key, item in value.items() if key != 'sources'},
            'usage': {'calls': 0, 'source': 'local_knowledge_retrieval'}, 'transport': 'knowledge_snapshot'}
