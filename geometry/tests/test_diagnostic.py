from workshop_geometry import create_diagnostic_box


def test_diagnostic_box_volume() -> None:
    mesh = create_diagnostic_box((10.0, 20.0, 5.0))
    assert mesh.is_watertight
    assert mesh.volume == 1000.0
