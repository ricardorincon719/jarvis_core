# Ediciones de PEARL HOME

Version inicial compartida: `0.7.0-beta.1`

PEARL usa versionado semantico:

```text
MAJOR.MINOR.PATCH-prerelease
```

- `MAJOR`: contratos incompatibles.
- `MINOR`: capacidades nuevas compatibles.
- `PATCH`: correcciones compatibles.
- `beta.N`: entrega previa a la version estable.

## PEARL Lite

Despliegue portable y minimo en Android/Termux o un equipo basico.

Responsabilidades:

- ejecutar Core, luces, musica y escenas simples en un solo equipo;
- ofrecer IA local o cloud basica;
- seguir funcionando sin Hub para pruebas personales;
- permitir migrar configuracion y memoria hacia Hub.

## PEARL Hub

Cerebro central de la casa y producto principal de la Beta Final.

Responsabilidades:

- operar 24/7;
- coordinar nodos, sensores y automatizaciones;
- mantener la fuente canonica de memoria y escenas;
- validar propuestas antes de ejecutar acciones;
- exponer contratos estables bajo `/api/v1`;
- permitir modulos Zigbee, Matter, Tuya, energia e IA.

## PEARL Client

App de control y consentimiento. No es el cerebro y no controla hardware directamente.

Responsabilidades:

- registrar un dispositivo autorizado;
- mostrar estado y capacidades del Hub o Lite;
- controlar la casa mediante contratos validados;
- recibir propuestas y notificaciones;
- aceptar o cancelar acciones.

## Reglas de compatibilidad

- Lite y Hub implementan el mismo contrato base cuando comparten una capacidad.
- Client descubre capacidades; no asume que todos los despliegues tienen los mismos modulos.
- Los endpoints existentes se conservan durante la Beta; los contratos estables nuevos usan `/api/v1`.
- Una salida libre de IA nunca se convierte directamente en una accion fisica.
- GitHub almacena codigo, documentos, esquemas y configuracion de ejemplo.
- Tokens, conversaciones, memoria real y datos del hogar permanecen fuera de Git.

## Migracion Lite a Hub

1. Instalar Hub y verificar `/api/v1/health`.
2. Exportar datos de Lite con una version de esquema declarada.
3. Importar y validar memoria en Hub.
4. Registrar Client contra Hub.
5. Mantener Lite como respaldo hasta comprobar escenas y dispositivos.
6. Revocar credenciales antiguas cuando termine la migracion.
