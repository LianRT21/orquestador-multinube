# ADR-0004: Reverse Proxy de Capa 7 con HAProxy Runtime API y Desactivación de Health Checks Autónomos

## Estado
Aceptado

## Contexto
El diseño experimental de la investigación compara cuantitativamente dos condiciones de conmutación ante fallas:
1. **Control:** Recuperación manual por un operador humano siguiendo un runbook.
2. **Tratamiento:** Conmutación automática decidida y ejecutada exclusivamente por el orquestador de resiliencia.

La mayoría de los balanceadores de carga y proxies inversos de capa 7 (como HAProxy, NGINX o Envoy) cuentan con mecanismos nativos de *health checking* activo que, al detectar timeouts o códigos 5xx, marcan el servidor como `DOWN` y redirigen automáticamente el tráfico a otros servidores disponibles.

Si HAProxy realizara conmutación por su cuenta ante una falla inyectada en N1, la conmutación ocurriría a nivel de infraestructura sin intervención del orquestador ni del operador, contaminando de manera irrecuperable las variables de respuesta del experimento (RTO, tasa de errores y disponibilidad).

Además, recargar la configuración del proxy en disco (`haproxy -f ... -sf ...`) ante cada failover puede introducir pausas de milisegundos o pérdidas transitorias de sockets bajo alta concurrencia.

## Decisión
1. Se adopta **HAProxy 2.x** como proxy inverso de capa 7 debido a su rendimiento extremo y a su **Runtime API** basada en socket TCP.
2. **Desactivación total de health checks propios:** En la configuración `deploy/haproxy/haproxy.cfg`, las directivas `server app-a` y `server app-b` se configuran estrictamente **sin** la opción `check`.
3. Estado inicial: `app-a` está activo y enrutando tráfico; `app-b` está configurado pero deshabilitado (`disabled` / modo `maint`).
4. **Conmutación determinista vía Runtime API:** El orquestador (en tratamiento) o el script del operador (en control) se conectan al socket TCP `haproxy:9999` y emiten comandos en tiempo real:
   - `set server app_back/app-a state maint` (fencing inmediato de N1).
   - `set server app_back/app-b state ready` (habilitación inmediata de N2).
5. Estos comandos surten efecto en el microsegundo siguiente en la memoria del proceso de HAProxy, con cero recargas de proceso y cero pérdida de sockets.

## Consecuencias
- **Positivas:**
  - Garantía absoluta de validez interna experimental: ningún failover puede ocurrir sin una orden explícita del orquestador o del operador.
  - Tiempos de conmutación del proxy medibles con precisión submilisegundo (< 1 ms).
  - Auditoría transparente: los códigos 502/503 devueltos por HAProxy mientras N1 está caído representan fielmente la ventana de degradación experimental antes del switch.
- **Negativas / Mitigaciones:**
  - Si el orquestador fallara en decidir, HAProxy no conmutará solo y seguirá respondiendo 502/503.
  - Esto es precisamente lo deseado metodológicamente, permitiendo censurar el RTO a 900 s si la condición evaluada no logra recuperarse.
