# ADR-0001: Diseño de la Máquina de Estados Finita Pura con Inyección de Reloj y Adaptadores

## Estado
Aceptado

## Contexto
El orquestador de resiliencia es el núcleo crítico de decisión del experimento. Si la lógica de decisión estuviera fuertemente acoplada a llamadas de red (HTTP `httpx`, sockets TCP `asyncio`, consultas SQL) o al reloj del sistema (`time.time()`), las pruebas automatizadas requerirían entornos Docker complejos o sufrirían de no-determinismo (*flaky tests*).

Además, para garantizar la validez experimental, es indispensable que:
1. Las decisiones de conmutación sean deterministas y auditables.
2. Cada transición de estado se base en reglas estrictas (umbral de 3 fallos consecutivos, reinicio por éxito, detección de degradación parcial).
3. Todas las marcas de tiempo ($t_{\text{detect}}$, $t_{\text{promote}}$, $t_{\text{switch}}$, $t_{\text{verified}}$) se registren con precisión de nanosegundos UTC.

## Decisión
1. Se separa la **lógica de decisión** pura (`FailoverStateMachine`) de la **capa de ejecución y E/S** (`OrchestratorEngine`).
2. La máquina de estados es un autómata determinista con estados formales:
   - `HEALTHY`: Nodo activo N1 respondiendo dentro de los umbrales de latencia y disponibilidad.
   - `SUSPECT`: Uno o dos fallos consecutivos acumulados.
   - `FAILING_OVER`: Se alcanzaron exactamente 3 fallos consecutivos en todas las instancias de N1. Secuencia de conmutación en curso.
   - `FAILED_OVER`: Conmutación completada exitosamente. Tráfico redirigido a N2.
   - `FAILOVER_ERROR`: Error parcial irrecuperable durante la conmutación (por ejemplo, N2 inalcanzable).
3. **Reloj Inyectable (`ClockProtocol`):** Todas las marcas de tiempo se obtienen a través de una abstracción de reloj, permitiendo inyectar un reloj simulado en pruebas unitarias para probar temporizadores y timeouts sin pausas reales (`sleep`).
4. **Adaptadores desacoplados tras interfaces `Protocol`:** HAProxy, cliente de sondas HTTP y promotor de PostgreSQL se implementan como adaptadores desacoplados, permitiendo pruebas unitarias con cobertura del 100% de la lógica sin contenedores.

## Consecuencias
- **Positivas:**
  - Cobertura de pruebas unitarias superior al 85% de forma inmediata y sin dependencias de Docker.
  - Reproducibilidad matemática: dadas las mismas entradas de sondas, la máquina genera exactamente las mismas transiciones y eventos.
  - Trazabilidad forense: cada evento registra `timestamp_ns`, `from_state`, `to_state`, `reason` y metadatos.
- **Negativas / Mitigaciones:**
  - Requiere mantener interfaces (`Protocol`) y separar la capa de coordinación en `engine.py`.
  - Esta sobrecarga arquitectónica es una práctica estándar recomendada en SRE y sistemas distribuidos.
