from copy import deepcopy

import pytest
import serial
from fastapi.testclient import TestClient

from pygmalion import config, storage
from pygmalion.api.app import WEB_DIST_DIR, create_app
from pygmalion.machine import grbl
from pygmalion.writing import prepare as preparation


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    original = deepcopy(config.CONFIG)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "data" / "poems.db")
    monkeypatch.setattr(preparation, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(grbl, "BACKUP_DIR", tmp_path / "backups")
    config.CONFIG.clear()
    config.CONFIG.update(deepcopy(config.DEFAULTS))
    storage.init_db()
    yield tmp_path
    config.CONFIG.clear()
    config.CONFIG.update(original)


@pytest.fixture
def client(isolated_runtime):
    app = create_app(WEB_DIST_DIR, dry_run=True)
    with TestClient(app) as session:
        yield session


@pytest.fixture(autouse=True)
def font_dataset_runtime(tmp_path, monkeypatch):
    """测试用最小笔画数据集，不依赖未跟踪的真实字库。"""
    from datasets import Dataset

    from pygmalion.servicer import system as api
    from pygmalion.writing import canvas, document

    monkeypatch.delenv("PYGMALION_FONTS_DIR", raising=False)
    root = tmp_path / "font-runtime"
    directory = root / "model-bin" / "cjk-medians"
    directory.mkdir(parents=True)
    chars = (
        "甲乙丙空山新雨后，天气晚来秋。山居秋暝陈雨诗一二三年月日书于赠天地玄黄宇宙洪荒"
    )
    Dataset.from_list(
        [
            {"char": ch, "lengths": [2], "x": [-4000, 4000], "y": [-2000, 2000]}
            for ch in dict.fromkeys(chars)
        ]
    ).to_parquet(directory / "train.parquet")
    monkeypatch.setattr(preparation, "ROOT", root)
    monkeypatch.setattr(document, "ROOT", root)
    monkeypatch.setattr(canvas, "ROOT", root)
    monkeypatch.setattr(api, "ROOT", root)


@pytest.fixture(autouse=True)
def forbid_physical_serial(monkeypatch):
    """All device tests must explicitly install a fake; real ports are never opened."""
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(str(args[0] if args else kwargs.get("port", "unspecified")))
        raise AssertionError("Physical serial access is forbidden in tests")

    monkeypatch.setattr(serial, "Serial", forbidden)
    yield
    assert not attempts, f"Unmocked physical serial access attempted: {attempts}"
