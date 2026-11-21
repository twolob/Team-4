# FastAPI Project - Backend

## Requirements

* [Docker](https://www.docker.com/).
* [uv](https://docs.astral.sh/uv/) for Python package and environment management.

## Local Development

AgTrack defaults to SQLite at `backend/agtrack.db`. Run commands from this backend folder. Set `DATABASE_URL=sqlite:///./agtrack.db` in `../.env` if that file already specifies PostgreSQL. Also configure `PROJECT_NAME=AgTrack`, `SECRET_KEY`, `FIRST_SUPERUSER`, and `FIRST_SUPERUSER_PASSWORD`.

```powershell
uv sync
uv run alembic upgrade head
uv run python -m app.initial_data
uv run fastapi dev app/main.py
```

Open http://localhost:8000/docs to register and sign in. SQLite requires no database service. Existing PostgreSQL data stays in its original database when switching the URL.

## General Workflow

Run backend commands from `./backend/` with `uv run`. Make sure your editor uses the Python interpreter at `.venv/bin/python` in the project root.

Modify or add SQLModel models for data and SQL tables in `./backend/app/models.py`, API endpoints in `./backend/app/api/`, CRUD (Create, Read, Update, Delete) utils in `./backend/app/crud.py`.

## VS Code

There are already configurations in place to run the backend through the VS Code debugger, so that you can use breakpoints, pause and explore variables, etc.

The setup is also already configured so you can run the tests through the VS Code Python tests tab.

## Full Stack with Docker Compose

To run the backend and built frontend in Docker Compose:

```console
$ docker compose run --rm backend bash scripts/prestart.sh
$ docker compose watch
```

The application is available at `http://localhost:8000`.

### Docker Compose Override

The `compose.override.yml` file contains local settings for published ports, source synchronization, automatic image rebuilds, and backend reloads. Docker Compose applies it automatically when you run `docker compose` without an explicit file list.

To open a shell in the backend container:

```console
$ docker compose exec backend bash
```

## Backend Tests

To test the backend from the `backend` directory, run:

```console
$ uv run bash scripts/test.sh
```

The tests run with Pytest. Modify existing tests or add new ones in `./backend/tests/`.

If you use GitHub Actions, the tests will run automatically.

### Test a Running Stack

If your stack is already up and you just want to run the tests, you can use:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

The `/app/backend/scripts/tests-start.sh` script calls `pytest`. If you need to pass extra arguments to `pytest`, you can pass them to that command and they will be forwarded.

For example, to stop on first error:

```bash
docker compose exec backend bash scripts/tests-start.sh -x
```

### Test Coverage

When the tests run, they generate `htmlcov/index.html`. Open it in your browser to inspect the test coverage.

## Migrations

Make sure you create a revision of your models and upgrade the database with that revision every time you change them. From the `backend` directory, use `uv` to run Alembic against the PostgreSQL container:

* Alembic is already configured to import your SQLModel models from `./backend/app/models.py`.

* After changing a model (for example, adding a column), create a revision:

```console
$ uv run alembic revision --autogenerate -m "Add column last_name to User model"
```

* Commit to the git repository the files generated in the alembic directory.

* After creating the revision, run the migration in the database (this is what will actually change the database):

```console
$ uv run alembic upgrade head
```

If you don't want to use migrations at all, uncomment the lines in the file at `./backend/app/core/db.py` that end in:

```python
SQLModel.metadata.create_all(engine)
```

and comment the line in the file `scripts/prestart.sh` that contains:

```console
$ alembic upgrade head
```

If you don't want to start with the default models and want to remove them / modify them, from the beginning, without having any previous revision, you can remove the revision files (`.py` Python files) under `./backend/app/alembic/versions/`. And then create a first migration as described above.

## Email Templates

The email templates are written with [React Email](https://react.email) in `./packages/react-email/`. The `emails` directory holds one component per email and the `ui` directory holds the shared components (layout, heading, button, link, callout).

The rendered HTML in `./backend/app/email-templates/` is generated from those components. It is what the application sends and should not be edited by hand.

To preview the emails while editing them, start the dev server from the root of the project:

```console
$ bun run email:dev
```

Values coming from the backend are declared as Jinja placeholders in the component props, for example `username = "{{ username }}"`. The context for each email is built in `generate_*_email()` in `./backend/app/utils.py`, so a new placeholder needs to be added there too.

Once you are done, regenerate the templates used by the application:

```console
$ bun run email:export
```

## AgTrack database migrations

Run these commands from the backend folder after configuring `../.env`. SQLite is the default.

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run python -m app.initial_data
```

The migration chain creates nine application tables, including unique email and phone indexes, UUID keys, and farm ownership. Existing email accounts are preserved. The latest revision is `ffd35e3b17e8`.

When changing SQLModel table definitions, generate and review a migration before applying it.

```powershell
uv run alembic revision --autogenerate -m "describe schema change"
uv run alembic upgrade head
uv run alembic check
```

To inspect upgrade SQL without connecting to PostgreSQL, use `uv run alembic upgrade head --sql` for PostgreSQL. SQLite batch migrations require an online connection. Configuration is still required. Downgrading the phone-account migration requires every account to have an email. Its guard prevents dropping phone data while phone-only accounts exist.

## Farm management API

All routes use `/api/v1`. Authenticate using `POST /login/access-token` with form fields `username` (email or international phone number) and `password`. Send the returned token as `Authorization: Bearer <token>`. Swagger UI is available at `/docs`. Public response models omit password hashes.

Farmers access records owned through their farms. Superusers can manage accessible records across farms. Unauthorized farm resources return 404. Existing item endpoints retain their established 403 permission response. The development-only `/private/users/` endpoint now requires a superuser token.

### Database overview

| Model | Relationships and purpose |
|---|---|
| User | Owns farms and items, existing email/phone authentication |
| Farm | Belongs to User, holds inventory, expenses, harvests, losses and reports |
| Item | Belongs to User and optionally Farm, has stock transactions |
| InventoryTransaction | Belongs to Item, immutable stock ledger |
| FarmExpense | Belongs to Farm, decimal LRD or USD expense |
| Harvest | Belongs to Farm, links batch events and optional losses |
| TraceabilityRecord | Belongs to Harvest, append-only batch event |
| LossRecord | Belongs to Farm and optionally a same-farm Harvest |
| FarmReport | Belongs to Farm, immutable generated JSON snapshot |

### Endpoints

| Resource | Operations |
|---|---|
| Accounts | Existing `/users`, `/users/signup`, `/users/me`, password and login routes remain available |
| Farmers | `POST /farmers/signup`, `PATCH /farmers/me` |
| Farms | `POST /farms/`, `GET /farms/`, `GET`, `PUT`, `PATCH`, `DELETE /farms/{id}` |
| Inventory | `POST /items/`, `GET /items/`, `GET`, `PUT`, `PATCH`, `DELETE /items/{id}` |
| Stock | `POST`, `GET /inventory-transactions`, `GET /inventory-transactions/{id}` |
| Expenses | `POST`, `GET /farm-expenses`, `GET`, `PATCH`, `DELETE /farm-expenses/{id}` |
| Harvests | `POST`, `GET /harvests`, `GET`, `PATCH`, `DELETE /harvests/{id}` |
| Traceability | `POST`, `GET /traceability`, `GET /traceability/{id}`, `GET /traceability/batches/{batch_code}` |
| Losses | `POST`, `GET /loss-records`, `GET`, `PATCH`, `DELETE /loss-records/{id}` |
| Reports | `POST /farm-reports/generate`, `GET /farm-reports`, `GET /farm-reports/{id}` |
| Overview | `GET /farms/{id}/overview` with `recent_limit` from 1 to 50 |

New record lists return `{ "data": [], "count": 0 }`, accept `skip >= 0` and `limit` from 1 to 100, and apply authorization before counting and pagination. Existing farm list responses remain arrays, with bounded pagination added.

Expense, harvest and loss lists accept `farm_id`, `start_date`, and `end_date`. Expenses also accept `category` and `currency`, harvests accept `crop_name`, and losses accept `harvest_id` and `loss_type`. Stock lists accept `item_id`, `transaction_type`, and date range. Traceability lists accept `farm_id`, `harvest_id`, `batch_code`, and date range. Report lists accept `farm_id`. Date ranges include both endpoint dates, with timestamps interpreted in UTC.

New resource creation returns 201. Validation failures return 422, missing authentication returns 401, inaccessible resources return 404, and conflicting stock, immutable associations or protected deletion return 409. Existing routes retain their success status codes.

### Request examples

Register a farmer using `POST /api/v1/farmers/signup`.

```json
{
  "full_name": "Example Farmer",
  "phone_number": "+231770000001",
  "password": "choose-your-own-password",
  "farm": {"name": "Example Farm", "county": "Bong", "farm_type": "Crops"}
}
```

The response contains `user` and `farm` objects with their server-generated IDs. Login returns `{ "access_token": "...", "token_type": "bearer" }`.

Create farm inventory using `POST /api/v1/items/`.

```json
{"title": "Rice seeds", "farm_id": "<farm UUID>", "category": "Seeds", "unit": "kg", "reorder_level": "5.0000"}
```

The item response includes its metadata, `owner_id`, `farm_id`, `quantity` initially `"0.0000"`, and timestamps. Quantity fields are excluded from metadata updates.

Post stock using `POST /api/v1/inventory-transactions`.

```json
{"item_id": "<item UUID>", "transaction_type": "IN", "quantity": "25.0000", "idempotency_key": "<new request UUID>"}
```

The response includes the movement `id`, `balance_after`, request fields, and `created_at`. Reusing a request key for the same item and movement returns the original movement. Conflicting payloads return 409. IN and OUT require positive quantities. ADJUSTMENT uses an explicit target balance and accepts zero. Corrections append compensating movements. Stock updates and their ledger entry commit together, using a conditional atomic SQL update to prevent overdrafts. SQLite arithmetic is rounded to the supported four decimal places.

Record an expense using `POST /api/v1/farm-expenses`.

```json
{"farm_id": "<farm UUID>", "category": "Seeds", "amount": "125.50", "currency": "LRD", "expense_date": "2026-11-21"}
```

Record a harvest using `POST /api/v1/harvests`.

```json
{"farm_id": "<farm UUID>", "crop_name": "Rice", "quantity": "100.0000", "unit": "kg", "harvest_date": "2026-11-21"}
```

Append a first batch event using `POST /api/v1/traceability`.

```json
{"harvest_id": "<harvest UUID>", "origin": "Bong", "status": "HARVESTED", "event_key": "<new event UUID>"}
```

The response adds `id`, `recorded_at`, and a generated `batch_code`. Later events must supply this returned batch code, the same harvest and origin, a new event key, and a timezone-aware timestamp on or after the origin event. Codes are namespaced with the harvest UUID and initial event UUID for collision protection. Arbitrary user-chosen first batch codes are rejected. Event keys deduplicate retries per harvest. A concurrent duplicate event can return 409 and may be retried. Batch history orders by recorded timestamp and ID, with pagination. Supported statuses are HARVESTED, STORED, IN_TRANSIT, and DELIVERED.

Record a loss using `POST /api/v1/loss-records`.

```json
{"farm_id": "<farm UUID>", "harvest_id": "<optional harvest UUID>", "loss_type": "Spoilage", "quantity": "2.0000", "unit": "kg", "reason": "Storage damage"}
```

Loss units must match a linked harvest. Losses do not change inventory. If stock was also affected, post its inventory movement explicitly. Reports count each loss record once.

Generate a report using `POST /api/v1/farm-reports/generate`.

```json
{"farm_id": "<farm UUID>", "report_type": "FARM_SUMMARY", "period_start": "2026-11-01", "period_end": "2026-11-30"}
```

The response contains `id`, `farm_id`, period, type, `generated_at`, and structured `report_data`. Report types are FARM_SUMMARY, INVENTORY, EXPENSE, HARVEST, LOSS, and TRACEABILITY. Every generation creates a new immutable snapshot from stored data. Monetary totals stay grouped by currency. Harvest totals stay grouped by crop and unit. Loss totals stay grouped by type, unit and linked crop. Inventory snapshots capture current balances when generated, with period movements grouped by item, unit and transaction type. Adjustment quantities represent target balances. Traceability summaries count events per status during the period. Overview provides lifetime totals plus bounded recent harvests and stock movements.

### Migration and historical data

Revision `ffd35e3b17e8` creates the six business tables and extends Item. Existing items retain `farm_id = NULL`, gain zero stock, and receive an update timestamp. The migration does not infer historical stock or choose a farm. Owners can explicitly associate a historical item with an owned farm through PATCH, then establish its verified opening balance using an inventory transaction. Existing farm inventory cannot be reassigned, and units cannot change after stock history exists.

The SQLite migration uses Alembic batch operations to add constraints, which recreates the item table while copying existing rows. A populated-database regression test verifies preservation. Business foreign keys restrict deletion. The API blocks deleting items with stock history, harvests with losses or traceability, farms with records, and accounts owning farms or stock history. Empty farms remain deletable. Database rollback drops the new business tables and should only be used after reviewing the loss of that new data.

SQLite is the verified development engine. PostgreSQL-compatible numeric, JSON and UUID types are used, but this implementation has not been exercised against a live PostgreSQL server. SQLite NUMERIC uses SQLite's native numeric representation, so very large values near precision limits require PostgreSQL validation before production use.

### Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ty check app
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format app --check
.\.venv\Scripts\python.exe -m alembic check
```

Tests configure a disposable SQLite database before importing the application. They migrate it, seed the admin account, and mock outbound email transport. They never use `agtrack.db`. Migration coverage includes fresh initialization and an upgrade containing legacy users, farms and items. Tests cover ownership, phone login, immutable history, currencies and units, reports, concurrent stock withdrawals and duplicate retries.

Weather, chatbot, credit scoring, SMS/USSD and PDF export remain outside this implementation scope.

## Postman testing walkthrough

Import `postman/AgTrack.postman_collection.json` into Postman. It contains 73 requests in execution order and automatically saves authentication tokens and resource IDs as collection variables. Select the collection and run one iteration with all requests selected. The first registration request generates fresh phone numbers and retry keys. Run the collection with collection variables taking precedence over any same-named environment variables.

Start the backend using `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`. The collection's `base_url` defaults to `http://127.0.0.1:8000/api/v1`. Its collection-level Bearer authorization uses `{{access_token}}`. Registration and login override this with No Auth. Login uses form URL encoding. Other write requests use raw JSON.

Execute the folders in this order.

1. Register and authenticate. Registration stores `user_id` and `farm_id`. Login stores `access_token`.
2. Farms. View farms and update the test farm community.
3. Inventory and stock logs. Create an item, add 25 kg, retry the same request, remove 5 kg, then adjust to 18.5 kg. The retry returns the original movement. There are three unique movements.
4. Farm expenses. Record LRD 1500 and USD 25 separately.
5. Harvests. Record cocoa as 250 kg and 2 bags. These remain separate totals.
6. Traceability event logs. Create a batch origin and append a storage event. Save `batch_code` and retrieve ordered history.
7. Loss records. Record 10 kg of spoilage against the kg harvest. This operation does not change inventory.
8. Reports and overview. Generate all six report types, retrieve the saved summary, and inspect farm totals.
9. Expected failure cases. The tests expect 401, 409, or 422, depending on the request. These requests pass when the API rejects the invalid operation.
10. Cross-user security tests. A second farmer cannot retrieve the first farmer's records. The collection retains the first farmer's token and uses the second token only on explicit security requests.
11. Delete disposable records. Create and delete a separate set of temporary records to test CRUD deletion. The primary sample data remains available for inspection.

Use the following URLs to inspect a specific JSON record after the collection has run.

| Record | GET URL |
|---|---|
| Stock movement log | `{{base_url}}/inventory-transactions/{{transaction_id}}` |
| All movements of the sample item | `{{base_url}}/inventory-transactions?item_id={{item_id}}&start_date=2026-11-21&end_date=2026-11-21` |
| Batch event | `{{base_url}}/traceability/{{traceability_id}}` |
| Full ordered batch history | `{{base_url}}/traceability/batches/{{batch_code}}` |
| Expense | `{{base_url}}/farm-expenses/{{expense_id}}` |
| Harvest | `{{base_url}}/harvests/{{harvest_id}}` |
| Loss | `{{base_url}}/loss-records/{{loss_id}}` |
| Saved summary | `{{base_url}}/farm-reports/{{report_id}}` |
| Farm overview | `{{base_url}}/farms/{{farm_id}}/overview?recent_limit=5` |

The example requests use November 21, 2026 so the fixed report date range includes all sample records. Sending an additional movement requires a fresh UUID retry key. Retrying the same movement requires its original key and payload. Rerunning an entire collection creates fresh accounts and records. It therefore adds test data to whichever backend `base_url` points at.

`postman/AgTrack.example-test-log.json` contains the actual request and response JSON from a successful isolated replay of all 73 collection calls. Passwords and tokens are redacted. Replay used FastAPI TestClient with equivalent substitutions and assertions, rather than the Postman JavaScript runtime. IDs inside this example log belonged to its disposable database. Use collection variables from your own run when querying your local API.
