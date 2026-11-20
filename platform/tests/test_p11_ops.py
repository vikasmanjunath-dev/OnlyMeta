"""P11: operator CLI - init, onboard/offboard, backup/restore, doctor, .env loader."""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from saas import envfile  # noqa: E402
from tools import ctl  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    t = tmp_path / "tenants.yaml"
    t.write_text((ROOT / "contracts/tenants.yaml").read_text())
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(ctl, "ENV", tmp_path / ".env")
    monkeypatch.setattr(ctl, "TENANTS", t)
    monkeypatch.setattr(ctl, "DATA", data)
    monkeypatch.setattr(ctl, "RUN", data / "run")
    return tmp_path


def run(*a):
    return ctl.main(list(a))


def mkdb(p, rows=3):
    c = sqlite3.connect(p)
    c.execute("create table t(x)")
    c.executemany("insert into t values(?)", [(i,) for i in range(rows)])
    c.commit(), c.close()


def test_envfile_parse_and_precedence(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nexport B=\"two words\"\nC='x'\nbad line\nD=a=b\n")
    assert envfile.parse(f.read_text()) == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}
    monkeypatch.setenv("A", "real")
    monkeypatch.delenv("B", raising=False)
    envfile.load(f)
    assert os.environ["A"] == "real" and os.environ["B"] == "two words"
    monkeypatch.delenv("B"), monkeypatch.delenv("C", raising=False), monkeypatch.delenv("D", raising=False)


def test_init_generates_strong_secrets_mode_600(env):
    assert run("init") == 0
    v = ctl.read_env()
    assert {"PSEUDO_KEY", "METRICS_TOKEN", "KEY_ALPHA", "USER_BETA_VIEWER_PASSWORD"} <= set(v)
    assert all(len(x) >= 24 for x in v.values()) and len(set(v.values())) == len(v)
    assert (ctl.ENV.stat().st_mode & 0o777) == 0o600
    before = dict(v)
    run("init")
    assert ctl.read_env() == before                          # idempotent: keeps good secrets
    run("init", "--force")
    assert ctl.read_env()["KEY_ALPHA"] != before["KEY_ALPHA"]


def test_init_replaces_placeholder_secrets(env):
    ctl.ENV.write_text("KEY_ALPHA=change-me-long-random\nPSEUDO_KEY=" + "p" * 30 + "\n")
    run("init")
    v = ctl.read_env()
    assert "change-me" not in v["KEY_ALPHA"] and v["PSEUDO_KEY"] == "p" * 30


def test_onboard_adds_tenant_visible_to_saas_and_collector(env, monkeypatch, capsys):
    run("init")
    assert run("onboard", "gamma", "--region", "us", "--tz", "America/New_York") == 0
    ts = ctl.tenants()
    assert ts["tenant-gamma"]["region"] == "us" and ts["tenant-gamma"]["key_env"] == "KEY_GAMMA"
    assert len(ts) == 3 and "tenant-alpha" in ts
    assert {"KEY_GAMMA", "USER_GAMMA_PASSWORD", "USER_GAMMA_VIEWER_PASSWORD"} <= set(ctl.read_env())
    assert "# SaaS stores one SQLite file" in ctl.TENANTS.read_text()       # comments survive
    # the real settings loaders accept the new tenant
    monkeypatch.setattr("saas.settings.ROOT", env, raising=False)
    (env / "contracts").mkdir()
    (env / "contracts/tenants.yaml").write_text(ctl.TENANTS.read_text())
    (env / "contracts/thresholds.yaml").write_text((ROOT / "contracts/thresholds.yaml").read_text())
    for k, v in ctl.read_env().items():
        monkeypatch.setenv(k, v)
    from saas.settings import load_settings
    s = load_settings(data_dir=env / "data")
    assert "gamma-admin" in s.users and s.keys[ctl.read_env()["KEY_GAMMA"]] == "tenant-gamma"


@pytest.mark.parametrize("args,msg", [
    (["Bad", "--region", "us"], "name must"), (["x", "--region", "us"], "name must"),
    (["alpha", "--region", "us"], "already exists"), (["gamma", "--region", "U"], "region must"),
    (["gamma", "--region", "us", "--tz", "Mars/Base"], "timezone")])
def test_onboard_rejects_bad_input(env, capsys, args, msg):
    assert run("onboard", *args) == 1
    assert msg in capsys.readouterr().out
    assert len(ctl.tenants()) == 2                          # nothing written on failure


