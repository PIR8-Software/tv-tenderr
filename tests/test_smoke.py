from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repo_layout_smoke():
    assert (ROOT / "README.md").exists()
    assert (ROOT / "requirements.txt").exists()
    assert (ROOT / "backend.py").exists()
    assert (ROOT / "tests").is_dir()
