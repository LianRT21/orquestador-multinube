"""Script CLI para la siembra inicial de datos en la base de datos de órdenes."""

import asyncio
import random
import time
from decimal import Decimal
from uuid import uuid4

import typer

from services.reference_app.src.database import OrderModel, db_manager

cli = typer.Typer(help="Siembra inicial de datos para la aplicación de referencia")


async def _seed_data(num_orders: int, num_customers: int, batch_size: int, seed: int) -> None:
    """Inserta pedidos en lotes para optimizar memoria y tiempo de transacción."""
    random.seed(seed)
    db_manager.init_engine()

    assert db_manager._sessionmaker is not None

    print(f"Iniciando siembra de {num_orders} pedidos para {num_customers} clientes...")
    start_time = time.perf_counter()
    inserted = 0

    async with db_manager._sessionmaker() as session:
        for batch_start in range(0, num_orders, batch_size):
            current_batch_size = min(batch_size, num_orders - batch_start)
            batch = [
                OrderModel(
                    order_id=uuid4(),
                    customer_id=random.randint(1, num_customers),
                    amount=Decimal(f"{random.uniform(5.0, 500.0):.2f}"),
                    status="COMPLETED",
                )
                for _ in range(current_batch_size)
            ]
            session.add_all(batch)
            await session.commit()
            inserted += current_batch_size
            print(f"Progreso: {inserted}/{num_orders} pedidos insertados...")

    elapsed = round(time.perf_counter() - start_time, 2)
    print(f"Siembra completada exitosamente en {elapsed} segundos.")
    await db_manager.close_engine()


@cli.command()
def run(
    orders: int = typer.Option(10000, "--orders", "-o", help="Número total de pedidos a sembrar"),
    customers: int = typer.Option(1000, "--customers", "-c", help="Número total de clientes"),
    batch_size: int = typer.Option(1000, "--batch-size", "-b", help="Tamaño del lote de inserción"),
    seed: int = typer.Option(42, "--seed", "-s", help="Semilla aleatoria para reproducibilidad"),
) -> None:
    """Ejecuta la siembra asíncrona de datos."""
    asyncio.run(_seed_data(orders, customers, batch_size, seed))


if __name__ == "__main__":
    cli()
