# Prompt para Antigravity: prototipo funcional del orquestador de failover multi-nube

> Cómo usarlo: copie todo lo que está debajo de la línea `---` y péguelo como primera instrucción en Antigravity. Pídale que genere el plan y la lista de tareas antes de escribir código, y revíselos antes de aprobar.

---

## 1. Rol y objetivo

Actúa como un ingeniero de software senior especializado en SRE, sistemas distribuidos y Python. Vas a construir, de principio a fin, un **prototipo funcional, probado y reproducible** de un **orquestador automatizado de conmutación por error (failover) entre dos "nubes" simuladas**, junto con todo el entorno para evaluarlo experimentalmente y analizar los resultados.

El prototipo es para un proyecto académico (Ingeniería de Sistemas, Universidad Libre, Bogotá). **No existe ninguna empresa real ni servidores reales**: todo se simula en una sola máquina con Docker. Tu trabajo es entregar un repositorio completo que yo pueda clonar, levantar con pocos comandos, probar, ejecutar el experimento y analizar.

## 2. Contexto del proyecto (no lo cambies)

- **Título:** "Optimización de la Resiliencia Operativa mediante un Orquestador Automatizado de Conmutación por Error en Entornos Multi-Nube para Aplicaciones Empresariales Críticas".
- **Enfoque:** cuantitativo experimental.
- **Idea:** una aplicación transaccional crítica corre en una nube activa **N1**. Una segunda nube **N2** actúa como **respaldo tibio** (warm standby) con una réplica **asíncrona** de la base de datos. Cuando N1 falla, el orquestador lo detecta con sondas HTTP, promueve la réplica de N2, reconfigura un *reverse proxy* de **capa 7** y el tráfico pasa a N2.
- **Diseño experimental:** factorial 2 × 4. Factor A = condición (**control**: recuperación manual por un operador con runbook; **tratamiento**: con orquestador). Factor B = tipo de falla (F1–F4). **30 réplicas por celda = 240 corridas.** La unidad de análisis es la **corrida**, no la solicitud individual.
- **Métricas:** RTO, RPO, disponibilidad, tasa de errores HTTP 5xx, latencia p95 y p99.
- **Modelo estadístico (ya definido en la propuesta):** ANOVA factorial sobre `log(RTO)` con interacción condición × falla; GLM binomial negativa para RPO; GLM binomial/cuasi-binomial (logit) para disponibilidad; prueba binomial exacta de la tasa de 5xx frente a 1 %; ANOVA sobre `log(latencia)`; análisis de supervivencia (Kaplan-Meier y Cox) si hay RTO censurado en el control. Herramienta principal: **Python (Pandas, statsmodels, SciPy)**. Excel se usa para tabulación y **validación cruzada**.

### Las cuatro fallas (definición oficial de la propuesta)

| Código | Falla inyectada | Qué simula |
|---|---|---|
| F1 | Terminación abrupta de las instancias de la aplicación en N1 | Caída de nodos o de una zona de disponibilidad |
| F2 | Partición de red entre N1 y N2, o pérdida de conectividad saliente de N1 | Fallo de enrutamiento o conectividad del proveedor |
| F3 | Caída de la base de datos primaria | Falla del plano de datos |
| F4 | Latencia inducida alta (≥ 2000 ms) y pérdida de paquetes (≥ 20 %) en N1 | Degradación parcial (*gray failure*) |

### Definiciones de métricas (oficiales)

- **RTO** = `t_recuperación − t_falla`, donde `t_recuperación` es el instante en que se registran **k = 10 solicitudes exitosas consecutivas** a través del proxy después de la falla.
- **RPO** = diferencia entre la marca de tiempo de la última transacción confirmada en el primario y la última presente en el secundario; además, **número de transacciones perdidas**.
- **Ventana máxima de recuperación:** 15 minutos. Si no hay recuperación en esa ventana, el RTO queda **censurado** en 900 s y se marca `rto_censored = true`.
- **Estructura de una corrida:** 5 min de estado estacionario → inyección de la falla → observación hasta la recuperación verificada + 5 min de estabilización. Duración típica ≈ 15 min (tratamiento) y hasta ≈ 25 min (control).
- **Carga:** 50 solicitudes/s constantes, 70 % lecturas y 30 % escrituras.

