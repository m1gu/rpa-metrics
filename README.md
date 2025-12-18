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

## Contenedores (Docker)
### Build de la imagen
Usando el registro ACR compartido (ajusta el nombre si difiere):
```powershell
docker build -t mcrlabsacr1234.azurecr.io/rpa-metrics:latest .
```

### Probar localmente (reutilizando tu .env sin hornearlo)
```powershell
docker run --rm --env-file .env mcrlabsacr1234.azurecr.io/rpa-metrics:latest
```

### Push a Azure Container Registry
```powershell
az acr login -n mcrlabsacr1234
docker push mcrlabsacr1234.azurecr.io/rpa-metrics:latest
```

### Programar en Azure Container Apps Job (resumen)
Cron para 06:00 y 18:00 UTC:
```powershell
az containerapp job create `
  --name rpa-metrics-job `
  --resource-group <tuRG> `
  --environment <tuEnvCA> `
  --trigger-type Schedule `
  --cron-expression "0 6,18 * * *" `
  --image mcrlabsacr1234.azurecr.io/rpa-metrics:latest `
  --registry-server mcrlabsacr1234.azurecr.io `
  --registry-username <userACR> `
  --registry-password <pwdACR> `
  --cpu 1 --memory 2Gi `
  --parallelism 1 `
  --replica-timeout 1800 `
  --secrets metrc-username=<METRC_USERNAME> metrc-password=<METRC_PASSWORD> pg-password=<POSTGRES_PASSWORD> `
  --environment-variables `
      METRC_BASE_URL=https://me.metrc.com/industry/TF722/packages `
      METRC_USERNAME=secretref:metrc-username `
      METRC_PASSWORD=secretref:metrc-password `
      PLAYWRIGHT_HEADLESS=true `
      PLAYWRIGHT_SLOWMO_MS=0 `
      POSTGRES_HOST=<host> `
      POSTGRES_PORT=5432 `
      POSTGRES_DB=<db> `
      POSTGRES_USER=<user> `
      POSTGRES_PASSWORD=secretref:pg-password `
      POSTGRES_SCHEMA=public `
      POSTGRES_TABLE=metrc_sample_statuses `
      LOG_LEVEL=INFO `
      MAX_RETRIES=3 `
      RETRY_BACKOFF_SECONDS=5 `
      DATE_RANGE_DAYS=30 `
  --command "python" "robot_metrc.py" "--days" "30"
```
Los valores de entorno se inyectan como secretos (no uses `.env` dentro de la imagen). Ajusta `<tuRG>`, `<tuEnvCA>`, host/DB/usuario y credenciales de ACR.
