import json
from pathlib import Path

from engine.cli import main
from engine.config import load_config


def test_validate_ok(project_dir, capsys):
    assert main(["validate", str(project_dir)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 17 nodes"


def test_validate_reports_every_error(project_dir, capsys):
    data = json.loads((project_dir / "manifest.json").read_text())
    data["nodes"][1]["depends_on"] = []
    (project_dir / "manifest.json").write_text(json.dumps(data))
    assert main(["validate", str(project_dir)]) == 1
    assert "ERROR: v1.s01.keyframe: input references @refs.product_hero" in capsys.readouterr().err


def test_dry_run_and_estimate(project_dir, capsys):
    assert main(["dry-run", str(project_dir)]) == 0
    out = capsys.readouterr().out
    assert "RUN    refs.product_hero" in out
    assert out.strip().endswith("17 to run, 0 cached, estimated cost: $0.00")
    assert main(["estimate", str(project_dir), "--only", "refs.*"]) == 0
    assert capsys.readouterr().out.strip() == "estimated cost: $0.00 for 1 nodes"


def test_run_status_revise_rollback(project_dir, capsys):
    assert main(["run", str(project_dir)]) == 0
    assert capsys.readouterr().out.strip() == "ran 17, cached 0, failed 0, needs_review 0, blocked 0"

    assert main(["status", str(project_dir)]) == 0
    status = capsys.readouterr().out
    assert "refs.product_hero" in status and "done" in status and "v1" in status

    assert main(["revise", str(project_dir), "v1.vo.l01", "--json", '{"inputs": {"text": "Take two"}}']) == 0
    out = capsys.readouterr().out
    assert "revised v1.vo.l01" in out
    assert "ran 4, cached 13" in out

    assert main(["rollback", str(project_dir), "v1.vo.l01", "1"]) == 0
    assert "restored from v1 as v3" in capsys.readouterr().out


def test_errors_exit_nonzero_with_message(project_dir, capsys):
    assert main(["rollback", str(project_dir), "v1.vo.l01", "9"]) == 1
    assert "ERROR:" in capsys.readouterr().err
    assert main(["revise", str(project_dir), "v1.vo.l01", "--json", '{"type": "image"}']) == 1
    assert "cannot revise" in capsys.readouterr().err


def test_example_config_loads():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
    assert cfg.routing["video"].provider == "mock"