## 3. Principios y restricciones no negociables

1. **Todo corre local con Docker Compose v2.** Las "dos nubes" son dos redes Docker aisladas (`cloud_a` = N1 y `cloud_b` = N2) más una red de plano de control. No se usa ningún servicio de pago ni cuenta en la nube.
2. **Reproducibilidad:** versiones de imágenes y dependencias **fijadas** (no usar `latest`), semillas aleatorias configurables, configuración por archivo YAML y variables de entorno. Un comando levanta todo; otro lo destruye.
3. **Portabilidad:** debe funcionar en Linux, macOS y Windows con Docker Desktop + WSL2. Toda la lógica va en **scripts Python con CLI (Typer)**; el `Makefile` solo envuelve esos comandos.
4. **El orquestador es el único que decide el failover en la condición de tratamiento.** Desactiva los health checks automáticos del proxy: si el proxy conmutara solo, contaminaría el experimento.
5. **No inventes resultados.** Los datos reales solo salen de ejecutar el experimento. Si generas datos sintéticos para probar el pipeline de análisis, deben estar claramente etiquetados (`synthetic=true`, carpeta aparte) y nunca mezclarse con datos reales.
6. **Honestidad técnica:** documenta en `docs/LIMITATIONS.md` todo lo que sea una simplificación frente a un entorno real (una sola máquina, latencias entre "nubes" simuladas, reloj único, operador simulado, etc.).
7. **No ejecutes automáticamente las 240 corridas completas** (≈ 64–80 horas). Entrega el comando y haz que sea **reanudable**. Sí ejecuta y verifica la corrida de humo (sección 9).
8. **Sin secretos en el repositorio.** Contraseñas de demo solo en `.env.example`; `.env` va en `.gitignore`.

## 4. Stack tecnológico (fija versiones concretas en los archivos)

- Python 3.12; FastAPI + Uvicorn; SQLAlchemy 2.x (modo asíncrono) con `asyncpg` o `psycopg 3`; Pydantic v2 y `pydantic-settings`; `httpx`; `structlog` (logs JSON); `prometheus-client`; Typer; Docker SDK for Python.
- PostgreSQL 16 (imagen oficial) con replicación en streaming asíncrona.
- HAProxy 2.x con **Runtime API** (socket de administración por TCP) como *reverse proxy* de capa 7.
- Prometheus, Blackbox Exporter y Grafana (dashboards provisionados por archivo).
- Locust (modo headless) como generador de carga.
- Inyección de fallas: Docker SDK (kill, `network disconnect`) y `tc netem` desde un contenedor auxiliar con `NET_ADMIN`; **plan B con Toxiproxy** si el kernel del host no soporta netem.
- Análisis: Pandas, NumPy, SciPy, statsmodels (ANOVA, GLM, `SurvfuncRight`, `PHReg`), Matplotlib, openpyxl.
- Calidad: pytest, pytest-asyncio, pytest-cov, ruff (lint y formato), mypy en modo estricto, pre-commit, GitHub Actions.

## 5. Arquitectura

```
                    ┌────────────── Plano de control (red control_plane) ─────────────┐
 Generador de       │  HAProxy (L7)  ◄── API runtime ──  Orquestador (FastAPI)        │
 carga (Locust) ───►│      │                                  │ sondas /health 1 s    │
 50 req/s           │      │                                  │ promueve réplica      │
                    │  Prometheus · Blackbox · Grafana        │                       │
                    └──────┼──────────────────────────────────┼───────────────────────┘
                           │                                  │
            ┌──────────────▼───────────┐          ┌───────────▼──────────────┐
            │ N1 (red cloud_a) ACTIVA  │          │ N2 (red cloud_b) RESPALDO│
            │  app-a  (FastAPI)        │          │  app-b  (FastAPI)        │
            │  db-a   (PG primario)    │─ stream ►│  db-b   (PG réplica)     │
            └──────────────────────────┘ asíncrono└──────────────────────────┘
```

