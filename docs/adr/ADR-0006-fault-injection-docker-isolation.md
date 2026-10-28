# ADR-0006: Estrategia de Inyección de Fallas y Aislamiento del Socket de Docker

## Estado
Aceptado

## Contexto
El diseño experimental factorial 2x4 requiere inyectar cuatro tipos de fallas reproducibles en la nube primaria (N1):
- **F1 (Caída de procesos de aplicación):** Emulación de fallo catastrófico del servicio web mediante terminación inmediata de procesos (`SIGKILL`).
- **F2 (Partición de red del plano de control):** Desconexión de los contenedores de N1 de la red `control_plane`, aislando la nube activa de las sondas y del tráfico de gestión sin alterar su estado interno.
- **F3 (Caída de la base de datos primaria):** Terminación abrupta del contenedor `db-a` mediante `SIGKILL`.
- **F4 (Degradación de enlace / red de aplicación):** Introducción de 2000 ms de latencia adicional y 20 % de pérdida de paquetes en el canal de comunicación de `app-a`.

Para manipular el ciclo de vida de los contenedores y las interfaces de red de Docker, se requiere acceso al daemon de Docker (`/var/run/docker.sock` o named pipe).

## Decisión
1. **Aislamiento Estricto del Socket de Docker:**
   - El socket de Docker se expone **únicamente** al módulo inyector de fallas (`services/fault_injector`) y al ejecutor de experimentos (`experiments/runner`).
   - El orquestador y la aplicación de referencia **nunca** tienen acceso ni montan el socket de Docker, garantizando que el orquestador actúe como un agente externo puro que solo percibe la salud del sistema a través de sondas HTTP y métricas de red.
2. **Estrategia por Falla:**
   - **F1:** Envío de señal `SIGKILL` a todos los contenedores de `app-a` mediante la API de Docker (`client.containers.get(name).kill(signal="SIGKILL")`).
   - **F2:** Desconexión controlada de la red `control_plane` (`client.networks.get(net).disconnect(container)`), lo cual es determinista y reversible.
   - **F3:** Envío de señal `SIGKILL` al contenedor `db-a`.
   - **F4:** Aplicación de `tc netem` (`tc qdisc add dev eth0 root netem delay 2000ms loss 20%`) mediante ejecución en el contenedor o contenedor auxiliar con capacidad `NET_ADMIN`.
3. **Marca Temporal de Falla ($t_{\text{falla}}$):**
   - La marca temporal $t_{\text{falla}}$ en nanosegundos UTC se captura e indexa **inmediatamente antes** de aplicar la perturbación en el cliente de Docker.
4. **Idempotencia de Restauración:**
   - Cada método de inyección tiene su contraparte `restore()` (arrancar contenedores, reconectar redes, eliminar reglas de `netem`), diseñada de forma idempotente para tolerar múltiples llamadas sin error.

## Consecuencias
- **Positivas:**
  - Control granular, determinista y automatizado del experimento.
  - La arquitectura respeta el principio de mínimos privilegios: el orquestador no tiene capacidades omniscientes ni privilegios de host.
  - Facilita pruebas unitarias mediante interfaces `Protocol` y mocks sin depender de un daemon real de Docker.
- **Riesgos y Mitigaciones:**
  - El acceso al socket de Docker otorga privilegios de nivel root sobre el host anfitrión.
  - Mitigación: El inyector y el runner se ejecutan en un entorno estrictamente local de investigación sin exposición a redes públicas y con nombres de contenedores y redes explícitamente parametrizados.
