import yaml

from engine.cli import main


def test_doctor_passes_with_installed_ffmpeg(ffmpeg, capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "ffmpeg: found" in out and "ffprobe: found" in out
    for f in ("xfade", "sidechaincompress", "subtitles", "drawtext", "zoompan"):
        assert f"OK      {f}" in out
    assert "font:" in out


def test_doctor_fails_with_bogus_ffmpeg(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"assembly": {"ffmpeg": str(tmp_path / "no-ffmpeg")}}))
    assert main(["doctor", "--config", str(cfg)]) == 1
    out = capsys.readouterr().out
    assert "ffmpeg: NOT FOUND" in out and "MISSING" in out
    assert "homebrew-ffmpeg" in out
