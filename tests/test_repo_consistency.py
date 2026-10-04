"""Things that are written down in more than one place and have drifted before."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCOPES = re.compile(r"oauth\?scopes=([A-Za-z0-9:_+]+)&force_verify=true")


def _scope_sets(relative: str) -> list[frozenset[str]]:
    text = (ROOT / relative).read_text(encoding="utf-8")
    return [frozenset(match.split("+")) for match in _SCOPES.findall(text)]


def test_setup_script_readme_and_docstring_request_the_same_oauth_scopes():
    readme = _scope_sets("README.md")
    assert len(readme) == 2, "README should have one bot URL and one broadcaster URL"
    for relative in ("deploy/setup.sh", "twitch_radio/chatbot.py"):
        assert _scope_sets(relative) == readme, f"{relative} asks for different scopes than README.md"


def test_the_unit_installs_files_private_to_the_service_user():
    unit = (ROOT / "deploy" / "twitch-radio.service").read_text(encoding="utf-8")
    assert "UMask=0077" in unit and "ProtectSystem=strict" in unit
