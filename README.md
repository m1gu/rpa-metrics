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
- `config.py`: centraliza carga de configuracion (Playwright, base de datos, runtime). Usa `.env` automaticamente.
- `robot.py`: clase `MetrcRobot` con flujo completo del navegador (placeholders para login, navegacion y extraccion listos para Fase 2).
- `db.py`: crea `engine`, `session_scope` y placeholder `insert_rows` que se completara en Fase 3.
- `main.py`: orquesta logging, ejecucion del robot y posterior insercion en base de datos.
- `robot_metrc.py`: CLI que permite ejecutar el pipeline definiendo en tiempo de ejecucion el numero de dias para el filtro de fechas (`python robot_metrc.py --days 180`).

## Flujo automatizado actual (Fase 3)
- Navega a `https://me.metrc.com/industry/TF722/packages`, realiza login condicional y aplica dos filtros: `pro` sobre **Lab Test Status** y rango de fechas (ultimos 30 dias UTC) sobre la columna **Date**.
- Extrae cada fila como `dict` con los campos necesarios y persiste los registros en PostgreSQL (`public.metrc_sample_statuses`) mediante UPSERT sobre `(metrc_id, metrc_date, metrc_status)`.
- Guarda tambien el `raw_payload` en JSONB y actualiza `status_fetched_at` con `NOW()` en cada ejecucion.
- `main.py` orquesta el flujo end-to-end y `test_robot.py` permite validar rapidamente el Tag del primer registro o informar cuando no hay datos.

## Ejecucion
```powershell
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
playwright install
python main.py
# o especificar el rango dinamico
python robot_metrc.py --days 180
```
El archivo `test_robot.py` se puede usar como smoke test rapido antes de correr la insercion completa.
