"""Shared pytest fixtures for hookify tests."""

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Provide an isolated $HOME directory for the test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)
    return home


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    """Provide an isolated project directory and chdir into it."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Provide both isolated $HOME and a project directory.

    Returns a dict: {'home': Path, 'project': Path}
    Chdir starts in the project directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    return {"home": home, "project": project}


def write_rule(directory, filename, frontmatter, body="test rule"):
    """Helper: write a rule file with given frontmatter dict + body."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                if isinstance(item, dict):
                    parts = ", ".join(f'{ik}: "{iv}"' for ik, iv in item.items())
                    lines.append(f"  - {parts}")
                else:
                    lines.append(f'  - "{item}"')
        else:
            lines.append(f'{k}: "{v}"')
    lines.append("---")
    lines.append("")
    lines.append(body)
    path = directory / filename
    path.write_text("\n".join(lines))
    return path
