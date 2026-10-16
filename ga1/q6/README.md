# GA1 - Q6 -- FastAPI Configuration Layering

## Task

Deploy a FastAPI service that merges multiple configuration layers with a defined precedence order, then applies query-parameter overrides with the highest precedence.

The configuration layers are:

```text
Defaults
   ↓
config.development.yaml
   ↓
.env
   ↓
OS environment variables
   ↓
Query parameter overrides
```

Higher layers override values from lower layers.

## Configuration Layers

### 1. Defaults

Hardcoded application defaults:

```yaml
port: 8000
workers: 1
debug: false
log_level: info
api_key: default-secret-000
```

### 2. Environment-specific YAML

`config.development.yaml`:

```yaml
workers: 13
debug: false
```

### 3. `.env`

```env
APP_PORT=8948
```

### 4. OS Environment Variables

Environment variables using the `APP_` prefix override the `.env` values.

For example:

```bash
export APP_PORT=8096
```

### 5. Query Parameter Overrides

The `/effective-config` endpoint accepts multiple `set` parameters.

Example:

```text
/effective-config?set=port=9000&set=debug=true&set=workers=2
```

These overrides have the highest precedence.

## Endpoint

```http
GET /effective-config
```

The service returns:

```json
{
  "port": 8000,
  "workers": 2,
  "debug": false,
  "log_level": "info",
  "api_key": "****"
}
```

The exact values depend on the active configuration layers and any query-parameter overrides.

## Type Coercion

The service applies the following conversion rules:

- `port` → integer
- `workers` → integer
- `debug` → boolean
- `log_level` and other values → string

For `debug`, the following values are treated as `true`:

```text
true
1
yes
on
```

Matching is case-insensitive.

## Special Cases

### Worker Alias

The `.env` variable:

```env
NUM_WORKERS=13
```

is treated as:

```text
workers=13
```

### API Key Masking

The actual `api_key` value is never returned by the API.

The response always contains:

```json
"api_key": "****"
```

### CORS

CORS is enabled so that the deployed endpoint can be accessed directly by the browser-based grader.

## Project Files

```text
q6/
├── README.md
├── app.py
├── config.development.yaml
├── .env
├── .gitignore
└── requirements.txt
```

The `.env` file is excluded from Git tracking because environment configuration may contain sensitive values.

## Local Testing

The service can be started with:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Base configuration

```bash
curl http://127.0.0.1:8000/effective-config
```

Expected result with the assigned environment variables:

```json
{
  "port": 8096,
  "workers": 13,
  "debug": false,
  "log_level": "info",
  "api_key": "****"
}
```

### Query parameter overrides

```bash
curl "http://127.0.0.1:8000/effective-config?set=port=9000&set=debug=true&set=workers=2"
```

Expected result:

```json
{
  "port": 9000,
  "workers": 2,
  "debug": true,
  "log_level": "info",
  "api_key": "****"
}
```

## Public Testing

The application was also tested through a temporary ngrok tunnel to verify that the FastAPI endpoint was publicly reachable.

The final submitted endpoint should use a persistent cloud deployment rather than the temporary local tunnel.

## Technologies

- Python
- FastAPI
- Uvicorn
- PyYAML
- python-dotenv
- ngrok for temporary public testing