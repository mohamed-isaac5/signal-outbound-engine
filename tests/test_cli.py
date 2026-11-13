from engine.cli import main


def test_version(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.count(".") == 2


def test_placeholder_subcommand(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["score"]) == 0
    assert "milestone" in capsys.readouterr().out
