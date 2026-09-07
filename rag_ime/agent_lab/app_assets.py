"""Immutable large App resources, kept outside frequently polled SQLite rows."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path


def asset_root(db_path: Path, key: str) -> Path:
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('应用资源标识无效。')
    root = db_path.parent / 'lab-app-packages' / key
    if root.is_symlink():
        raise ValueError('应用资源目录不可用。')
    return root


def freeze_assets(db_path: Path, version: dict, exporter) -> None:
    from .app_knowledge_runtime import materialize
    identity = {key: version[key] for key in ('appId', 'version', 'contentHash')}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = asset_root(db_path, key)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(tempfile.mkdtemp(prefix='preparing-', dir=root.parent))
    try:
        materialize(temporary, version['resourceFiles'])
        manifest = [{'path': name, 'byteSize': len(text.encode()),
                     'sha256': hashlib.sha256(text.encode()).hexdigest()}
                    for name, text in version['resourceFiles'].items()]
        exports = {}
        for target in ('paw', 'standalone'):
            filename, archive = exporter(version, target)
            path = temporary / (target + '.zip')
            path.write_bytes(archive)
            os.chmod(path, 0o600)
            exports[target] = {'filename': filename, 'mimeType': 'application/zip',
                               'byteSize': len(archive), 'sha256': hashlib.sha256(archive).hexdigest()}
        receipt = json.dumps({'resources': manifest, 'exports': exports}, sort_keys=True)
        (temporary / 'ready.json').write_text(receipt)
        if root.exists():
            if (root / 'ready.json').read_text() != receipt:
                raise ValueError('应用冻结资源与现有版本不一致。')
        else:
            temporary.rename(root)
        version.update(assetKey=key, resourceManifest=manifest, exports=exports)
        version.pop('resourceFiles')
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def download_asset(db_path: Path, version: dict, target: str) -> dict:
    record = version['exports'][target]
    path = asset_root(db_path, version['assetKey']) / (target + '.zip')
    if path.is_symlink() or not path.is_file() or path.stat().st_size != record['byteSize']:
        raise ValueError('此版本的应用包缺失或不完整，请重新准备应用。')
    archive = path.read_bytes()
    if hashlib.sha256(archive).hexdigest() != record['sha256']:
        raise ValueError('此版本的应用包发生变化，请重新准备应用。')
    return {**record, 'base64': base64.b64encode(archive).decode()}
