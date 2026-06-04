# PEARL HOME Beta Final

Estado: diseño inicial
Fecha: 2026-06-04

## Objetivo

La beta final debe:

- mantener Core y nodos activos en segundo plano;
- conservar sesiones, conversaciones, recordatorios y escenas entre reinicios;
- proponer escenas mediante notificaciones Android con `Aceptar` y `Cancelar`;
- exigir confirmacion humana antes de ejecutar acciones fisicas;
- funcionar localmente sin depender de Internet.

No se eliminara por completo la autenticacion. El sistema recordara un celular autorizado
y permitira revocarlo sin pedir el PIN en cada apertura.

## Estado actual

- La laptop tiene `jarvis-music.service`, pero el orquestador de `:5006` no es servicio.
- Los servicios de usuario tienen `Linger=no`; paran al cerrar la ultima sesion.
- El Core movil guarda `api_sessions` solo en RAM. Reiniciarlo borra las sesiones.
- La web mantiene el token solo en JavaScript. Reabrirla exige autenticarse nuevamente.
- ARIA usa `SharedPreferences`, pero actualmente guarda el chat como `emptyList()`.
- Hay dos memorias de escenas: Core movil y orquestador laptop. Debe quedar una sola fuente
  de verdad para evitar estados inconsistentes.

## Arquitectura

```text
PEARL Client
  - interfaz, credencial protegida, WorkManager y notificaciones
          |
          v
PEARL Hub :5006 o PEARL Lite :5004
  - autenticacion, validacion, gateway y ejecucion confirmada
          |
          v
Servicios del Hub o del mismo equipo Lite
  - fuente unica de eventos, escenas y propuestas
          |
          +--> musica :5005
          +--> domotica
```

En la Beta Final, PEARL Hub sera la fuente unica de verdad de escenas. PEARL Lite
conservara una fuente local cuando opere sin Hub. PEARL Client sera la puerta de
interaccion y consentimiento, pero nunca ejecutara hardware directamente.

Las responsabilidades y reglas de migracion se definen en
[`product-editions.md`](product-editions.md).

## Segundo plano

### Laptop

Crear `pearl-hub.service` como servicio `systemd --user`:

- ejecuta `orchestrator.py --http`;
- usa `Restart=always`;
- guarda memoria en `~/.local/share/pearl-home/scene-memory`;
- registra logs en `journalctl --user`.

Activar una sola vez:

```bash
loginctl enable-linger samsung-ubuntu
```

Esto permite iniciar servicios sin abrir la sesion grafica. Puede pedir la contrasena de
administrador una vez.

### Celular

- Termux inicia el Core mediante Termux:Boot y adquiere `termux-wake-lock`.
- Android usa `WorkManager` para salud y propuestas pendientes.
- Un modo continuo opcional usa `ForegroundService` con notificacion permanente.
- Termux y PEARL HOME deben excluirse de la optimizacion de bateria.

Android no puede reiniciar automaticamente una app detenida con `Forzar detencion`.

## Memoria persistente

| Memoria | Propietario | Persistencia |
|---|---|---|
| Sesion del dispositivo | Core movil + Android | credencial revocable protegida |
| Conversacion y recordatorios | Android/Core movil | historial local limitado |
| Eventos y escenas | Orquestador laptop | JSON atomico versionado durante beta |
| Estado temporal | cada proceso | RAM descartable |

Reglas:

- no guardar datos duraderos solamente en variables globales;
- mover escenas fuera del repositorio y mantener respaldo;
- incluir `schema_version` para migraciones;
- limitar historial y eventos para evitar crecimiento indefinido;
- reparar ARIA para restaurar y guardar `memory.chatMessages`, no `emptyList()`.

## Sesion recordada

Primer ingreso:

1. El usuario introduce el PIN.
2. El Core crea una credencial aleatoria asociada a un `device_id`.
3. El Core guarda solo su hash, fecha, nombre y estado de revocacion.
4. Android guarda la credencial usando Android Keystore.
5. Las siguientes aperturas validan el dispositivo sin pedir el PIN.