- `app-a` y `app-b` son **la misma imagen** con distinta variable `CLOUD_ID`. Cada una se conecta solo a su base de datos local.
- Parametriza `APP_INSTANCES_PER_CLOUD` (por defecto 1). F1 mata **todas** las instancias de N1.
- HAProxy enruta a `app-a` por defecto y tiene a `app-b` configurado pero **deshabilitado** (estado `maint`). La conmutación consiste en cambiar esos estados vía Runtime API, sin recargar el proceso.
- La replicación pasa por un punto donde se pueda **inyectar retardo configurable** (por ejemplo Toxiproxy en el enlace de replicación), para que el RPO sea medible y no trivialmente cero. Valor por defecto del retardo: 200 ms, configurable en YAML.

## 6. Estructura del repositorio (créala exactamente así o justifica cualquier cambio)

```
resilience-orchestrator/
├── README.md
├── Makefile
├── pyproject.toml                # config de ruff, mypy, pytest, coverage
├── .env.example
├── .gitignore  .editorconfig  .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── EXPERIMENT_PROTOCOL.md
│   ├── RUNBOOK_MANUAL.md         # runbook de la condición de control
│   ├── METRICS.md                # definición formal de cada métrica
│   ├── LIMITATIONS.md
│   └── adr/                      # decisiones de arquitectura (ADR-0001...)
├── deploy/
│   ├── compose.yaml
│   ├── postgres/                 # init del primario, entrypoint de la réplica, postgresql.conf
│   ├── haproxy/haproxy.cfg
│   ├── prometheus/prometheus.yml
│   ├── blackbox/blackbox.yml
│   └── grafana/                  # provisioning + dashboards .json
├── services/
│   ├── reference_app/            # src/, tests/, Dockerfile, requirements.txt
│   ├── orchestrator/             # src/, tests/, Dockerfile, requirements.txt
│   └── fault_injector/           # librería + CLI
├── experiments/
│   ├── config/experiment.yaml
│   ├── loadgen/locustfile.py
│   ├── runner/                   # run_experiment.py, design.py, manual_operator.py
│   └── metrics/compute_metrics.py
├── analysis/
│   ├── analyze.py  models.py  plots.py  export_excel.py  synthetic.py
│   └── tests/
└── data/
    ├── raw/        .gitkeep      # logs por solicitud y eventos por corrida
    └── processed/  .gitkeep      # runs.csv, resultados, figuras
```

## 7. Especificación por componente

### 7.1 Aplicación de referencia (`services/reference_app`)

API REST transaccional que simula pedidos/pagos de una empresa.

- **Endpoints**
  - `POST /orders`: crea un pedido. El cuerpo incluye `order_id` (UUID generado por el **cliente**, para idempotencia), `customer_id`, `amount`. Responde `201` solo después del `COMMIT`. Si el `order_id` ya existe, responde `200` sin duplicar.
  - `GET /orders/{order_id}`: lectura.
  - `GET /orders?customer_id=...&limit=...`: lectura con consulta simple.
  - `GET /health`: devuelve `200` con JSON `{status, cloud_id, db_ok, db_role, db_latency_ms, mem_mb, uptime_s}`; devuelve `503` si la base de datos no responde en el tiempo máximo. Debe medir una consulta real (`SELECT 1`) y el rol de la BD (`pg_is_in_recovery()`).
  - `GET /metrics`: métricas Prometheus (contador de solicitudes por código, histograma de latencia, estado de la conexión a BD).
- **Esquema:** tabla `orders(order_id uuid pk, customer_id, amount, status, seq bigserial, committed_at timestamptz default clock_timestamp())` e índice por `customer_id`. `seq` y `committed_at` sirven para calcular el RPO.
- **Comportamiento según rol de la BD:** si la BD está en modo réplica (`pg_is_in_recovery() = true`), las lecturas funcionan y las escrituras devuelven `503` con un cuerpo claro. Al ser promovida, las escrituras funcionan **sin reiniciar** la aplicación (detecta el rol con caché de máximo 1 s).
- **Robustez:** pool de conexiones con límites, *timeouts* explícitos de conexión y de consulta, cierre ordenado ante SIGTERM, manejo de errores sin filtrar trazas al cliente, logs JSON con `request_id`.
- **Datos semilla:** script que carga un volumen inicial configurable (por defecto 10 000 pedidos y 1 000 clientes).

### 7.2 Base de datos y replicación (`deploy/postgres`)

