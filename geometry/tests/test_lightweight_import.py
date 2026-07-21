import importlib
import sys

def test_three_mf_import_does_not_require_trimesh(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "trimesh", None)
    module = importlib.import_module("workshop_geometry.three_mf")
    assert hasattr(module, "inspect_3mf")
