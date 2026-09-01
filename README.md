# HubSpot Master Service

A Python/FastAPI service that extracts data from HubSpot CRM, normalizes it into clean relational tables, and uploads to MinIO object storage. Designed to be called by a Coordinator service via HMAC-authenticated HTTP.

## Architecture

```
Coordinator (HMAC-signed HTTP) → FastAPI Service → HubSpot CRM v3 API
                                       ↓
                                  PostgreSQL (job tracking)
                                       ↓
                                  MinIO (normalized Parquet files)
```

**Supported HubSpot objects:** Contacts, Companies, Deals (+ associations/line items), Tickets, Owners

## Quick Start

### Prerequisites
- Docker & Docker Compose
- OR: Python 3.11+, PostgreSQL 15+, MinIO

### Using Docker Compose (recommended)

```bash
# Clone the repo
git clone <repo-url> && cd hubspot-master-service

# Copy env file and configure
cp .env.example .env
# Edit .env with your HubSpot credentials and HMAC keys

# Start all services
docker-compose up -d

# Service is now running at http://localhost:8000
# API docs at http://localhost:8000/docs
# MinIO console at http://localhost:9001 (minioadmin/minioadmin)
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Copy and configure env
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the service
uvicorn app.main:app --reload --port 8000
```

## Configuration

All settings via environment variables (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://hubspot_user:hubspot_pass@localhost:5432/hubspot_service` |
| `HMAC_ENABLED` | Enable HMAC auth | `true` |
| `HMAC_SECRET_KEY_CORE` | Coordinator HMAC key | (required in production) |
| `HMAC_SECRET_KEY_ENGINEER` | Read-only HMAC key | (optional) |
| `MINIO_ENDPOINT` | MinIO endpoint | `localhost:9000` |
| `MINIO_BUCKET` | Target bucket | `hubspot-data` |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check (unauthenticated) |
| `GET` | `/api/stats` | Service statistics (unauthenticated) |
| `POST` | `/api/scan/start` | Start a new extraction |
| `GET` | `/api/scan/{id}/status` | Check scan progress |
| `POST` | `/api/scan/{id}/pause` | Pause at next checkpoint |
| `POST` | `/api/scan/{id}/resume` | Resume from checkpoint |
| `POST` | `/api/scan/{id}/cancel` | Cancel scan |
| `GET` | `/api/scan/list` | List all scans |
| `DELETE` | `/api/scan/{id}/remove` | Delete scan + data |
| `POST` | `/api/normalization/{id}/normalize` | Normalize raw data to tables |
| `GET` | `/api/normalization/{id}/tables` | List normalized files |
| `POST` | `/api/validate-credentials` | Validate HubSpot token |
| `POST` | `/api/maintenance/cleanup` | Delete old scans |
| `POST` | `/api/maintenance/detect-crashed` | Flag stale jobs |
| `GET` | `/api/audit/logs` | Query audit logs |

## HMAC Authentication

All endpoints except `/api/health` and `/api/stats` require HMAC-signed requests:

```
Headers: X-HS-Signature, X-HS-Timestamp, X-HS-Client-ID, X-HS-Nonce
Canonical string: METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)
Signed with: HMAC-SHA256
```

- **Coordinator key** (`HMAC_SECRET_KEY_CORE`): full access
- **Engineer key** (`HMAC_SECRET_KEY_ENGINEER`): GET-only

Set `HMAC_ENABLED=false` for local development.

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## What's Built

- ✅ HubSpot OAuth + private-app auth with token refresh
- ✅ Cursor-based pagination through all CRM objects
- ✅ Rate limit handling (429 + Retry-After, separate from retry budget)
- ✅ Checkpoint-based pause/resume/crash-recovery
- ✅ Per-object normalizers → flat relational tables
- ✅ Parquet + JSON output, MinIO upload
- ✅ Full job state machine (PENDING→RUNNING→PAUSED→COMPLETED etc.)
- ✅ HMAC dual-key authentication with nonce replay protection
- ✅ Dead letter queue for exhausted retries
- ✅ Audit logging
- ✅ Docker + Compose deployment
- ✅ Comprehensive test suite

## What's Incomplete

- Webhook-based incremental sync (out of scope per design)
- PII masking/anonymization (explicitly excluded per §9)
- Deduplication/change detection (explicitly excluded per §9)