- `db-a` primario; `db-b` réplica en **streaming asíncrono** (`synchronous_commit = local`, `synchronous_standby_names` vacío), con *replication slot* y usuario de replicación dedicado.
- La réplica se inicializa con `pg_basebackup` en su primer arranque; todo automatizado en scripts de entrypoint idempotentes.
- Promoción con `SELECT pg_promote(wait => true)`. El script debe medir y registrar cuánto tarda.
- Expón el retardo de replicación (`pg_stat_replication`) como métrica Prometheus.
- **Reinicio entre corridas:** recreación completa de volúmenes y re-siembra de datos para garantizar independencia entre corridas. Documenta el tiempo que toma y asegúrate de que **no** cuente dentro del RTO.

### 7.3 Proxy de capa 7 (`deploy/haproxy`)

- Modo HTTP. Backend `app` con `server app-a` activo y `server app-b` en `maint` al inicio.
- **Sin health checks activos propios** en ninguno de los servidores.
- Runtime API habilitada por TCP en la red de control, accesible solo desde el orquestador y desde el script de recuperación manual.
- Timeouts explícitos (`timeout connect`, `client`, `server`); logs en formato que permita auditar códigos 5xx generados por el proxy (502/503/504) frente a los de la aplicación.

### 7.4 Orquestador (`services/orchestrator`), el componente principal

**Sondas.** Cada `probe_interval_s` (por defecto 1 s) hace `GET /health` a cada instancia de N1 de forma concurrente. Una sonda **falla** si: el código no es 200, hay *timeout* (por defecto 1,0 s), o el tiempo de respuesta supera `degraded_latency_ms` (por defecto 1500 ms, lo que permite detectar F4). La respuesta también se evalúa por `db_ok`. N1 se considera caída cuando **todas** sus instancias acumulan `failure_threshold` fallos consecutivos (por defecto **3**). Un éxito reinicia el contador.

**Máquina de estados explícita:** `HEALTHY → SUSPECT → FAILING_OVER → FAILED_OVER` (más `FAILOVER_ERROR` con reintentos limitados). Implementada de forma pura y testeable (la decisión no depende de red ni de reloj; se inyectan).

**Secuencia de failover (idempotente, con bloqueo para evitar ejecuciones concurrentes):**
1. Registrar `t_detect` y pasar a `FAILING_OVER`.
2. *Fencing* de N1: sacar a `app-a` del proxy (HAProxy → `maint`) **antes** de promover, para evitar *split-brain*. Intento adicional, con tiempo máximo corto, de dejar `db-a` en solo lectura si es alcanzable.
3. Verificar que N2 está sana (`app-b` responde y `db-b` está en recuperación).
4. Promover `db-b` y registrar `t_promote_start` y `t_promote_end`.
5. Habilitar `app-b` en el proxy (HAProxy → `ready`) y registrar `t_switch`.
6. Verificación sintética: escritura y lectura de prueba a través del proxy; registrar `t_verified`.
7. Estado final `FAILED_OVER`. **No hay failback automático** (fuera del alcance); documéntalo como decisión de diseño en un ADR.

**Otros requisitos:**
- Reintentos con *backoff* exponencial y límite en cada acción; *timeouts* en todo; manejo explícito de errores parciales (por ejemplo, la promoción funcionó pero el proxy no respondió).
- Histéresis: tras un failover no vuelve a decidir nada hasta recibir un `reset` explícito.
- API de administración: `GET /status` (estado, contadores, últimas sondas), `GET /events` (línea de tiempo con marcas de tiempo en nanosegundos UTC), `POST /reset`, `GET /metrics`, `GET /health`.
- Configuración tipada por YAML/variables de entorno con validación al arrancar (falla rápido si falta algo).
- **Eventos con marca de tiempo** persistidos como JSON Lines en un volumen compartido para que el *runner* los lea: `probe_failed`, `suspect`, `t_detect`, `t_promote_start`, `t_promote_end`, `t_switch`, `t_verified`.

### 7.5 Condición de control: recuperación manual

