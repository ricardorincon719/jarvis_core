# Auditoría de PEARL Core (`jarvis_core`), solo lectura

Fecha: **29 de septiembre de 2026**. Revisión estática del código, la configuración y
el despliegue, más la ejecución de la suite de pruebas. No se modificó implementación,
configuración, servicios ni datos, y no se hicieron pruebas activas contra el servicio
en producción.

Referencia: commit `7f40e1f Scope Jinnex Watch device sessions`, worktree limpio.
Unas 15.000 líneas Python (`core.py`: 2.502). Servicio `pearl-core` activo con el
servidor de desarrollo de Flask en `0.0.0.0:5004`.

**Pruebas:** 102 pasan con `unittest`, 0 fallos. `pytest` no está instalado en `.venv`.

## Dictamen

Hay dos vulnerabilidades **críticas explotables hoy desde internet**: el token maestro
efectivo es el valor por defecto publicado en el repositorio, y el PIN de
emparejamiento está fijo en el código. Deben corregirse antes que cualquier otra cosa.

### Contexto de exposición

`~/.cloudflared/config.yml` publica **todo** el puerto 5004 en
`pearl.pearlhome.com.br`, sin filtrar rutas. Las peticiones que llegan por el túnel
aparecen con `remote_addr = 127.0.0.1`, así que las comprobaciones de "IP local"
(`es_ip_local`) y "sólo loopback" dejan pasar a cualquier cliente de internet.

## Hallazgos

| # | Sev. | Hallazgo | Dónde |
|---|---|---|---|
| **P1** | **Crítica** | **El token maestro efectivo es el valor por defecto** que aparece en `core.py`, `.env.example` y `README.md`. El `.env` real usa ese mismo valor y el proceso no lo sobrescribe. Con él, cualquiera en internet obtiene acceso maestro: `/ask` (luces y plugins), `PUT /devices/<n>/local-key` (reemplazar claves Tuya), aprobar dispositivos y escenas, decidir acciones, etc. | `core.py:89,265-272,419-432` |
| **P2** | **Crítica** | **PIN fijo en el código fuente** y comparado sin tiempo constante. `/api/v1/auth/pin` emite una sesión de dispositivo de 30 días. `/api/v1/auth/jinnex-watch` también es accesible por el túnel y concede `nova.chat` y `codex.read` (ejecución de Codex en la máquina). `PEARL_JINNEX_WATCH_DEVICE_ALLOWLIST` está vacía. | `branches/auth/v1.0.0/plugin.py:8`, `core.py:1955-2060` |
| **P3** | **Alta** | **El bloqueo por intentos se puede saltar.** `auth_client_key` acepta la cabecera `X-Jinnex-Client-Key` de cualquier petición loopback, y por el túnel todas lo son: rotando la cabecera no hay límite. Sin la cabecera, todos los clientes de internet comparten la clave `127.0.0.1`, lo que permite bloquear el acceso de todos. | `core.py:315-356` |
| P4 | Alta | `CORS(app)` admite cualquier origen. Con el token público, cualquier página web visitada puede dar órdenes al Core desde el navegador en la red local. | `core.py:53` |
| P5 | Media | Servidor de desarrollo de Flask (`app.run`) en `0.0.0.0`; la unidad systemd no tiene endurecimiento (a diferencia de `jinnex-nova.service`). | `core.py:2502`, `~/.config/systemd/user/pearl-core.service` |
| P6 | Media | Las respuestas de error devuelven el texto de la excepción al cliente. | `core.py:574,1834,2006,2210` |
| P7 | Baja | `/ask` y `/ask_stream` imprimen en el log la consulta completa, la IP y el Host. | `core.py:1773-1775,1864-1866` |
| P8 | Baja | `auth_failures` y `device_signature_nonces` no son seguros entre hilos; `auth_failures` no se poda. | `core.py:158-159` |
| P9 | Baja | `test_env_example_secrets.py` no comprueba `JARVIS_SECRET_TOKEN`, por eso no detectó P1. | `tests/test_env_example_secrets.py:6` |
| P10 | Info | Código antiguo con `shell=True` (con `shlex.quote`) en `branches/music/v1.0.0`; no se carga porque el core usa `current/`. | `branches/music/v1.0.0/plugin.py:25` |

## Puntos fuertes

- Firma de dispositivo (RSA con timestamp y nonce anti-replay) en las rutas de escenas.
- Propuestas de acción con confirmación y caducidad.
- Nova sólo observa y no tiene autoridad sobre la ejecución.
- `.env` y `*.json` en `.gitignore`: no hay secretos versionados más allá de los valores por defecto.
- Tests de privacidad de respuestas y resiliencia de domótica.

## Plan de corrección (por orden)

1. **Rotar `JARVIS_SECRET_TOKEN`** a un valor aleatorio (`openssl rand -hex 32`) y
   reiniciar `pearl-core`. Eliminar el valor por defecto del código y exigir que exista.
2. **Sacar el PIN del código:** leerlo de `.env` (o guardarlo con hash) y compararlo con
   `hmac.compare_digest`.
3. **Limitar el túnel:** publicar sólo las rutas que usa la app, o proteger
   `pearl.pearlhome.com.br` con Cloudflare Access.
4. **Arreglar el bloqueo:** identificar al cliente con `CF-Connecting-IP` y aceptar
   `X-Jinnex-Client-Key` sólo con un secreto compartido con el puente Nova.
5. Restringir CORS al origen propio, rellenar la lista de relojes permitidos, usar
   gunicorn/waitress y añadir endurecimiento a la unidad systemd.
6. Añadir `JARVIS_SECRET_TOKEN` al test de secretos de `.env.example`.

## Relación con Jinnex Next

Ver `A_proyecto_nuevo/Jinnex_Next/docs/auditoria-2026-09-29.md`. El puente Nova
(puerto 5010) confía en las sesiones que emite este Core, así que P1–P3 también
comprometen la autenticación del reloj.