def test_offboard_removes_tenant_and_secrets_keeps_others(env):
    run("init"), run("onboard", "gamma", "--region", "us")
    assert run("offboard", "gamma") == 0
    assert set(ctl.tenants()) == {"tenant-alpha", "tenant-beta"}
    assert "KEY_GAMMA" not in ctl.read_env() and "KEY_ALPHA" in ctl.read_env()
    assert "# SaaS stores one SQLite file" in ctl.TENANTS.read_text()


def test_offboard_unknown_and_last(env, capsys):
    assert run("offboard", "nope") == 1
    run("offboard", "beta")
    assert run("offboard", "alpha") == 1 and "last tenant" in capsys.readouterr().out


def test_backup_restore_roundtrip(env, capsys):
    mkdb(ctl.DATA / "saas_in.db", 5), mkdb(ctl.DATA / "collector_alpha.db", 2)
    (ctl.DATA / "saas.kek").write_bytes(b"k" * 32)
    capsys.readouterr()
    assert run("backup", "--out", str(env / "bk")) == 0
    arc = json.loads(capsys.readouterr().out)["backup"]
    assert (Path(arc).stat().st_mode & 0o777) == 0o600
    for f in ctl.DATA.glob("*"):
        f.unlink()
    assert run("restore", arc) == 0
    assert sqlite3.connect(ctl.DATA / "saas_in.db").execute("select count(*) from t").fetchone()[0] == 5
    assert (ctl.DATA / "saas.kek").read_bytes() == b"k" * 32


def test_restore_refuses_overwrite_and_tampering(env, capsys):
    mkdb(ctl.DATA / "saas_in.db"), capsys.readouterr()
    run("backup", "--out", str(env / "bk"))
    arc = Path(json.loads(capsys.readouterr().out)["backup"])
    assert run("restore", str(arc)) == 1 and "overwrite" in capsys.readouterr().out
    assert run("restore", str(arc), "--force") == 0
    capsys.readouterr()
    import tarfile
    bad = env / "bad.tgz"
    with tarfile.open(arc) as src, tarfile.open(bad, "w:gz") as dst:
        for m in src.getmembers():
            f = src.extractfile(m)
            data = f.read()
            if m.name == "saas_in.db":
                data = data[:-1] + b"\x00" if data[-1] else data[:-1] + b"\x01"
            import io
            m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    ctl.DATA.joinpath("saas_in.db").unlink()
    assert run("restore", str(bad)) == 1 and "checksum" in capsys.readouterr().out
    assert not (ctl.DATA / "saas_in.db").exists()           # nothing half-restored


def test_restore_rejects_path_traversal(env, capsys):
    import io
    import tarfile
    evil = env / "evil.tgz"
    with tarfile.open(evil, "w:gz") as t:
        m = tarfile.TarInfo("../escape.db")
        m.size = 1
        t.addfile(m, io.BytesIO(b"x"))
    assert run("restore", str(evil)) == 1 and "unsafe" in capsys.readouterr().out
    assert not (env.parent / "escape.db").exists()


def test_backup_is_consistent_while_writing(env):
    p = ctl.DATA / "saas_in.db"
    mkdb(p, 10)
    w = sqlite3.connect(p)
    w.execute("pragma journal_mode=wal").fetchone()
    w.execute("insert into t values(99)")
    w.commit()
    run("backup", "--out", str(env / "bk"))
    arc = next((env / "bk").glob("*.tgz"))
    import tarfile
    with tarfile.open(arc) as t:
        t.extract("saas_in.db", env / "x", filter="data")
    assert sqlite3.connect(env / "x/saas_in.db").execute("select count(*) from t").fetchone()[0] == 11  # WAL content included
    w.close()


def test_doctor_flags_problems_then_passes(env, capsys):
    assert run("doctor") == 2
    out = json.loads(capsys.readouterr().out)
    assert any(c["check"] == ".env present" and not c["ok"] for c in out["checks"])
    run("init"), capsys.readouterr()
    mkdb(ctl.DATA / "saas_in.db")
    assert run("doctor") == 0
    capsys.readouterr()
    ctl.DATA.joinpath("bad.db").write_bytes(b"not a database" * 50)
    assert run("doctor") == 2
    assert any(c["check"] == "db bad.db" and not c["ok"] for c in json.loads(capsys.readouterr().out)["checks"])


def test_doctor_catches_loose_env_mode(env, capsys):
    run("init"), capsys.readouterr()
    os.chmod(ctl.ENV, 0o644)
    assert run("doctor") == 2
    assert any(c["check"] == ".env mode 600" and not c["ok"] for c in json.loads(capsys.readouterr().out)["checks"])