- Documenta en `docs/RUNBOOK_MANUAL.md` los pasos que un operador sigue: observar la alerta, confirmar la falla, comprobar la réplica, promoverla, redirigir el proxy y verificar.
- Implementa `experiments/runner/manual_operator.py` con dos modos:
  - `--operator human`: imprime cada paso del runbook, espera que el operador lo confirme y registra el tiempo de cada paso. Es el modo "real" de la propuesta (mismo operador en todas las corridas).
  - `--operator simulated`: ejecuta los mismos pasos con **retardos configurables** (modelo en `experiment.yaml`, por ejemplo distribución log-normal para detección y para cada paso). Es para poder automatizar las corridas de control. Toda corrida con este modo debe quedar marcada con `operator_mode = simulated` en los datos, y el supuesto debe documentarse como amenaza a la validez en `LIMITATIONS.md`.
- El mismo mecanismo de promoción y de cambio de proxy que usa el orquestador, pero disparado por el operador. En control **el orquestador está apagado**.
- Si la recuperación no ocurre dentro de 15 minutos, el RTO queda censurado.

### 7.6 Monitoreo (`deploy/prometheus`, `deploy/grafana`)

- Prometheus: *scrape* de sondas cada 1 s y del sistema cada 5 s, como dice la metodología.
- Blackbox Exporter sondeando el proxy.
- Dashboard de Grafana provisionado (sin configuración manual) con: estado de cada nube, RTO en vivo, tasa de errores por código, latencia p50/p95/p99, retardo de replicación y línea de tiempo de eventos del orquestador.

### 7.7 Generador de carga (`experiments/loadgen`)

- Locust en modo headless, **50 usuarios con `constant_throughput(1)`** para obtener 50 req/s; mezcla 70 % lecturas (GET) y 30 % escrituras (POST con UUID generado en el cliente).
- **Sin reintentos automáticos** en el cliente (para medir la experiencia cruda).
- *Timeout* de cliente configurable (por defecto 3 s).
- Un *hook* de eventos escribe **cada solicitud** en un archivo por corrida: `ts_start_ns, method, path, status, latency_ms, order_id, ok, error_type`. Las escrituras confirmadas (`201`) se guardan también en una lista de "confirmadas" para calcular el RPO.
- Si Locust no logra precisión suficiente a 50 req/s en la máquina del usuario, documenta el problema y propón (sin implementar sin avisar) una alternativa con un cliente asíncrono propio.

### 7.8 Inyector de fallas (`services/fault_injector`)

CLI y librería con una interfaz común `inject(fault)` / `restore()` y estrategia por falla:

- **F1:** `SIGKILL` a todos los contenedores `app` de N1.
- **F2:** desconectar N1 de la red de control (`docker network disconnect`) para simular pérdida de conectividad, de modo que sea reversible.
- **F3:** `SIGKILL` al contenedor `db-a`.
- **F4:** `tc netem delay 2000ms loss 20%` sobre la interfaz de `app-a`, mediante un contenedor auxiliar que comparte el espacio de red (`--network container:app-a`, capacidad `NET_ADMIN`). Plan B: Toxiproxy.
- Registra `t_falla` en nanosegundos UTC **inmediatamente antes** de aplicar el efecto.
- El socket de Docker solo se monta en el inyector y en el runner, nunca en la aplicación ni en el orquestador. Documenta el riesgo.

### 7.9 Ejecutor del experimento (`experiments/runner`)

- `design.py` genera el diseño completo: 2 condiciones × 4 fallas × 30 réplicas, en **orden aleatorizado con semilla** configurable, y lo guarda en `data/design.csv` con `run_id`, `condition`, `fault`, `rep`, `seed`.
- `run_experiment.py` ejecuta **una corrida completa**: reiniciar entorno → verificar estado sano → iniciar carga → 5 min de estado estacionario → inyectar falla → (tratamiento: el orquestador actúa; control: entra el operador) → esperar recuperación (k = 10 éxitos consecutivos) o ventana de 15 min → 5 min de estabilización → detener carga → calcular RPO contra la base promovida → guardar datos crudos → desmontar.
- **Reanudable:** si se interrumpe, `--resume` salta las corridas ya completadas (detectadas por archivo de resultado) y reintenta la corrida incompleta desde cero.
- Modos: `--dry-run` (valida configuración sin tocar Docker), `--only run_id`, `--limit N`, `--smoke` (sección 9).
- Un registro `run_manifest.json` por corrida con versiones de imágenes, semilla, parámetros y marcas de tiempo.
- Parámetros de duración configurables en YAML (estado estacionario, estabilización, ventana máxima, k, umbrales) para poder acortarlos en pruebas.

