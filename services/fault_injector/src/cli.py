"""CLI para inyección y restauración de fallas en el entorno experimental."""

import json
import sys

import typer
from rich.console import Console

from services.fault_injector.src.injector import DockerFaultInjector
from services.fault_injector.src.models import (
    FaultInjectorConfig,
    FaultType,
)

app = typer.Typer(
    name="fault-injector",
    help="CLI para inyección controlada de fallas F1 a F4 en entornos Docker",
    add_completion=False,
)
console = Console()


def get_injector() -> DockerFaultInjector:
    """Instancia el inyector con configuración predeterminada."""
    config = FaultInjectorConfig()
    return DockerFaultInjector(config=config)


@app.command()
def inject(
    fault: FaultType = typer.Option(
        ...,
        "--fault",
        "-f",
        help="Tipo de falla a inyectar (F1: crash app, F2: partición red, F3: crash db, F4: degradación red)",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Emitir el resultado en formato JSON estructurado",
    ),
) -> None:
    """Inyecta una falla registrando t_falla en nanosegundos inmediatamente antes del evento."""
    try:
        injector = get_injector()
        result = injector.inject(fault)
        if as_json:
            typer.echo(result.model_dump_json(indent=2))
        else:
            console.print(f"[bold green]✔ Falla {fault.value} inyectada con éxito.[/bold green]")
            console.print(f"  [cyan]t_falla (UTC ns):[/cyan] {result.t_fault_ns}")
            console.print(f"  [cyan]Detalles:[/cyan] {result.details}")
    except Exception as exc:
        if as_json:
            err_dict = {
                "fault": fault.value,
                "success": False,
                "error": str(exc),
            }
            typer.echo(json.dumps(err_dict, indent=2))
        else:
            console.print(f"[bold red]✘ Error al inyectar falla {fault.value}:[/bold red] {exc}")
        sys.exit(1)


@app.command()
def restore(
    fault: FaultType = typer.Option(
        ...,
        "--fault",
        "-f",
        help="Tipo de falla a restaurar (F1, F2, F3, F4)",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Emitir el resultado en formato JSON estructurado",
    ),
) -> None:
    """Restaura el estado original del sistema previo a la inyección de la falla."""
    try:
        injector = get_injector()
        result = injector.restore(fault)
        if as_json:
            typer.echo(result.model_dump_json(indent=2))
        else:
            console.print(f"[bold green]✔ Falla {fault.value} restaurada con éxito.[/bold green]")
            console.print(f"  [cyan]t_restauracion (UTC ns):[/cyan] {result.t_restore_ns}")
            console.print(f"  [cyan]Detalles:[/cyan] {result.details}")
    except Exception as exc:
        if as_json:
            err_dict = {
                "fault": fault.value,
                "success": False,
                "error": str(exc),
            }
            typer.echo(json.dumps(err_dict, indent=2))
        else:
            console.print(f"[bold red]✘ Error al restaurar falla {fault.value}:[/bold red] {exc}")
        sys.exit(1)


@app.command()
def restore_all(
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Emitir el resultado en formato JSON estructurado",
    ),
) -> None:
    """Restaura todas las posibles perturbaciones (F1, F2, F3, F4) de forma secuencial."""
    injector = get_injector()
    results = []
    has_error = False
    for fault in [FaultType.F1, FaultType.F2, FaultType.F3, FaultType.F4]:
        try:
            res = injector.restore(fault)
            results.append(res.model_dump())
        except Exception as exc:
            has_error = True
            results.append({"fault": fault.value, "success": False, "error": str(exc)})

    if as_json:
        typer.echo(json.dumps({"results": results, "success": not has_error}, indent=2))
    else:
        for r in results:
            if r.get("success"):
                console.print(f"[green]✔ Restaurado {r.get('fault')}[/green]")
            else:
                console.print(f"[red]✘ Falló {r.get('fault')}: {r.get('error')}[/red]")

    if has_error:
        sys.exit(1)


if __name__ == "__main__":
    app()
