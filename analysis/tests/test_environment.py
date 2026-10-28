"""Prueba unitaria de verificación del entorno base."""

import sys


def test_python_version() -> None:
    """Verifica que la versión de Python sea 3.12 o superior."""
    assert sys.version_info >= (3, 12), f"Se requiere Python 3.12+, detectado: {sys.version}"


def test_project_structure() -> None:
    """Verifica la existencia de los directorios clave del proyecto."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    expected_dirs = [
        root / "docs",
        root / "deploy",
        root / "services",
        root / "experiments",
        root / "analysis",
        root / "data" / "raw",
        root / "data" / "processed",
    ]
    for d in expected_dirs:
        assert d.exists(), f"El directorio {d} no existe"