### 7.10 Cálculo de métricas (`experiments/metrics`)

A partir de los datos crudos de cada corrida produce una fila en `data/processed/runs.csv` con al menos:
`run_id, condition, fault, rep, seed, operator_mode, t_fault, t_detect, t_recovered, rto_s, rto_censored, detect_s, promote_s, switch_s, rpo_tx_lost, rpo_s, n_requests, n_ok, availability, n_5xx, err_5xx_rate, n_conn_errors, err_total_rate, p95_ms_fault_window, p99_ms_fault_window, p95_ms_baseline, p99_ms_baseline, synthetic`.

Definiciones exactas (documentarlas también en `docs/METRICS.md`):
- **Éxito de una solicitud:** HTTP 2xx dentro del *timeout* del cliente.
- **Disponibilidad por corrida:** solicitudes exitosas / solicitudes totales en toda la corrida.
- **Tasa de 5xx:** 5xx (incluidos 502/503/504 del proxy) / solicitudes de la ventana de falla (`t_falla` hasta `t_recuperación`). Los errores de conexión y los *timeouts* se reportan aparte y se incluyen en `err_total_rate`.
- **RPO:** escrituras confirmadas con `201` que **no** aparecen en la base promovida; `rpo_s` es la diferencia entre la marca de tiempo de la última confirmada y la última presente.
- **Latencias:** percentiles sobre solicitudes exitosas, calculados con el mismo método (`numpy.percentile`, interpolación lineal), por ventana de falla y por línea base.

### 7.11 Análisis estadístico (`analysis/`)

Un solo comando (`make analyze`) lee `runs.csv` y genera tablas, figuras y un informe en `data/processed/`:

- Supuestos: Shapiro-Wilk de residuales y Levene; si fallan, errores robustos **HC3**, prueba de permutación o análisis de sensibilidad (t de Welch / Mann-Whitney por tipo de falla).
- **RTO:** `ols("np.log(rto_s) ~ C(condition) * C(fault)")` + ANOVA tipo II (`anova_lm`). Reporta el término de interacción.
- **RPO:** GLM binomial negativa (enlace log).
- **Disponibilidad:** GLM binomial (logit) con éxitos/fracasos por corrida, con ajuste cuasi-binomial si hay sobredispersión.
- **5xx:** prueba binomial exacta frente a 1 % (agregando solicitudes de la ventana de falla de las corridas de tratamiento).
- **Latencia p95/p99:** ANOVA factorial sobre el logaritmo.
- **Censura:** Kaplan-Meier (`statsmodels.duration.survfunc.SurvfuncRight`) y regresión de Cox (`PHReg`). Si la censura en control supera el 10 %, el análisis principal del RTO pasa a ser de supervivencia.
- Corrección de **Holm** para comparaciones múltiples; tamaño del efecto (**d de Cohen** y **delta de Cliff**); IC 95 % por *bootstrap* con **10 000 remuestreos** y semilla fija. Nivel de significancia 0,05.
- Figuras: cajas/violines de RTO por falla y condición, curvas de supervivencia, gráfico de interacción, latencias. Con ejes rotulados en español y exportadas en PNG y SVG a alta resolución.
- `export_excel.py` genera un `.xlsx` con una hoja de datos, una hoja de resumen y una hoja de **validación cruzada** con **fórmulas nativas** de Excel (promedio, desviación estándar muestral, percentil inclusivo, conteos) sobre las columnas clave, junto a los valores calculados en Python y la discrepancia relativa (aceptada: < 0,01 %). Escribe las fórmulas con los nombres en inglés que exige `openpyxl`; Excel las muestra en el idioma del usuario.
- `synthetic.py` genera datos falsos con la misma estructura **solo** para probar que el pipeline de análisis funciona antes de tener datos reales. Debe marcar `synthetic=true` y rechazar el análisis final si detecta esa marca, salvo que se use `--allow-synthetic`.

## 8. Buenas prácticas de ingeniería (aplican a todo el código)

