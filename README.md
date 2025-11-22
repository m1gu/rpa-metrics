# RPA-Metrics Fase 1

## Requisitos iniciales
1. Crear un entorno virtual (opcional pero recomendado).
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
2. Instalar dependencias base.
   ```powershell
   pip install -r requirements.txt
   playwright install
   ```
3. Configurar variables de entorno.
   - Copiar `.env.example` a `.env`.
   - Ajustar credenciales/URLs cuando sea necesario. El archivo de ejemplo ya contiene los valores proporcionados para METRC y PostgreSQL.

## Arquitectura del codigo
- `src/config/settings.py`: centraliza carga de configuracion (Playwright, base de datos, runtime) y expone `settings`.
- `src/automation/robot.py`: clase `MetrcRobot` con el flujo completo de Playwright.
- `src/db/engine.py`, `src/db/models.py`, `src/db/repository.py`: engine + session_scope, definicion de tabla y operaciones (insert/update/fetch).
- `src/services/pipeline.py`: orquesta logging, ejecucion del robot y posterior insercion/actualizacion en base de datos.
- CLI: `src/cli/main.py` (ejecucion por defecto), `src/cli/metrc.py` (permite `--days`), `src/cli/smoke_test.py` (prueba rapida).

## Flujo automatizado actual (Fase 3)
- Navega a `https://me.metrc.com/industry/TF722/packages`, realiza login condicional y aplica dos filtros: `pro` sobre **Lab Test Status** y rango de fechas (ultimos 30 dias UTC) sobre la columna **Date**.
- Extrae cada fila como `dict` con los campos necesarios y persiste los registros en PostgreSQL (`public.metrc_sample_statuses`) mediante UPSERT sobre `(metrc_id, metrc_date, metrc_status)`.
- Guarda tambien el `raw_payload` en JSONB y actualiza `status_fetched_at` con `NOW()` en cada ejecucion.
- `src/services/pipeline.py` orquesta el flujo end-to-end y `src/cli/smoke_test.py` permite validar rapidamente el Tag del primer registro o informar cuando no hay datos.

## Ejecucion
```powershell
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
playwright install
python -m src.cli.main
# o especificar el rango dinamico
python -m src.cli.metrc --days 30
# compatibilidad con los entrypoints antiguos:
python main.py
python robot_metrc.py --days 30
```
El archivo `src/cli/smoke_test.py` se puede usar como smoke test rapido antes de correr la insercion completa.
