"""Every RhinoCommon / Grasshopper member we use exists in the real Rhino 8 assemblies.

Needs `dnfile` and either network access (downloads RhinoCommon/Grasshopper from NuGet once)
or a filled cache at $KAZI_NUGET_CACHE. Skipped otherwise.
"""

import os
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("dnfile")
TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "check_rhino_api.py"


def test_rhino_api_uses_exist():
    cache = os.environ.get("KAZI_NUGET_CACHE", "~/.cache/kazi-rhino/nuget")
    r = subprocess.run([sys.executable, str(TOOL), "--cache", cache], capture_output=True, text=True,
                       timeout=600)
    if "URLError" in r.stderr or "HTTPError" in r.stderr:
        pytest.skip("can't download RhinoCommon from NuGet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 problem(s)" in r.stdout
