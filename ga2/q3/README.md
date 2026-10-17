# GA2 Q3 - FastAPI Statistics API with CORS

## Task

Build and deploy a FastAPI service that computes descriptive statistics for a dynamically supplied batch of integers and enforces a strict per-origin CORS policy.

The grader sends a fresh batch of random integers on every check, so the service must calculate the statistics dynamically rather than return hard-coded values.

## Endpoint

```text
GET /stats?values=1,2,3,...
```

The `values` query parameter contains comma-separated integers.

Example:

```text
/stats?values=10,20,30,40
```

The service returns:

```json
{
  "email": "<your-email>",
  "count": 4,
  "sum": 100,
  "min": 10,
  "max": 40,
  "mean": 25.0
}
```

The `mean` value must be accurate within ±0.01 of the true mean.

The `email` field must contain the exact email address associated with the logged-in TDS account.

## CORS Policy

Only the assigned origin is allowed:

```text
https://dash-kkv6vn.example.com
```

The service must **not** use a wildcard CORS policy such as:

```text
Access-Control-Allow-Origin: *
```

### Allowed Origin

A preflight `OPTIONS /stats` request from the assigned origin must succeed and include the appropriate:

```text
Access-Control-Allow-Origin
```

header.

### Other Origins

A preflight request from any other origin must not receive an `Access-Control-Allow-Origin` header.

## Required Response Headers

Every response must include:

### `X-Request-ID`

A unique identifier for the request, such as a UUID.

Example:

```text
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
```

### `X-Process-Time`

The handler duration in seconds as a non-negative decimal number.

Example:

```text
X-Process-Time: 0.001234
```

## Validation

The grader checks:

- Preflight request from the allowed origin receives the CORS header.
- Preflight request from an unauthorized origin does not receive the CORS header.
- `GET /stats` correctly calculates statistics for fresh random integer batches.
- `email` exactly matches the logged-in account email.
- `X-Request-ID` is present and unique per request.
- `X-Process-Time` is present and contains a non-negative numeric value.

## Deployment

The FastAPI service must be publicly accessible through a deployed HTTP(S) endpoint.

The final submission should provide the base URL of the deployed service.

## Project Structure

```text
q7/
├── README.md
├── app.py
├── requirements.txt
└── .gitignore
```

## Development Flow

```text
Implement
    ↓
Test statistics locally
    ↓
Test allowed CORS origin
    ↓
Test rejected CORS origin
    ↓
Verify required headers
    ↓
Deploy publicly
    ↓
Test deployed endpoint
    ↓
Submit base URL
```