- **Tipado completo** (`mypy --strict` sin errores) y docstrings claros en español en módulos y funciones públicas.
- **Separación de responsabilidades:** lógica de decisión pura y sin E/S; adaptadores (HAProxy, PostgreSQL, Docker, HTTP) detrás de interfaces (`Protocol`) para poder sustituirlos por dobles en pruebas. Inyección de dependencias, **reloj inyectable**.
- **Configuración** centralizada con validación; ningún número "mágico" en el código.
- **Errores:** excepciones propias y específicas; nada de `except Exception: pass`; los fallos se registran con contexto.
- **Logging estructurado** (JSON) con marca de tiempo UTC, nivel, componente y `run_id` cuando aplique.
- **Docker:** Dockerfile multi-etapa, usuario no root, `HEALTHCHECK`, imágenes base fijadas, `.dockerignore`. Compose con `depends_on` por condición de salud, reinicio controlado y redes separadas.
- **Seguridad básica:** sin credenciales en el repositorio, puertos publicados solo en `127.0.0.1`, mínimos privilegios y capacidades (solo `NET_ADMIN` donde haga falta).
- **Calidad automática:** `ruff check` y `ruff format`, `mypy`, `pytest --cov`, `pre-commit`. **CI en GitHub Actions** que corre lint, tipos y pruebas unitarias en cada *push* (las pruebas de integración con Docker se marcan y se ejecutan localmente con `make test-integration`).
- **Git:** historial limpio con **Conventional Commits**, un commit lógico por hito, `.gitignore` completo (Python, datos crudos, `.env`, `.venv`).
- **Documentación viva:** README con *quickstart* de 5 comandos; cada decisión importante en un ADR corto.

## 9. Estrategia de pruebas

1. **Unitarias (rápidas, sin Docker):** máquina de estados del orquestador (todas las transiciones, umbral de 3 fallos, éxito intermedio que reinicia el contador, fallo parcial entre instancias, latencia degradada), cálculo de RTO con k = 10, cálculo de RPO, cálculo de disponibilidad y percentiles, generación del diseño factorial (240 filas, 30 por celda, semilla reproducible), configuración inválida. **Cobertura mínima del 85 %** en la lógica del orquestador y de las métricas.
2. **Contrato:** pruebas de los endpoints de la aplicación (idempotencia de `POST /orders`, `/health` bajo BD caída, comportamiento en rol réplica).
3. **Integración con Docker (marcadas):** levantar el entorno completo; comprobar replicación; promover la réplica; cambiar el proxy por Runtime API; verificar que el proxy **no** conmuta por sí solo.
4. **Extremo a extremo "de humo" (`make smoke`):** 2 condiciones × 4 fallas × **1 réplica**, con duraciones acortadas por configuración (por ejemplo 60 s de estado estacionario, 90 s de ventana, 30 s de estabilización). Debe terminar solo, producir un `runs.csv` válido con 8 filas y pasar el análisis con `--allow-synthetic` desactivado (ya que los datos son reales, aunque pocos; el análisis de modelos puede omitirse con aviso si hay menos de 2 réplicas, pero el flujo no debe fallar).
5. **Prueba de cordura del experimento:** con el orquestador activo, F1 debe producir un RTO de decenas de segundos como máximo y cero duplicados; en control con operador simulado el RTO debe ser claramente mayor. Si el resultado contradice esto, **repórtalo y diagnostica**, no lo maquilles.
6. **Pruebas de caos del propio orquestador:** matar `db-b` durante el failover, retrasar el proxy y comprobar que el orquestador termina en un estado definido (`FAILOVER_ERROR`) y no queda colgado.

## 10. Comandos esperados (`Makefile`, delegando en los CLI de Python)

```
make setup              # entorno virtual, dependencias, pre-commit
make up                 # levanta todo y espera a que esté sano (< 120 s)
make down               # destruye contenedores y volúmenes
make lint test          # ruff + mypy + pruebas unitarias con cobertura
make test-integration   # pruebas con Docker
make smoke              # corrida de humo (8 corridas cortas)
make design             # genera data/design.csv (240 corridas aleatorizadas)
make run-all            # ejecuta todo el experimento, reanudable (--resume)
make run ID=<run_id>    # una corrida específica
make metrics            # calcula runs.csv desde los datos crudos
make analyze            # modelos, figuras, informe
make excel              # exporta el .xlsx con validación cruzada
make dashboards         # abre Grafana (127.0.0.1)
```

