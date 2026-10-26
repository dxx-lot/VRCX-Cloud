"""A modular release must contain its imports/assets, hashes and no account data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'scripts' / 'build-release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_release_has_complete_modules_and_does_not_package_instance_data(tmp_path):
    out = tmp_path / 'release.tar.gz'
    manifest = builder.build(out)
    with tarfile.open(out) as archive:
        names = set(archive.getnames())
        assert {'web.py', 'vrc_watch.py', 'services/routes.py', 'services/cache.py',
                'templates/index.html', 'static/core/runtime.js', 'static/bootstrap.js',
                'domain/favorites.py', 'domain/ws_events.py', 'domain/backup.py', 'release-manifest.json'} <= names
        assert not any(p.endswith(('.db', '.token', '.secret')) or Path(p).name in {'config.json','auth-ui.json'} for p in names)
        for name, checksum in manifest['files'].items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == checksum
        for member in archive.getmembers():
            assert not member.name.startswith('/') and '..' not in Path(member.name).parts
            archive.extract(member, path=tmp_path / 'runtime')
    runtime = tmp_path / 'runtime'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    code = "import web, favorites, ws_events, backup; assert web.PAGE_HTML; assert web.ApiRouter(vars(web)).allowed('POST'); assert web._ASSETS.resolve('core/runtime.js')"
    completed = subprocess.run([sys.executable, '-c', code], cwd=runtime, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
