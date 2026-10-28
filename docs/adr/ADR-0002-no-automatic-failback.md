# ADR-0002: Ausencia de Conmutación Inversa Automática (No Automatic Failback)

## Estado
Aceptado

## Contexto
Cuando ocurre un failover hacia la nube secundaria N2 (`cloud_b`), la base de datos `db-b` es promovida a primaria independiente. En este punto:
1. `db-b` acepta escrituras y diverge en su secuencia de WAL respecto a la primaria original `db-a`.
2. Si `db-a` o la red de N1 se recupera espontáneamente, `db-a` ya no puede aceptar escrituras (está desincronizada) y no puede volver a ser primaria sin un proceso de resincronización (*pg_rewind* o reconstrucción de réplica).
3. Si el orquestador intentara realizar un failback automático inmediato tan pronto como N1 responda un `200 OK`, se produciría el antipatrón de **oscilación ping-pong** (*flapping*), riesgo inminente de *split-brain* y corrupción silenciosa de datos.

## Decisión
1. Se declara explícitamente que **no existe conmutación inversa automática (failback)** en el orquestador.
2. Al completar la secuencia de conmutación, la máquina de estados alcanza el estado terminal estable `FAILED_OVER`.
3. En este estado opera un mecanismo de **histéresis**: el orquestador suspende nuevas decisiones de conmutación.
4. El retorno al estado inicial requiere un comando administrativo explícito (`POST /reset`) o el desmontaje e inicialización limpia del entorno entre corridas por parte del runner experimental.

## Consecuencias
- **Positivas:**
  - Garantía de consistencia: se previene absolutamente el riesgo de *split-brain* o re-escrituras en primarias divergentes.
  - El diseño experimental es limpio: cada corrida evalúa el proceso de conmutación ante una falla específica y se reinicia desde cero para la siguiente réplica.
- **Negativas / Mitigaciones:**
  - En un entorno de producción comercial, el failback requeriría un runbook asistido con resincronización manual o herramientas como *pg_rewind*.
  - Esta delimitación se documenta explícitamente en `docs/LIMITATIONS.md` como una simplificación deliberada del prototipo.