## 11. Forma de trabajo que debes seguir

1. **Primero el plan.** Antes de escribir código, entrégame un **plan de implementación** y una **lista de tareas** por hitos, y espera mi aprobación. Hitos sugeridos: (1) esqueleto y herramientas de calidad; (2) aplicación + BD + replicación; (3) proxy + monitoreo; (4) orquestador y sus pruebas unitarias; (5) inyector de fallas; (6) carga, runner y métricas; (7) control manual; (8) análisis y Excel; (9) pruebas de integración y humo; (10) documentación.
2. **Un hito a la vez.** Al terminar cada hito, ejecuta sus pruebas, muestra la salida real (no la resumas de memoria) y haz el commit antes de seguir.
3. **Verifica de verdad.** Levanta el entorno, ejecuta `make smoke` y revisa que los números tengan sentido. Si algo falla, diagnostica la causa raíz; no desactives pruebas ni bajes umbrales para que pasen.
4. **No inventes** APIs, flags ni versiones: si no estás seguro de un comando (por ejemplo de HAProxy Runtime API o de `pg_basebackup`), compruébalo en la documentación oficial o ejecutándolo.
5. **Pregunta solo lo imprescindible.** Si hay una ambigüedad menor, elige la opción más simple, regístrala en un ADR y sigue. Si la ambigüedad cambia el diseño experimental, detente y pregúntame.
6. **Al final entrega un informe de cierre** (*walkthrough*) con: qué se construyó, cómo ejecutarlo, evidencias (salida de pruebas, resultado de `make smoke`, captura del dashboard de Grafana), decisiones tomadas, limitaciones conocidas y cualquier desviación respecto a este prompt.

## 12. Criterios de aceptación (marca cada uno con evidencia)

- [ ] `make setup && make up` levanta N1, N2, proxy, orquestador y monitoreo sanos en menos de 120 s.
- [ ] La replicación asíncrona funciona y el retardo es visible en Grafana.
- [ ] El proxy **no** conmuta por sí solo; solo cambia por el orquestador o por el operador.
- [ ] Con el orquestador activo, las cuatro fallas (F1–F4) provocan failover automático y el servicio se recupera por N2.
- [ ] El orquestador detecta tras exactamente 3 sondas fallidas consecutivas y la línea de tiempo de eventos queda registrada.
- [ ] No hay *split-brain*: nunca aceptan escrituras ambas bases a la vez (hay una prueba que lo verifica).
- [ ] La condición de control funciona en modo `human` y en modo `simulated`, y se distingue en los datos.
- [ ] `make smoke` termina solo y genera un `runs.csv` válido con las 8 corridas.
- [ ] `make design` produce 240 corridas (30 por celda) con orden aleatorizado reproducible.
- [ ] `make analyze` y `make excel` funcionan; la validación cruzada de Excel muestra discrepancia < 0,01 %.
- [ ] `ruff`, `mypy --strict` y las pruebas unitarias pasan; cobertura ≥ 85 % en decisión y métricas; el CI está en verde.
- [ ] La documentación (README, ARCHITECTURE, EXPERIMENT_PROTOCOL, RUNBOOK_MANUAL, METRICS, LIMITATIONS, ADRs) está completa y coincide con lo implementado.
- [ ] Ningún secreto en el repositorio; versiones fijadas; todo reproducible con los comandos del README.

## 13. Qué NO debes hacer

- No usar servicios en la nube reales, cuentas ni tarjetas.
- No habilitar el failover automático del proxy ni de PostgreSQL por su cuenta (rompería el experimento).
- No fabricar ni "ajustar" resultados; no mezclar datos sintéticos con reales.
- No cambiar las definiciones de RTO, RPO, F1–F4, el número de réplicas (30), la carga (50 req/s, 70/30) ni el modelo estadístico sin preguntarme.
- No lanzar las 240 corridas completas sin que yo lo pida.
- No dejar código muerto, `TODO` sin dueño, ni pruebas deshabilitadas.

Empieza ahora entregando el **plan de implementación y la lista de tareas** (sección 11, punto 1).
