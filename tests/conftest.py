import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """Point the DB and media folder at a temp dir."""
    from common import config
    import db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "agent.db")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    return tmp_path, db.connect(tmp_path / "agent.db")
