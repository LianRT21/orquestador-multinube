# ADR-0003: Retardo Configurable en el Enlace de Replicación Asíncrona mediante Toxiproxy

## Estado
Aceptado

## Contexto
En un entorno multi-nube real, las dos nubes residen en regiones geográficas distintas (por ejemplo, AWS us-east-1 y GCP us-central1), con latencias de red inter-región que oscilan entre 20 ms y 100+ ms. Debido a que nuestro experimento se ejecuta localmente en una única máquina mediante contenedores Docker, la comunicación de red interna por defecto tiene latencias submilisegundo (< 1 ms).

Si la réplica de base de datos secundaria (`db-b`) recibe las transacciones de `db-a` en menos de 1 ms, la ventana de pérdida de datos ante una caída abrupta (F1 o F3) sería artificialmente nula o microscópica, resultando en un RPO trivialmente cero en casi todas las observaciones. Esto impediría evaluar cuantitativamente la pérdida de datos y la capacidad del orquestador para minimizar el RPO en condiciones de desfase real.

## Decisión
Se introduce un proxy de inyección de perturbaciones de red (`Toxiproxy`) en el canal de replicación entre `db-a` y `db-b`:
1. `db-b` no se conecta directamente a `db-a:5432`, sino a `toxiproxy:5434`.
2. `toxiproxy` reenvía el flujo TCP a `db-a:5432` aplicando un tóxico de tipo `latency` configurable (200 ms por defecto).
3. La configuración es declarativa a través de `deploy/toxiproxy/toxiproxy.json` y puede modificarse dinámicamente mediante API REST en el puerto `8474`.

## Consecuencias
- **Positivas:**
  - El RPO es cuantitativamente medible y refleja el desfase asíncrono realista de una arquitectura multi-región.
  - El retardo es totalmente parametrizable sin reiniciar PostgreSQL.
  - La métrica de retardo de replicación expuesta en `pg_stat_replication` y Prometheus muestra valores no nulos comprobables en los dashboards.
- **Negativas / Mitigaciones:**
  - Introduce un contenedor adicional en el plano de datos.
  - Mitigación: Toxiproxy es extremadamente liviano (< 20 MB RAM, compilado en Go) y su sobrecarga de CPU es despreciable.
