# 06 — API Contract Specification

## Base URL

- Development: `http://localhost:8000/api/v1`
- Production: `https://app.clarifi.ai/api/v1`

## Authentication

All protected endpoints require `Authorization: Bearer <access_token>` header.

Refresh tokens are stored as `HttpOnly`, `Secure`, `SameSite=Strict` cookies.

---

## Error Response Format

All errors follow a consistent shape:

```json
{
  "error": "ValidationError",
  "detail": "Email is already registered",
  "request_id": "req_abc123"
}
```

| HTTP Code | Error Type | When |
|-----------|-----------|------|
| 400 | `BadRequest` | Malformed request |
| 401 | `AuthenticationError` | Invalid/expired token |
| 403 | `AuthorizationError` | Valid token, insufficient permissions |
| 404 | `NotFoundError` | Resource doesn't exist |
| 409 | `ConflictError` | Duplicate email/username |
| 413 | `FileTooLargeError` | Upload exceeds limit |
| 422 | `ValidationError` | Schema validation failure |
| 429 | `RateLimitExceeded` | Too many requests |
| 500 | `InternalError` | Unexpected server error |

---

## Auth Endpoints

### `POST /auth/register`

```
Request:
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "SecurePass1!",
  "confirm_password": "SecurePass1!"
}

Response (201):
{
  "user": { "id": "uuid", "email": "user@example.com", "username": "johndoe", "is_active": true, "created_at": "ISO8601" },
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
+ Set-Cookie: clarifi_refresh=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth
```

### `POST /auth/login`

```
Request:
{ "email": "user@example.com", "password": "SecurePass1!" }

Response (200): Same shape as register
```

### `POST /auth/refresh`

```
Request: (cookie-based, no body)
Response (200):
{ "access_token": "eyJ...", "token_type": "bearer", "expires_in": 900 }
+ Updated refresh cookie
```

### `POST /auth/logout`

```
Response (204): No body
+ Cleared refresh cookie
```

### `GET /auth/me` (Protected)

```
Response (200):
{ "id": "uuid", "email": "...", "username": "...", "is_active": true, "created_at": "ISO8601" }
```

---

## Dataset Endpoints

### `POST /datasets/upload` (Protected)

Uploads a file, stores it, returns parsed preview.

```
Request: multipart/form-data
  file: <binary>

Response (201):
{
  "dataset_id": "uuid",
  "filename": "employees.csv",
  "headers": ["name", "email", "department", "salary"],
  "rows": [ { "name": "John", "email": "john@co.com", ... }, ... ],  // first 200 rows
  "total_rows": 5000,
  "total_columns": 4
}
```

### `POST /datasets/{id}/analyze` (Protected)

Triggers async analysis. Returns job ID for progress tracking.

```
Response (202):
{
  "job_id": "uuid",
  "status": "pending",
  "ws_url": "/api/v1/jobs/ws/{job_id}"
}
```

### `GET /datasets/{id}/analysis` (Protected)

Returns the latest analysis result (cached).

```
Response (200):
{
  "dataset_meta": { "filename": "...", "total_rows": 5000, "total_columns": 4 },
  "overall_quality_score": 73,
  "executive_summary": "Dataset has moderate quality issues...",
  "category_breakdown": {
    "completeness": 85,
    "uniqueness": 100,
    "consistency": 62,
    "accuracy": 70,
    "format": 80
  },
  "issues": [
    {
      "inspector_name": "Missing Values",
      "category": "completeness",
      "severity": "warning",
      "column": ["salary"],
      "count": 47,
      "description": "Column 'salary' has 47 missing values (0.9%)",
      "suggestion": "Fill with column median.",
      "affected_cells": [ { "row": 12, "column": "salary", "value": null }, ... ]
    }
  ]
}
```

### `POST /datasets/{id}/autofix` (Protected)

Triggers async autofix. Returns job ID.

```
Response (202):
{
  "job_id": "uuid",
  "status": "pending",
  "ws_url": "/api/v1/jobs/ws/{job_id}"
}
```

### `GET /datasets/{id}/autofix-result` (Protected)

Returns autofix result after job completes.

```
Response (200):
{
  "headers": ["name", "email", ...],
  "rows": [ ... ],                  // Clean rows
  "clean_count": 4850,
  "quarantine_headers": ["name", "email", ..., "_issue_reason"],
  "quarantine_rows": [ ... ],       // Rows needing human attention
  "quarantine_count": 150,
  "changes": [
    { "row": 0, "column": "email", "old_value": "JOHN@GMIAL.COM", "new_value": "john@gmail.com", "kind": "fixed", "reason": "Email normalized" },
    ...
  ],
  "changes_applied": 342
}
```

### `POST /datasets/{id}/export` (Protected)

```
Request:
{
  "format": "csv",                    // "csv" | "xlsx" | "json" | "tsv"
  "include_quarantine": false,
  "headers": ["name", "email", ...],
  "rows": [ ... ]                     // Current state from frontend
}

Response: Binary file download with appropriate Content-Type
```

### `GET /datasets/{id}/rows` (Protected)

Paginated row access for large datasets.

```
Query params: ?offset=0&limit=200&search=john

Response (200):
{
  "headers": [...],
  "rows": [...],
  "total_rows": 5000,
  "offset": 0,
  "limit": 200
}
```

---

## History Endpoints

### `GET /history?limit=20&offset=0` (Protected)

```
Response (200):
[
  {
    "id": "uuid",
    "filename": "employees.csv",
    "original_format": "csv",
    "row_count": 5000,
    "column_count": 4,
    "latest_quality_score": 73,
    "created_at": "ISO8601"
  }
]
```

### `DELETE /history/{id}` (Protected)

```
Response (204): No body
```

---

## Job Endpoints

### `GET /jobs/{id}` (Protected)

```
Response (200):
{
  "id": "uuid",
  "job_type": "analyze",
  "status": "running",
  "progress": 65,
  "created_at": "ISO8601",
  "started_at": "ISO8601"
}
```

### `WebSocket /jobs/ws/{id}`

Server pushes JSON messages:

```json
{ "status": "running", "progress": 45, "message": "Running outlier detection..." }
{ "status": "running", "progress": 80, "message": "Scoring..." }
{ "status": "completed", "progress": 100 }
```

Or on error:
```json
{ "status": "failed", "progress": 45, "error": "Out of memory processing file" }
```

---

## Rate Limits

| Endpoint Pattern | Limit | Window |
|-----------------|-------|--------|
| `POST /auth/login` | 10 | 1 minute |
| `POST /auth/register` | 5 | 1 minute |
| `POST /datasets/upload` | 10 | 1 minute |
| `POST /datasets/*/analyze` | 5 | 1 minute |
| `POST /datasets/*/autofix` | 5 | 1 minute |
| All other endpoints | 60 | 1 minute |

Rate limit headers on every response:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1700000000
```

---

## Versioning Strategy

- URL prefix: `/api/v1/`, `/api/v2/`
- Major version = breaking changes (removing fields, changing semantics)
- Minor additions (new optional fields) don't require new version
- Deprecation headers: `Sunset: Sat, 01 Jan 2027 00:00:00 GMT`
- Maintain v1 for 6 months after v2 launch
