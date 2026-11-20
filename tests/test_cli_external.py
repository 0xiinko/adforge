import json

import yaml

from engine.cli import main
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA_CONFIG

HERO = "refs.product_hero"


def supply_file(d, n):
    f = d / f"{n['id']}{'.png' if n['type'] == 'image' else '.mp4'}"
    f.write_bytes(PNG_1X1 if n["type"] == "image" else b"clip")
    return f


def test_run_exits_3_while_awaiting(ellora_dir, capsys):
    assert main(["run", str(ellora_dir)]) == 3
    out = capsys.readouterr().out
    assert "ran 2, cached 0, failed 0, needs_review 0, blocked 0, awaiting 1" in out
    assert f"AWAITING {HERO}" in out


def test_external_lists_awaiting_nodes(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    capsys.readouterr()
    assert main(["external", str(ellora_dir), "--json"]) == 0
    [hero] = json.loads(capsys.readouterr().out)
    assert hero["id"] == HERO and hero["model"] == "ellora-image"
    assert main(["external", str(ellora_dir)]) == 0
    assert capsys.readouterr().out.startswith(HERO)


def test_external_with_nothing_awaiting(ellora_dir, capsys):
    assert main(["external", str(ellora_dir)]) == 0
    assert capsys.readouterr().out.strip() == "nothing awaiting external supply"


def test_supply_and_refuse(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    f = supply_file(ellora_dir, {"id": HERO, "type": "image"})
    assert main(["supply", str(ellora_dir), HERO, str(f), "--ref", "ellora://hero", "--id", "g1"]) == 0
    assert capsys.readouterr().out.strip().endswith(f"supplied {HERO} as v1")
    assert main(["run", str(ellora_dir)]) == 3
    capsys.readouterr()
    assert main(["supply", str(ellora_dir), "v1.s01.keyframe", "--refused", "content policy"]) == 0
    assert "v1.s01.keyframe marked needs_review (refused)" in capsys.readouterr().out
    assert main(["run", str(ellora_dir)]) == 1  # 1 wins over 3
    assert "ATTENTION v1.s01.keyframe" in capsys.readouterr().out


def test_supply_argument_errors(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    capsys.readouterr()
    assert main(["supply", str(ellora_dir), HERO]) == 1
    assert "supply needs a file and --ref" in capsys.readouterr().err
    f = supply_file(ellora_dir, {"id": HERO, "type": "image"})
    assert main(["supply", str(ellora_dir), HERO, str(f), "--failed", "x"]) == 1
    assert "not both" in capsys.readouterr().err
    assert main(["supply", str(ellora_dir), "v1.vo.l01", str(f), "--ref", "r"]) == 1
    assert "not routed to an external provider" in capsys.readouterr().err


def test_validate_and_dry_run_report_external_problems(ellora_dir, capsys):
    cfg = {**ELLORA_CONFIG, "routing": {"video": {"provider": "ellora", "model": "ellora-video"}}}
    (ellora_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    assert main(["validate", str(ellora_dir)]) == 1
    assert "ERROR: v1.s01.clip: input @v1.s01.keyframe is rendered locally" in capsys.readouterr().err
    assert main(["dry-run", str(ellora_dir)]) == 1


def test_dry_run_labels_external_nodes(ellora_dir, capsys):
    assert main(["dry-run", str(ellora_dir)]) == 0
    assert f"RUN    {HERO}" in capsys.readouterr().out
    main(["dry-run", str(ellora_dir)])
    assert "(external: supplied by Claude)" in capsys.readouterr().out


def test_full_claude_loop_finishes(ellora_dir, capsys):
    passes = 0
    while (code := main(["run", str(ellora_dir)])) == 3:
        passes += 1
        assert passes <= 4
        capsys.readouterr()
        assert main(["external", str(ellora_dir), "--json"]) == 0
        for n in json.loads(capsys.readouterr().out):
            if n["id"].endswith(".clip"):
                assert n["external_inputs"]["first_frame"] == f"ellora://{n['id'].replace('.clip', '.keyframe')}"
            f = supply_file(ellora_dir, n)
            assert main([
                "supply", str(ellora_dir), n["id"], str(f),
                "--ref", f"ellora://{n['id']}", "--fingerprint", n["fingerprint"],
            ]) == 0
    assert code == 0 and passes == 3  # hero, keyframes, clips
    assert (ellora_dir / "v1" / "preview.mp4").exists()
    assert (ellora_dir / "v2" / "capcut_draft").is_dir()
