"""Portable launcher for an unchanged copy of the project docking runner."""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('p2x4_runner', ROOT / 'scripts/21_run_single_compound.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.MEEKO_PREPARE = Path(shutil.which('mk_prepare_ligand.py') or '')
runner.MEEKO_EXPORT = Path(shutil.which('mk_export.py') or '')
runner.VINA = Path(os.environ.get('P2X4_LIVE_VINA') or shutil.which('vina') or ROOT / 'bin/vina')
if __name__ == '__main__':
    runner.main()
