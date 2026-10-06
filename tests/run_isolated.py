"""Run the backend suite from a credential/data-free source copy, never the live .env."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='tv-isolated-') as directory:
    dest = Path(directory)
    for name in ('backend.py', 'release.sh', 'requirements.txt'):
        shutil.copy2(root/name, dest/name)
    for name in ('tests', 'web', 'android/app/src'):
        shutil.copytree(root/name, dest/name, ignore=shutil.ignore_patterns('__pycache__'))
    environment = {k: v for k, v in os.environ.items() if not k.startswith(('RADARR_', 'SONARR_', 'PLEX_', 'TMDB_', 'TV_TENDERR_', 'BACKEND_'))}
    environment['PYTHONPATH'] = str(dest)
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=dest, env=environment, capture_output=True, text=True)
    output = result.stdout + result.stderr
    evidence = root.parent/'tv-tenderr-audit/evidence/backend-tests.log'
    evidence.parent.mkdir(exist_ok=True, parents=True)
    evidence.write_text(output)
    print(output)
    sys.exit(result.returncode)