La interfaz tendra `Cerrar sesion` y `Olvidar este dispositivo`. El PIN y los secretos
por defecto no deben formar parte de la beta distribuida.

## Propuestas de escena

Tipos:

- `candidate_approval`: una escena nueva fue aprendida. `Aceptar` la aprueba y `Cancelar`
  la rechaza.
- `activation_suggestion`: una escena aprobada coincide con el contexto. `Aceptar`
  solicita ejecutarla y `Cancelar` descarta solo esa propuesta.

Modelo minimo:

```json
{
  "id": "prompt_123",
  "kind": "activation_suggestion",
  "scene_id": "scene_123",
  "title": "Escena sugerida",
  "message": "Suele usar jazz y luz calida a esta hora. ¿Activar?",
  "status": "pending",
  "created_at": "2026-06-04T18:00:00-03:00",
  "expires_at": "2026-06-04T18:30:00-03:00"
}
```

Contratos nuevos del Core movil:

```text
GET  /api/v1/scene-prompts/pending
POST /api/v1/scene-prompts/<prompt_id>/decision
     {"decision": "accept" | "cancel", "idempotency_key": "..."}
```

Las decisiones deben ser idempotentes: repetir un toque nunca ejecuta dos veces.

## Notificaciones Android

Componentes:

- `SceneSuggestionWorker`: consulta propuestas pendientes aproximadamente cada 15 minutos;
- `SceneNotificationManager`: canal `scene_suggestions`;
- `SceneDecisionReceiver`: procesa `Aceptar` y `Cancelar`;
- `ScenePromptStore`: recuerda propuestas mostradas y decisiones por sincronizar.

Flujo:

1. `WorkManager` consulta el Core movil.
2. La app muestra una notificacion con dos acciones.
3. El receptor envia la decision al Core.
4. El Core valida sesion, expiracion, escena y acciones permitidas.
5. Solo una aceptacion valida puede ejecutar una escena aprobada.
6. La app actualiza la notificacion con el resultado.

La app solicitara `POST_NOTIFICATIONS` en Android 13 o superior. Los `PendingIntent`
seran unicos e inmutables.

## Seguridad

- IA propone, humano confirma, Core valida, nodos ejecutan.
- Ninguna escena aprendida tiene `auto_execute=true`.
- Aprobar una escena candidata no la ejecuta.
- Ejecutar una escena aprobada requiere otra confirmacion.
- El Core solo acepta acciones incluidas en una lista permitida.
- Decisiones vencidas se rechazan y tokens completos nunca se registran en logs.

## Plan de entrega

### Fase 0: estabilizar datos

- reparar persistencia del historial ARIA;
- migrar a una memoria canonica de escenas;
- agregar respaldo, version de esquema y pruebas de reinicio.

### Fase 1: procesos persistentes

- crear y habilitar `pearl-hub.service`;
- activar `linger` en laptop;
- validar Termux:Boot, wake lock y recuperacion del Core.

### Fase 2: dispositivo recordado

- reemplazar sesiones en RAM por credenciales revocables;
- integrar almacenamiento protegido Android;
- agregar cierre de sesion y revocacion.

### Fase 3: propuestas y decisiones

- crear propuestas persistentes;
- implementar endpoints idempotentes;
- validar aprobacion, descarte y ejecucion confirmada.

### Fase 4: notificaciones

- implementar Worker, canal, receptor y botones;
- manejar Core sin conexion, reintentos y resultados.

### Fase 5: cierre beta

- probar reinicios de laptop, celular, Core y app;
- probar expiracion, doble toque y perdida de red;
- instalar APK beta y ejecutar lista de verificacion.

## Criterios de aceptacion

- Reiniciar laptop inicia musica y orquestador sin abrir sesion grafica.
- Reiniciar celular recupera Core y conserva el dispositivo autorizado.
- Cerrar y abrir app no borra conversaciones, recordatorios ni escenas.
- Una propuesta no genera notificaciones duplicadas.
- `Aceptar` ejecuta como maximo una vez y solo escenas aprobadas.
- `Cancelar` nunca ejecuta acciones.
- Ninguna salida libre de un modelo controla directamente musica o domotica.
