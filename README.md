# Bestin backend

FastAPI product backend for Bestin: admins upload books, readers ask grounded questions by text or voice, and the AI service supplies speech and lip-sync data. The browser talks only to this backend; it stores users, books, conversations and citations in PostgreSQL (or development SQLite), stores uploads locally, and calls bestin-ai over HTTP with a shared internal token. See [the API contract](docs/API_CONTRACT.md) for endpoints and response shapes. Interactive API documentation is available at `/docs`.

## Setup

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and optionally PostgreSQL. On macOS arm64:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
cp .env.example .env
./scripts/dev.sh
```

The service listens on port 8000. Start bestin-ai on port 8001 separately. The default database is `postgresql+psycopg://bestin:bestin@localhost:5432/bestin`; create the database and role if needed. With `DB_FALLBACK_SQLITE=true`, an unreachable PostgreSQL server causes a warning and uses `data/bestin.db` instead. Set it to `false` where silently switching databases is undesirable. `/health` reports the actual database and AI connectivity.

Migrations run automatically at startup, before the admin is seeded. To run them manually against `DATABASE_URL`, use `.venv/bin/alembic upgrade head`. Back up persistent data before migrations. The development admin is `admin@bestin.local` / `admin12345`; set `ADMIN_EMAIL` and `ADMIN_PASSWORD` before first startup. Seeding only creates a missing account; changing the environment does not reset an existing password unless `ADMIN_RESET_PASSWORD_ON_START=true`. Set it back to `false` after an intentional reset. Change the JWT secret and credentials for any shared deployment.

## Configuration and providers

All settings are documented in [.env.example](.env.example). `AI_INTERNAL_TOKEN` must match bestin-ai. `CORS_ORIGINS` is a comma-separated allowlist, and `STORAGE_DIR` should be backed up together with the database. The backend itself requires no external API keys. bestin-ai can run with its keyless fallbacks; optional provider keys are configured in that service, not here. Free provider signup: [Groq](https://console.groq.com/keys) and [Google AI Studio](https://aistudio.google.com/apikey). OpenAI is optional: [API keys](https://platform.openai.com/api-keys); usage may incur charges.

Uploaded books are limited to PDF, EPUB, TXT and Markdown, and covers are converted to WebP. If the initial AI ingestion request fails, the upload and its local record are removed. If an accepted ingestion later fails, the admin can retry it using reingest. Deletion requires the AI service to respond before local files and records are removed. Book availability for readers requires both a ready ingestion status and publication. AI status is refreshed on reads and periodically in the background; a temporary AI outage preserves the last known status. Admin-edited suggested questions take precedence over AI suggestions. Conversations belong to their creator, and deleting a book removes its conversations and messages. The seven-day statistics use UTC calendar dates.

Users can change their name or password through `PATCH /api/auth/me`. Admins can change a user’s role or active status through `PATCH /api/admin/users/{id}`. API responses include `X-Request-ID` for correlating requests with access logs.

## Tests

```sh
.venv/bin/pytest -q
TEST_DATABASE_URL='postgresql+psycopg://bestin:bestin@localhost:5432/bestin_test' .venv/bin/pytest -q
python3 .github/scripts/malware-check.py
.venv/bin/ruff check .
```

The PostgreSQL test database is destructive: the suite drops its product tables before each test. Never point it at a real database. AI responses are mocked in tests.

## Troubleshooting

- Check `/health` and the startup logs for database fallback or an unreachable AI service. Verify PostgreSQL credentials, the AI URL, and the shared token.
- `502 ai_unavailable` means the AI service could not be reached or returned a server error. Check the AI service local transcription model if voice input is unavailable.
- If a book fails ingestion, inspect its error in admin and retry after fixing the AI service. Check `MAX_UPLOAD_MB`, file extension, and storage permissions for upload errors.
- SQLite fallback is a separate database, not a replica; restore PostgreSQL connectivity before expecting its data to appear.

## Verified

On 2026-11-19, the automated suite passed against SQLite and the dedicated PostgreSQL `bestin_test` database. A local end-to-end smoke used PostgreSQL and the runnable sibling AI service: admin login and a TXT upload succeeded, ingestion reached ready, and a `speak=true` question returned an extractive answer with one citation and speech. The conversation contained both stored messages. Both test servers were stopped afterwards. The smoke used isolated temporary storage; external provider availability can change.
