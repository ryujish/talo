import io
import json


def test_headless_replay_after_restart(tmp_path, monkeypatch, capsys):
    from talo.service import serve
    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    req = {"version": 1, "id": "session-1", "method": "session.start", "cwd": str(root), "params": {"title": "첫 작업"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(req) + "\n"))
    assert serve() == 0
    first = json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(req) + "\n"))
    assert serve() == 0
    second = json.loads(capsys.readouterr().out)
    assert first["result"]["session_id"] == second["result"]["session_id"]
    req["params"]["title"] = "다른 작업"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(req) + "\n"))
    serve()
    assert json.loads(capsys.readouterr().out)["type"] == "error"


def test_health_and_bad_request(capsys, monkeypatch):
    from talo.service import serve
    monkeypatch.setattr("sys.stdin", io.StringIO('{"version":1,"id":"h","method":"health"}\nnot-json\n'))
    serve()
    lines = [json.loads(s) for s in capsys.readouterr().out.splitlines()]
    assert lines[0]["result"]["transport"] == "stdio"
    assert lines[1]["type"] == "error"
