# Roadmap RPA Web ➜ PostgreSQL

## Fase 1 · Fundaciones del robot
- **Objetivo**: preparar entorno Python, definir dependencias (Playwright, SQLAlchemy/psycopg2, loggers) y establecer variables de entorno para credenciales y DSN. Crear `robot.py` con estructura básica (abrir navegador, placeholders para pasos). Configurar `db.py` con utilidades de conexión y manejo de sesiones/cursores. Armar `main.py` con esqueleto de orquestación y logging centralizado.
- **Entregable**: repositorio con módulos esqueléticos, requirements y guía breve para ejecutar `playwright install` y configurar `.env`.
- **Recomendaciones de revisión**: verificar soporte para múltiples entornos (dev/prod), chequear que credenciales no se versionen, confirmar que los logs se roten o limiten tamaño.

## Fase 2 · Automatización y extracción de datos
- **Objetivo**: implementar en `robot.py` el flujo real: login condicional, navegación a la tabla, aplicación de filtros y espera explícita de la tabla. Extraer filas como lista de dicts validando encabezados dinámicos y manejando timeouts/reintentos.
- **Entregable**: `robot.py` funcional + pruebas manuales (video corto o capturas de la tabla filtrada) + documento con selectores/estrategia de espera.
- **Recomendaciones de revisión**: validar robustez de selectores ante cambios menores de UI, medir tiempos promedio, incluir mecanismos de screenshot/logs en fallos.

## Fase 3 · Persistencia, monitoreo y endurecimiento
- **Objetivo**: completar `db.py` con inserciones batch/UPSERT, transacciones y validaciones de schema; integrar en `main.py` el flujo completo (robot ➜ base de datos) con manejo de excepciones y retires. Añadir configuraciones para ejecución programada (task scheduler/cron) y métricas básicas (tiempos, conteo de filas).
- **Entregable**: pipeline end-to-end funcionando localmente guardando datos en PostgreSQL + script/README para correr el robot y revisar tablas.
- **Recomendaciones de revisión**: probar con datos edge (tabla vacía/cambios de columnas), monitorear consumo de recursos, preparar check-list de smoke test previo a ejecución programada.
