from __future__ import annotations

def create_diagnostic_box(size_mm: tuple[float, float, float] = (10.0, 20.0, 5.0)):
    import trimesh

    if any(value <= 0 for value in size_mm):
        raise ValueError("All box dimensions must be positive.")

    return trimesh.creation.box(extents=size_mm)
