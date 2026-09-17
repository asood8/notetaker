from typer.testing import CliRunner

from notetaker import __version__
from notetaker.cli import app


def test_version_command_prints_the_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
