import os


def test_smoke_imports():
    assert os.path.exists("README.md")
    assert os.path.exists("requirements.txt")
