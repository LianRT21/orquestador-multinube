"""CLI de administración y orquestación del proyecto.

Permite ejecutar todas las tareas del ciclo de vida del experimento tanto en
Linux/macOS/WSL2 como en Windows nativo (PowerShell / CMD).
"""

import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = ROOT_DIR / "deploy" / "compose.yaml"


def _run(cmd: list[str], check: bool = True) -> int:
    """Ejecuta un comando en el directorio raíz del proyecto."""
    print(f"\n[EXEC] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if check and result.returncode != 0:
        print(f"\n[ERROR] El comando falló con código {result.returncode}")
        sys.exit(result.returncode)
    return result.returncode


def cmd_setup() -> None:
    """Instala dependencias y configura pre-commit."""
    print("=== Configurando entorno de desarrollo ===")
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    _run([sys.executable, "-m", "pip", "install", "-e", ".[dev]"])
    # Instalar pre-commit si está disponible
    try:
        _run(["pre-commit", "install"], check=False)
    except FileNotFoundError:
        print("[AVISO] pre-commit no está en el PATH; omitiendo hook git.")
    print("=== Entorno configurado exitosamente ===")


def cmd_up() -> None:
    """Levanta todos los servicios con Docker Compose y espera a que estén sanos."""
    print("=== Levantando entorno Docker Multi-Nube ===")
    if not COMPOSE_FILE.exists():
        print(f"[ERROR] Archivo compose no encontrado en {COMPOSE_FILE}")
        sys.exit(1)
    _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"])
    print("=== Todos los servicios están en ejecución y sanos ===")


def cmd_down() -> None:
    """Detiene y elimina todos los contenedores y volúmenes."""
    print("=== Deteniendo y limpiando entorno Docker ===")
    if COMPOSE_FILE.exists():
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"])
    print("=== Entorno detenido y volúmenes removidos ===")


def cmd_lint() -> None:
    """Ejecuta validaciones de formato, estilo y tipado estricto."""
    print("=== Ejecutando Ruff (Linter) ===")
    _run([sys.executable, "-m", "ruff", "check", "."])
    print("=== Ejecutando Ruff (Formato) ===")
    _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    print("=== Ejecutando Mypy (Modo Estricto) ===")
    # Validar directorios existentes
    target_dirs = [d for d in ["services", "experiments", "analysis"] if (ROOT_DIR / d).exists()]
    if target_dirs:
        _run([sys.executable, "-m", "mypy", "--strict", *target_dirs])
    else:
        _run([sys.executable, "-m", "mypy", "--strict", "manage.py"])
    print("=== Todas las validaciones de calidad pasaron exitosamente ===")


def cmd_test_unit() -> None:
    """Ejecuta pruebas unitarias con reporte de cobertura."""
    print("=== Ejecutando pruebas unitarias ===")
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "-m",
            "not integration and not chaos",
            "--cov",
            "--cov-report=term-missing",
        ]
    )


def cmd_test() -> None:
    """Alias para ejecutar pruebas unitarias."""
    cmd_test_unit()


def cmd_test_integration() -> None:
    """Ejecuta pruebas de integración que requieren Docker."""
    print("=== Ejecutando pruebas de integración ===")
    _run([sys.executable, "-m", "pytest", "-v", "-m", "integration"])


def cmd_smoke() -> None:
    """Ejecuta la corrida de humo (8 réplicas cortas)."""
    print("=== Iniciando Corrida de Humo (Smoke Test) ===")
    _run([sys.executable, "-m", "experiments.runner.run_experiment", "--smoke"])


def cmd_design() -> None:
    """Genera la matriz del diseño experimental factorial 2x4."""
    print("=== Generando matriz de diseño experimental (240 corridas) ===")
    _run([sys.executable, "-m", "experiments.runner.design"])


def cmd_run_all() -> None:
    """Ejecuta el experimento completo reanudable."""
    print("=== Ejecutando experimento completo con reanudación (--resume) ===")
    _run([sys.executable, "-m", "experiments.runner.run_experiment", "--resume"])


def cmd_run(run_id: str) -> None:
    """Ejecuta una corrida individual por ID."""
    print(f"=== Ejecutando corrida individual: {run_id} ===")
    _run([sys.executable, "-m", "experiments.runner.run_experiment", "--only", run_id])


def cmd_metrics() -> None:
    """Calcula métricas a partir de los datos crudos."""
    print("=== Calculando métricas y actualizando data/processed/runs.csv ===")
    _run([sys.executable, "-m", "experiments.metrics.compute_metrics"])


def cmd_analyze() -> None:
    """Ejecuta modelos estadísticos, figuras e informe."""
    print("=== Ejecutando análisis estadístico y generando figuras ===")
    _run([sys.executable, "-m", "analysis.analyze"])


def cmd_excel() -> None:
    """Exporta el libro de Excel con validación cruzada."""
    print("=== Generando libro de validación cruzada en Excel ===")
    _run([sys.executable, "-m", "analysis.export_excel"])


def cmd_dashboards() -> None:
    """Abre el panel de control de Grafana."""
    url = "http://127.0.0.1:3000"
    print(f"=== Abriendo Grafana en {url} ===")
    webbrowser.open(url)


def main() -> None:
    """Enrutador de comandos CLI."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Uso: python manage.py <comando> [argumentos]")
        print("\nComandos disponibles:")
        print("  setup             Instala dependencias y herramientas")
        print("  up                Levanta el entorno Docker Compose")
        print("  down              Destruye contenedores y volúmenes")
        print("  lint              Ejecuta ruff y mypy")
        print("  test              Ejecuta pruebas unitarias con cobertura")
        print("  test-unit         Ejecuta pruebas unitarias")
        print("  test-integration  Ejecuta pruebas de integración Docker")
        print("  smoke             Ejecuta corrida de humo")
        print("  design            Genera data/design.csv")
        print("  run-all           Ejecuta las 240 corridas con --resume")
        print("  run <id>          Ejecuta una corrida específica")
        print("  metrics           Procesa runs.csv")
        print("  analyze           Ejecuta modelos y genera figuras")
        print("  excel             Genera validación cruzada en Excel")
        print("  dashboards        Abre Grafana")
        sys.exit(0)

    action = sys.argv[1].lower()
    commands = {
        "setup": cmd_setup,
        "up": cmd_up,
        "down": cmd_down,
        "lint": cmd_lint,
        "test": cmd_test,
        "test-unit": cmd_test_unit,
        "test-integration": cmd_test_integration,
        "smoke": cmd_smoke,
        "design": cmd_design,
        "run-all": cmd_run_all,
        "metrics": cmd_metrics,
        "analyze": cmd_analyze,
        "excel": cmd_excel,
        "dashboards": cmd_dashboards,
    }

    if action == "run":
        if len(sys.argv) < 3:
            print(
                "[ERROR] Debe especificar el ID de la corrida. Ejemplo: python manage.py run RUN_001"
            )
            sys.exit(1)
        cmd_run(sys.argv[2])
    elif action in commands:
        commands[action]()
    else:
        print(
            f"[ERROR] Comando desconocido: '{action}'. Ejecute 'python manage.py --help' para ver la lista."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
