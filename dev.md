# Development Plan: SQLite → MariaDB/MySQL Migration (feilong / zvmsdk)

Reference architecture: `proposed_architecture.md`

---

## Guiding Principles

- Every phase must leave the `backend = sqlite` default path **fully working** before merging.
- No phase breaks existing unit tests. New tests are added alongside code, not after.
- Each phase produces a standalone, reviewable PR. Phases may not be squashed together.
- All SQL in operator methods migrates to `text("... :param")` syntax — never bare strings.
- DDL migrations ship with a documented manual-rollback procedure in the migration file itself.

---

## Phase Overview

| Phase | Name                                        | Risk   | Blocking phases |
|-------|---------------------------------------------|--------|-----------------|
| 1     | SQLAlchemy engine factory (SQLite only)     | Low    | —               |
| 2     | Table definitions + Alembic bootstrap       | Low    | 1               |
| 3     | Refactor `database.py` connection managers  | Medium | 2               |
| 4     | MariaDB/MySQL backend support               | Medium | 3               |
| 5     | `compute_node_id` schema extension          | High   | 4               |
| 6     | Remote mode — node registration + scoped queries | High | 5          |
| 7     | Data migration tool                         | Low    | 4               |
| 8     | Integration testing (OpenStack + z/VM)      | Medium | 6, 7            |
| 9     | Hardening, monitoring, and documentation    | Low    | 8               |

---

## Phase 1 — SQLAlchemy Engine Factory (SQLite only, no behavioral change)

### Goal
Introduce `zvmsdk/db/api.py` with `get_engine()` and `get_connection()`. The SQLite
backend path must be identical in behavior to the current `sqlite3.connect()` approach.
No existing code in `database.py` is changed yet.

### Tasks

#### 1.1 Add new dependencies to `requirements.txt`

```
SQLAlchemy>=2.0.0        # Apache-2.0
alembic>=1.13.0          # MIT
PyMySQL>=1.1.0           # MIT
cryptography>=41.0.0     # Apache/BSD — needed by PyMySQL for SSL
```

Verify there are no version conflicts with existing dependencies (`six`, `Routes`,
`WebOb`, `PyJWT`, etc.) by running `pip install -r requirements.txt` in a clean venv.

#### 1.3 Create `zvmsdk/db/__init__.py`
Empty file to make `zvmsdk.db` a package.

#### 1.4 Create `zvmsdk/db/api.py`

Implement in full (all functions documented in §7.2 of the architecture):

- `_COMPUTE_NODE_ID: str = ''` — module-level global.
- `_ENGINE = None` — module-level global.
- `_ENGINE_LOCK = threading.Lock()` — double-checked locking guard.
- `get_compute_node_id() -> str` — returns the module global.
- `_resolve_compute_node_id() -> str` — priority 1/2/3 logic from §7.5.
  - Priority 1: `CONF.database.compute_node_id` (explicit config).
  - Priority 2: single `vmcp query userid` subprocess call; parse `tokens[0]@tokens[-1]`.
  - Priority 3: `CONF.network.my_ip` fallback.
- `get_engine()` — double-checked locked init; SQLite path only in this phase.
  - Validates `mode=remote` + `backend=sqlite` is illegal.
  - Stores `StaticPool` engine for SQLite.
- `_build_url()` — uses `sqlalchemy.engine.URL.create()` (not f-string).
- `_build_ssl_args()` — filters out `None` values; only populates `ssl` dict when `ssl_ca` is set.
- `get_connection()` — `contextmanager` wrapping `engine.begin()`.
- `verify_remote_connectivity()` — no-op when `mode=local`.

**Important**: In this phase, `get_engine()` only builds the SQLite engine. The MariaDB
branch raises `NotImplementedError` (to be filled in Phase 4).

#### 1.5 Add new config options to `zvmsdk/config.py`

Under the existing `[database]` section, register these new `Opt` entries:
- `backend` (str, default `'sqlite'`)
- `mode` (str, default `'local'`)
- `connection` (str, default `None`)
- `host` (str, default `'127.0.0.1'`)
- `port` (int, default `3306`)
- `name` (str, default `'zvmsdk'`)
- `user` (str, default `'zvmsdk'`)
- `password` (str, default `''`)
- `compute_node_id` (str, default `None`)
- `pool_size` (int, default `5`)
- `pool_max_overflow` (int, default `10`)
- `pool_timeout` (int, default `30`)
- `pool_recycle` (int, default `3600`)
- `alembic_config` (str, default `None`)
- `ssl_ca` (str, default `None`)
- `ssl_cert` (str, default `None`)
- `ssl_key` (str, default `None`)

#### 1.6 Update `zvmsdk.conf` sample / documentation
Add the `[database]` block from §6 of the architecture to any sample config files
under `sample/` or `doc/`.

### Tests

**Unit tests** (`tests/unit/test_db_api.py`):
- `test_get_engine_sqlite_returns_engine` — verify `get_engine()` returns a SQLAlchemy engine
  with SQLite dialect.
- `test_get_engine_is_singleton` — call `get_engine()` twice; assert same object returned.
- `test_get_engine_thread_safety` — spawn 20 threads all calling `get_engine()` simultaneously;
  assert all receive the same engine object and `_resolve_compute_node_id()` ran exactly once.
- `test_resolve_node_id_from_config` — mock `CONF.database.compute_node_id = 'my-node'`;
  assert returned value is `'my-node'`.
- `test_resolve_node_id_from_vmcp` — mock `subprocess.check_output` to return
  `b'IAAS01EF AT BOEM5401\n'`; assert returned value is `'IAAS01EF@BOEM5401'`.
- `test_resolve_node_id_fallback_to_my_ip` — mock vmcp to raise; assert fallback is
  `CONF.network.my_ip`.
- `test_build_ssl_args_empty_when_no_ssl_ca` — assert returns `{}`.
- `test_build_ssl_args_only_ca` — assert `ssl` dict has only `'ca'` key.
- `test_build_ssl_args_full` — assert `ssl` dict has all three keys.
- `test_mode_remote_backend_sqlite_raises` — mock config; assert `SDKInternalError` raised.
- `test_get_connection_commits_on_success` — use in-memory SQLite; verify a write is
  committed after the `get_connection()` block exits normally.
- `test_get_connection_rolls_back_on_exception` — verify write is absent after exception
  inside the block.

### Files changed
| File | Change |
|------|--------|
| `requirements.txt` | Add `SQLAlchemy`, `alembic`, `PyMySQL`, `cryptography` |
| `zvmsdk/db/__init__.py` | New (empty) |
| `zvmsdk/db/api.py` | New |
| `zvmsdk/config.py` | Add 17 new `Opt` entries under `[database]` |
| `sample/zvmsdk.conf` (if exists) | Add new `[database]` options |
| `tests/unit/test_db_api.py` | New |

### Exit criteria
- All new unit tests pass.
- All existing unit tests pass.
- `pip install -r requirements.txt` succeeds in a clean venv with no conflicts.
- No import of `zvmsdk.db.api` in `database.py` yet — this phase is purely additive.

---

## Phase 2 — Table Definitions and Alembic Bootstrap

### Goal
Create `zvmsdk/db/models.py` with all SQLAlchemy Core table definitions.
Set up the Alembic directory and write the first migration (SQLite baseline).
Nothing in the runtime path changes.

### Tasks

#### 2.1 Create `zvmsdk/db/models.py`

Implement all 8 tables exactly as specified in §7.3 of the architecture:
`compute_nodes`, `guests`, `switch`, `image`, `fcp`, `template`,
`template_sp_mapping`, `template_fcp_mapping`.

Key correctness points:
- `image` PK is `(imagename, compute_node_id)` with `server_default='GLOBAL'`.
- `fcp` and all data tables: **no FK to `compute_nodes`** in the base definition.
- `template_sp_mapping` has `ForeignKeyConstraint` to `template(id, compute_node_id)`
  with `ON DELETE CASCADE`.
- `template_fcp_mapping` has two `ForeignKeyConstraint`s: to `template` and to `fcp`.
- All tables use `mysql_engine='InnoDB'`, `mysql_charset='utf8mb4'`,
  `mysql_collate='utf8mb4_general_ci'`.

#### 2.2 Set up Alembic directory structure

```
alembic/
├── alembic.ini
├── env.py
├── script.py.mako
└── versions/
    └── 0001_initial_sqlite_baseline.py
```

**`alembic/env.py`** — implement `get_url()` and `run_migrations_online()` per §8.2.
Use `URL.create()` (not f-string) for the MariaDB URL path.

**`alembic/alembic.ini`** — minimal config pointing `script_location` to the
`alembic/` directory. `sqlalchemy.url` is left blank and overridden by `env.py`.

#### 2.3 Write migration `0001_initial_sqlite_baseline.py`

Creates all current tables **without** `compute_node_id` — this is the baseline for
existing installations already running SQLite. The `upgrade()` function should use
`op.execute()` with the raw DDL for each table. The `downgrade()` function drops all
tables in reverse dependency order.

Document the manual rollback in the module docstring:
```
Rollback: run downgrade() — drops all tables. Existing data is lost.
          Back up before applying this migration in production.
```

#### 2.4 Create `zvmsdk/db/migration.py`

Implement `_get_alembic_ini_path()` and `ensure_schema_current()` per §8.3:
- `_get_alembic_ini_path()` checks `CONF.database.alembic_config` first, then
  falls back to the package-bundled `alembic/alembic.ini`.
- `ensure_schema_current()` calls `alembic.command.upgrade(cfg, 'head')`.

### Tests

**Unit tests** (`tests/unit/test_db_models.py`):
- `test_metadata_contains_all_tables` — assert `models.metadata.tables.keys()` contains
  all 8 expected table names.
- `test_image_pk_is_composite` — assert `image.primary_key.columns.keys()` ==
  `['imagename', 'compute_node_id']`.
- `test_fcp_has_no_fk_to_compute_nodes` — assert no FK from `fcp.compute_node_id` to
  `compute_nodes` in the base model.
- `test_template_sp_mapping_fk_cascade` — assert `ForeignKeyConstraint` exists with
  `ondelete='CASCADE'`.
- `test_template_fcp_mapping_has_two_fks` — assert two `ForeignKeyConstraint`s.

**Integration tests** (`tests/integration/test_alembic_sqlite.py`):
- `test_alembic_upgrade_head_sqlite` — run `ensure_schema_current()` against a temp
  SQLite file; assert all 8 tables exist afterwards.
- `test_alembic_downgrade_to_base_sqlite` — upgrade then downgrade; assert tables are gone.

### Files changed
| File | Change |
|------|--------|
| `zvmsdk/db/models.py` | New |
| `zvmsdk/db/migration.py` | New |
| `alembic/alembic.ini` | New |
| `alembic/env.py` | New |
| `alembic/script.py.mako` | New (copy from alembic default) |
| `alembic/versions/0001_initial_sqlite_baseline.py` | New |
| `tests/unit/test_db_models.py` | New |
| `tests/integration/test_alembic_sqlite.py` | New |
| `MANIFEST.in` | Add `alembic/` directory to package data |
| `setup.py` | Add `package_data` for `alembic/` |

### Exit criteria
- `alembic upgrade head` runs against a fresh SQLite file and creates all 8 tables.
- `alembic downgrade base` removes all tables.
- All unit and integration tests pass.

---

## Phase 3 — Refactor `database.py` Connection Managers

### Goal
Replace the 5 SQLite connection globals (`_NETWORK_CONN`, `_IMAGE_CONN`, `_GUEST_CONN`,
`_FCP_CONN`) and all 5 `threading.RLock()` instances with calls to
`zvmsdk.db.api.get_connection()`. The SQLite backend must continue to work identically.
All SQL statements are migrated from bare strings to `text("... :param")`.

This is the largest single phase by lines-of-code changed.

### Tasks

#### 3.1 Replace connection managers

For each of `get_network_conn()`, `get_image_conn()`, `get_guest_conn()`, `get_fcp_conn()`:

**Before (sqlite3)**:
```python
global _FCP_CONN
if not _FCP_CONN:
    _FCP_CONN = _init_db_conn(const.DATABASE_FCP)
_DBLOCK_FCP.acquire()
try:
    if not _FCP_CONN.in_transaction:
        _FCP_CONN.execute("BEGIN")
        skip_commit = False
    else:
        skip_commit = True
    yield _FCP_CONN
    if not skip_commit:
        _FCP_CONN.execute("COMMIT")
except exception.SDKBaseException as err:
    if not skip_commit:
        _FCP_CONN.execute("ROLLBACK")
    raise
except Exception as err:
    if not skip_commit:
        _FCP_CONN.execute("ROLLBACK")
    raise exception.SDKGuestOperationError(rs=1, msg=str(err))
finally:
    _DBLOCK_FCP.release()
```

**After (SQLAlchemy)**:
```python
from zvmsdk.db.api import get_connection

@contextlib.contextmanager
def get_fcp_conn():
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        raise exception.SDKDatabaseException(msg=msg)
```

Apply the same pattern to `get_network_conn()`, `get_image_conn()`, `get_guest_conn()`.

#### 3.2 Remove now-unused globals and locks

Delete from `database.py`:
- `_NETWORK_CONN`, `_IMAGE_CONN`, `_GUEST_CONN`, `_FCP_CONN`
- `_DBLOCK_VOLUME`, `_DBLOCK_NETWORK`, `_DBLOCK_IMAGE`, `_DBLOCK_GUEST`, `_DBLOCK_FCP`
- `_init_db_conn()` function
- `import sqlite3`
- `import six` (if only used for `six.text_type` in connection managers)

#### 3.3 Migrate all raw SQL to `text()` with named parameters

Every `conn.execute(...)` call in `database.py` must be converted.

**Conversion rules**:
| Old pattern | New pattern |
|-------------|-------------|
| `conn.execute("SELECT ... WHERE x=?", (val,))` | `conn.execute(text("SELECT ... WHERE x=:x"), {'x': val})` |
| `conn.executemany("UPDATE fcp SET ...", list_of_tuples)` | `conn.execute(text("UPDATE fcp SET ..."), list_of_dicts)` |
| `IS NOT ''` | `<> ''` |
| `COLLATE NOCASE` in DDL strings | Remove — collation is handled at table-definition level |
| `sqlite3.Row` subscript access `row['col']` | `row._mapping['col']` or `dict(row._mapping)` |
| `conn.in_transaction` | Removed — `engine.begin()` manages this |

**Hotspots to address** (from current `database.py` analysis):
- Lines ~411–490: `FCPDbOperator` `executemany` calls (`UPDATE fcp SET reserved`, `UPDATE fcp`,
  `INSERT INTO fcp`, `DELETE FROM fcp`, `UPDATE fcp SET wwpn_npiv`, `UPDATE fcp set state`)
- Lines ~727, 747: `template_fcp_mapping` `executemany` inserts
- Lines ~842, 847: `template_sp_mapping` `executemany` deletes/inserts
- Lines ~920–993: `IS NOT ''` comparisons in FCP queries (at least 4 occurrences)
- Lines ~1331–1332: Additional `IS NOT ''` in FCP multipath queries
- Line ~1634: `template_fcp_mapping` INSERT

#### 3.4 Remove `_initialize_table` DDL from operators

Currently each operator calls `CREATE TABLE IF NOT EXISTS` on init. With Alembic managing
schema, these DDL calls are removed. The operators assume the schema already exists
(guaranteed by `ensure_schema_current()` at startup).

Remove `_create_switch_table()`, `_initialize_table()`, and similar methods from
`NetworkDbOperator`, `GuestDbOperator`, `ImageDbOperator`, `FCPDbOperator`.

#### 3.5 Add `ensure_schema_current()` call to SDK startup

In the main SDK entry point (wherever `CONF` is loaded and operators are first instantiated),
add:
```python
from zvmsdk.db import migration
migration.ensure_schema_current()
```
This must run before any `*DbOperator()` is constructed.

### Tests

**Unit tests** — update all existing `database.py` unit tests:
- Replace any `sqlite3` mock with `unittest.mock.MagicMock` that mimics the
  SQLAlchemy connection interface (`execute`, `fetchone`, `fetchall`).
- Assert that `conn.execute()` receives a `text()` object, not a plain string.

**Regression tests** (`tests/unit/test_database_connection_managers.py`):
- `test_get_fcp_conn_raises_sdk_database_exception_on_generic_error`
- `test_get_fcp_conn_reraises_sdk_base_exception`
- `test_get_network_conn_raises_sdk_database_exception`
- `test_get_guest_conn_raises_sdk_database_exception`

**Integration tests** (`tests/integration/test_database_sqlite.py`):
- Run the full `GuestDbOperator`, `NetworkDbOperator`, `ImageDbOperator`, `FCPDbOperator`
  test suites against an in-memory SQLite engine (schema created by Alembic).
- Compare output of each operator method against expected values — no mocking of the DB layer.

### Files changed
| File | Change |
|------|--------|
| `zvmsdk/database.py` | Major refactor — remove 5 conn globals, 5 locks, `_init_db_conn`, `_initialize_table` methods; migrate all SQL to `text()`; update connection managers |
| `tests/unit/test_database.py` | Update all mocks to SQLAlchemy interface |
| `tests/integration/test_database_sqlite.py` | New |
| `tests/unit/test_database_connection_managers.py` | New |

### Exit criteria
- All unit tests (SQLite path) pass with zero regressions.
- All 95 methods in `database.py` execute successfully against an in-memory SQLite in CI.
- No bare string is passed to any `conn.execute()` call — enforced by a `grep` in CI:
  ```
  grep -rn 'conn\.execute("[^t]' zvmsdk/database.py && exit 1 || true
  ```
- No `sqlite3`, `six`, `threading.RLock`, `executemany` remain in `database.py`.

---

## Phase 4 — MariaDB/MySQL Backend Support

### Goal
Complete the MariaDB branch of `get_engine()` and run all operator tests against a live
MariaDB. This phase proves every SQL query works in both dialects before schema changes.

### Tasks

#### 4.1 Complete `get_engine()` MariaDB path in `zvmsdk/db/api.py`

Remove the `NotImplementedError` placeholder from Phase 1. The full MariaDB engine
creation (per §7.2) is now active:
- `URL.create()` for the connection URL.
- `QueuePool` with `pool_pre_ping=True`.
- `_build_ssl_args()` for optional TLS.

#### 4.2 Write Alembic migration `0002_initial_mariadb.py`

Creates all 8 tables in MariaDB-compatible DDL (InnoDB, utf8mb4, utf8mb4_general_ci).
No `compute_node_id` yet — that comes in Phase 5.

Include manual rollback procedure in docstring:
```
Rollback: run downgrade() — drops all 8 tables.
          Back up before running in production.
```

#### 4.3 Audit and fix all SQLite-specific SQL constructs

Cross-reference the compatibility map from §5.3 and scan `database.py` for any
remaining constructs that need changing for MariaDB compatibility:

| Check | Tool |
|-------|------|
| `COLLATE NOCASE` in any string | `grep -n 'COLLATE NOCASE' zvmsdk/database.py` |
| `IS NOT ''` | `grep -n "IS NOT ''" zvmsdk/database.py` |
| `?` placeholders | `grep -n '".*?"' zvmsdk/database.py` |
| `isolation_level=None` | `grep -n 'isolation_level' zvmsdk/database.py` |
| `conn.in_transaction` | `grep -n 'in_transaction' zvmsdk/database.py` |

All occurrences should be zero by end of Phase 3. This task is a final audit.

#### 4.4 Fix `get_volume_conn()` if it exists

`DATABASE_VOLUME = 'sdk_volume.sqlite'` is declared in `constants.py` but no
operator or connection uses it. Confirm with `grep` and leave a code comment
explaining the unused constant. Do not create a volume table.

#### 4.5 Test all operators against MariaDB

Run the full `GuestDbOperator`, `NetworkDbOperator`, `ImageDbOperator`, `FCPDbOperator`
integration test suite (from Phase 3) against the CI MariaDB service.

Every test that passed against SQLite must also pass against MariaDB.

### Tests

**Integration tests** (`tests/integration/test_database_mariadb.py`):
- Parameterized re-run of all `test_database_sqlite.py` tests using the
  MariaDB URL from `ZVMSDK_TEST_DB_URL` environment variable.
- Skipped automatically if `ZVMSDK_TEST_DB_URL` is not set (local dev without MariaDB).

**Smoke test** (`tests/integration/test_mariadb_connectivity.py`):
- `test_mariadb_connect` — verify `get_engine().connect()` succeeds.
- `test_mariadb_charset` — verify `SHOW VARIABLES LIKE 'character_set_database'`
  returns `utf8mb4`.
- `test_mariadb_collation` — verify collation is `utf8mb4_general_ci`.
- `test_pool_pre_ping` — simulate a stale connection (close server side), verify
  `pool_pre_ping` recovers silently.

### Files changed
| File | Change |
|------|--------|
| `zvmsdk/db/api.py` | Complete MariaDB engine path |
| `alembic/versions/0002_initial_mariadb.py` | New |
| `tests/integration/test_database_mariadb.py` | New |
| `tests/integration/test_mariadb_connectivity.py` | New |
| `zvmsdk/constants.py` | Add comment on unused `DATABASE_VOLUME` |

### Exit criteria
- All operator integration tests pass against a local MariaDB instance.
- No `COLLATE NOCASE`, no `IS NOT ''`, no bare `?` placeholder, no `sqlite3` import
  remains in `database.py`.
- `alembic upgrade head` on a fresh MariaDB creates all 8 tables with correct charset
  and collation.

---

## Phase 5 — `compute_node_id` Schema Extension

### Goal
Add `compute_node_id` to all node-scoped tables and create the `compute_nodes` registry
table. Schema is extended in both SQLite and MariaDB. FK constraints are only added when
`mode = remote` (handled in Phase 6). Existing data is backfilled.

### Tasks

#### 5.1 Write Alembic migration `0003_add_compute_node_support.py`

**`upgrade()` steps** (in order):
1. Create `compute_nodes` table.
2. For each data table (`switch`, `guests`, `fcp`, `template`, `template_sp_mapping`,
   `template_fcp_mapping`):
   a. `ALTER TABLE ... ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT ''`
   b. `UPDATE <table> SET compute_node_id = :node_id` — backfill with the current node's
      ID (read from `CONF.database.compute_node_id` or resolved via priority logic).
   c. `ALTER TABLE ... DROP PRIMARY KEY`
   d. `ALTER TABLE ... ADD PRIMARY KEY (old_pk_cols..., compute_node_id)`
3. For `image`:
   a. `ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'GLOBAL'`
   b. `ALTER TABLE ... DROP PRIMARY KEY`
   c. `ALTER TABLE ... ADD PRIMARY KEY (imagename, compute_node_id)`

**`downgrade()` steps** (reverse order):
1. For each table: `DROP PRIMARY KEY`, `ADD PRIMARY KEY (original_cols)`, `DROP COLUMN compute_node_id`.
2. `DROP TABLE compute_nodes`.

**Manual rollback note in docstring** (required because DDL is not transactional in MySQL):
```
Manual rollback if upgrade() fails mid-way:
  -- If compute_node_id was added but PK not yet expanded:
  ALTER TABLE <table> DROP COLUMN compute_node_id;
  -- If compute_nodes was created but data tables not yet altered:
  DROP TABLE compute_nodes;
  -- Run: alembic stamp <previous_revision_id>
```

#### 5.2 Update `zvmsdk/db/models.py`

Add `compute_node_id` to all table definitions (already done in Phase 2 for
`image` — verify consistency). Update PKs to match the expanded composite keys.
No FK to `compute_nodes` in model definitions (FK added by Phase 6 migration only).

#### 5.3 Update operator `__init__` methods

Remove any remaining `CREATE TABLE IF NOT EXISTS` DDL from `FCPDbOperator._initialize_table()`
and related methods. All schema is now owned by Alembic.

#### 5.4 Inject `compute_node_id` into all write-path operator methods

Every `INSERT` in `database.py` that targets a node-scoped table must inject
`db_api.get_compute_node_id()`. Methods affected:

| Operator | Method |
|----------|--------|
| `GuestDbOperator` | `add_guest()` |
| `NetworkDbOperator` | `switch_add_record()` |
| `ImageDbOperator` | `image_add_record()` |
| `FCPDbOperator` | `new_fcp()`, `assign_fcp()`, `add_fcp_template()`, `add_fcp_template_sp_mapping()`, `add_fcp_template_fcp_mapping()` |

No caller outside `database.py` passes or knows the `compute_node_id`.

#### 5.5 Do NOT add node filtering to read-path queries (local mode)

In **local mode**, queries must not filter by `compute_node_id`. The column is stored
and indexed but ignored in WHERE clauses. This preserves exact backward-compatible
behavior for local deployments. The read-path filtering is added in Phase 6 (remote mode
only), controlled by `CONF.database.mode`.

### Tests

**Unit tests** (`tests/unit/test_compute_node_id_injection.py`):
- For each write-path method, assert the `text()` SQL includes `:node_id` and
  that the bound dict contains the value from `get_compute_node_id()`.

**Integration tests** (`tests/integration/test_schema_migration_0003.py`):
- `test_upgrade_0003_sqlite` — run migration on fresh SQLite; verify columns exist.
- `test_upgrade_0003_mariadb` — run on MariaDB; verify columns, PK expansion.
- `test_backfill_writes_node_id` — after migration, insert a guest; read back and
  assert `compute_node_id` equals the resolved node ID.
- `test_downgrade_0003` — verify clean rollback removes columns and restores original PKs.

### Files changed
| File | Change |
|------|--------|
| `alembic/versions/0003_add_compute_node_support.py` | New |
| `zvmsdk/db/models.py` | Update PKs to composite keys (verify against Phase 2) |
| `zvmsdk/database.py` | Inject `compute_node_id` in all write paths; remove DDL init methods |
| `tests/unit/test_compute_node_id_injection.py` | New |
| `tests/integration/test_schema_migration_0003.py` | New |

### Exit criteria
- `alembic upgrade head` on a fresh DB creates all tables with `compute_node_id`.
- `alembic downgrade base` cleanly removes all columns.
- All operator write methods inject `compute_node_id`.
- All existing operator read methods return correct data without filtering by node.
- All unit tests and MariaDB integration tests pass.

---

## Phase 6 — Remote Mode: Node Registration and Scoped Queries

### Goal
Implement everything needed for `mode = remote`: node registration in `compute_nodes`,
FK enforcement, and read-path query filtering by `compute_node_id`.

### Tasks

#### 6.1 Implement `register_compute_node()` in `zvmsdk/db/api.py`

```python
def register_compute_node():
    """UPSERT this node into compute_nodes on startup."""
    node_id  = get_compute_node_id()
    hostname = socket.gethostname()
    ip       = CONF.network.my_ip
    with get_connection() as conn:
        conn.execute(text("""
            INSERT INTO compute_nodes (id, hostname, ip_address, status, last_seen)
            VALUES (:id, :hostname, :ip, 'active', NOW())
            ON DUPLICATE KEY UPDATE
                last_seen = NOW(),
                status = 'active',
                hostname = VALUES(hostname),
                ip_address = VALUES(ip_address)
        """), {'id': node_id, 'hostname': hostname, 'ip': ip})
```

For SQLite, use `INSERT OR REPLACE` syntax (SQLAlchemy abstracts this via `dialect`
detection or use `on_conflict_do_update` from SQLAlchemy Core).

#### 6.2 Implement `deregister_compute_node()` in `zvmsdk/db/api.py`

Sets `status = 'inactive'` on clean shutdown.
Hooked into the SDK shutdown path.

#### 6.3 Write Alembic migration `0004_add_remote_mode_fks.py`

Conditionally adds FK constraints to `compute_nodes`. This migration only runs when
`mode = remote`:

```python
def upgrade():
    mode = getattr(CONF.database, 'mode', 'local')
    if mode != 'remote':
        return   # no-op in local mode
    op.create_foreign_key('fk_fcp_node', 'fcp', 'compute_nodes',
                          ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_switch_node', 'switch', 'compute_nodes', ...)
    op.create_foreign_key('fk_guests_node', 'guests', 'compute_nodes', ...)
    op.create_foreign_key('fk_template_node', 'template', 'compute_nodes', ...)
    op.create_foreign_key('fk_tmpl_sp_node', 'template_sp_mapping', 'compute_nodes', ...)
    op.create_foreign_key('fk_tmpl_fcp_node', 'template_fcp_mapping', 'compute_nodes', ...)
```

Manual rollback note: list each `ALTER TABLE ... DROP FOREIGN KEY` statement.

#### 6.4 Add mode-aware filtering to read-path operator methods

Add a helper in `database.py`:

```python
def _node_filter():
    """Returns SQL fragment and bind dict for node scoping in remote mode."""
    if getattr(CONF.database, 'mode', 'local') == 'remote':
        return "AND compute_node_id = :node_id", {'node_id': db_api.get_compute_node_id()}
    return "", {}
```

Apply `_node_filter()` to all SELECT queries that should be scoped to the local node
in remote mode. Methods affected:

| Operator | Methods |
|----------|---------|
| `GuestDbOperator` | `get_guest_list()`, `get_guest_by_userid()`, `get_guest_metadata()` |
| `NetworkDbOperator` | `switch_select()`, `switch_select_record()` |
| `ImageDbOperator` | `image_query_record()`, `image_get_all()` |
| `FCPDbOperator` | All `get_fcp_*` methods, `get_template_*` methods |

In **local mode**, `_node_filter()` returns empty strings and the queries run exactly
as before.

#### 6.5 Integrate startup sequence into SDK entry point

Update the SDK startup (wherever operators are initialized) to call in order:
1. `migration.ensure_schema_current()`
2. `api.verify_remote_connectivity()` (no-op in local mode)
3. `api.register_compute_node()`

On clean shutdown, call `api.deregister_compute_node()`.

#### 6.6 Add `verify_remote_connectivity()` implementation

Already stubbed in Phase 1; complete implementation per §9.2. Uses `text("SELECT 1")`
against the engine. Raises `SDKInternalError` if unreachable in remote mode.

### Tests

**Unit tests** (`tests/unit/test_remote_mode.py`):
- `test_node_filter_returns_empty_in_local_mode`
- `test_node_filter_returns_clause_in_remote_mode`
- `test_verify_connectivity_noop_in_local_mode`
- `test_verify_connectivity_raises_on_failure` — mock engine to raise; assert `SDKInternalError`.

**Integration tests** (`tests/integration/test_remote_mode_mariadb.py`):
- Spin up two "virtual nodes" sharing the same MariaDB (differentiated by `compute_node_id`).
- `test_guest_isolation` — node A inserts a guest; node B cannot see it via `get_guest_by_userid()`.
- `test_fcp_isolation` — same pattern for FCP devices.
- `test_image_global_shared` — image with `compute_node_id='GLOBAL'` is visible from both nodes.
- `test_fk_cascade_on_node_removal` — delete a `compute_nodes` row; assert its fcp/switch/guest
  rows are cascade-deleted.
- `test_compute_node_upsert_updates_last_seen` — call `register_compute_node()` twice;
  assert `last_seen` timestamp increases.
- `test_deregister_sets_inactive` — call `deregister_compute_node()`; assert `status='inactive'`.

### Files changed
| File | Change |
|------|--------|
| `zvmsdk/db/api.py` | Add `register_compute_node()`, `deregister_compute_node()` |
| `zvmsdk/database.py` | Add `_node_filter()` helper; apply to all read-path queries in remote mode |
| `alembic/versions/0004_add_remote_mode_fks.py` | New |
| SDK entry point (TBD) | Add startup sequence |
| `tests/unit/test_remote_mode.py` | New |
| `tests/integration/test_remote_mode_mariadb.py` | New |

### Exit criteria
- Two nodes sharing a MariaDB cannot see each other's guests/FCPs/switch records.
- FK cascade deletes work correctly in remote mode.
- In local mode, all existing behavior is unchanged (zero regressions).
- All remote mode integration tests pass against a local MariaDB instance.

---

## Phase 7 — Data Migration Tool

### Goal
Provide `tools/migrate_sqlite_to_mariadb.py` so operators can migrate their existing
5-file SQLite data to MariaDB (or to the new consolidated `zvmsdk.db`) without data loss.

### Tasks

#### 7.1 Create `tools/migrate_sqlite_to_mariadb.py`

**CLI interface**:
```
migrate_sqlite_to_mariadb.py
  --sqlite-dir PATH        Source directory containing *.sqlite files
  --config PATH            Path to zvmsdk.conf (for target DB config)
  --compute-node-id ID     Node ID to inject into migrated rows
  --target-backend sqlite|mariadb   Default: mariadb
  --dry-run                Print row counts without writing
  --batch-size N           Rows per INSERT batch (default: 500)
```

**Source files to read** (in `--sqlite-dir`):
- `sdk_network.sqlite` → tables: `switch`
- `sdk_guest.sqlite` → tables: `guests`
- `sdk_image.sqlite` → tables: `image`
- `sdk_fcp.sqlite` → tables: `fcp`, `template`, `template_sp_mapping`, `template_fcp_mapping`
- `sdk_volume.sqlite` — skip (no table body exists)

**Steps**:
1. Parse arguments.
2. Verify each source SQLite file exists; warn and skip missing files.
3. Connect to target (MariaDB or new consolidated SQLite `zvmsdk.db`).
4. Run `ensure_schema_current()` on the target.
5. Call `register_compute_node()` to ensure the node exists in `compute_nodes`.
6. For each source file and each table:
   a. `SELECT COUNT(*) FROM <table>` on source — record expected count.
   b. Read in batches of `--batch-size`.
   c. Inject `compute_node_id` into each row dict.
   d. INSERT batch into target using `conn.execute(text(...), list_of_dicts)`.
7. Verify counts: `SELECT COUNT(*) FROM <table> WHERE compute_node_id = :node_id`.
8. Print summary report per table: source count, target count, status (OK / MISMATCH).
9. Exit with code 1 if any table has a count mismatch.

**Idempotency**: The script must be safely re-runnable. Use `INSERT OR IGNORE` for SQLite
target and `INSERT IGNORE` for MariaDB target so re-runs don't duplicate data.

#### 7.2 Add `--dry-run` mode

In dry-run mode, read source rows, count them, print the report, but write nothing to
the target. Useful for pre-flight validation.

#### 7.3 Write a rollback note

At the top of the script, document:
```
Rollback: this script does not delete source SQLite files. To revert, drop the
target database and restore from backup. The source SQLite files are never modified.
```

### Tests

**Unit tests** (`tests/unit/test_migrate_tool.py`):
- `test_dry_run_writes_nothing` — mock the target connection; assert no INSERT executed.
- `test_batch_insert_correct_size` — 1001 rows with batch-size 500 → 3 INSERT calls.
- `test_compute_node_id_injected` — assert every row dict has `compute_node_id`.
- `test_skips_missing_sqlite_file` — assert warning logged, no exception raised.
- `test_count_mismatch_exits_1` — mock count discrepancy; assert `SystemExit(1)`.

**Integration tests** (`tests/integration/test_migrate_sqlite_to_mariadb.py`):
- `test_full_migration_sqlite_to_mariadb` — populate source SQLite files with known data;
  run migration; assert exact rows in MariaDB with correct `compute_node_id`.
- `test_full_migration_sqlite_to_sqlite` — same but with `--target-backend sqlite`.
- `test_idempotent_rerun` — run migration twice; assert no duplicate rows.

### Files changed
| File | Change |
|------|--------|
| `tools/migrate_sqlite_to_mariadb.py` | New |
| `tests/unit/test_migrate_tool.py` | New |
| `tests/integration/test_migrate_sqlite_to_mariadb.py` | New |

### Exit criteria
- Script migrates all known test fixtures from 5 SQLite files to MariaDB with zero data loss.
- `--dry-run` writes nothing.
- Re-running the script is idempotent.
- Exit code 1 on any count mismatch.

---

## Phase 8 — Integration Testing (OpenStack + z/VM)

### Goal
Validate end-to-end that the nova-compute z/VM driver continues to work correctly
against feilong in both local-MariaDB and remote-MariaDB modes. No OpenStack-side
changes should be needed.

### Tasks

#### 8.1 Local-mode regression test against MariaDB

Deploy feilong with `backend=mariadb`, `mode=local`, pointing to a local MariaDB.
Run the full functional validation test (FVT) suite in `fvt-requirements.txt`.
All FVT tests must pass with zero changes.

#### 8.2 Remote-mode smoke test

Deploy two feilong instances pointing to the same MariaDB (`mode=remote`).
- Create a guest from node A; verify it is not visible from node B.
- Delete node A's `compute_nodes` entry; verify FK cascade removes its guests/FCPs.
- Restart node A; verify `register_compute_node()` recreates the entry.

#### 8.3 Migration tool FVT

Start with a live feilong deployment running SQLite (pre-migration state).
Run `migrate_sqlite_to_mariadb.py`.
Switch `zvmsdk.conf` to `backend=mariadb`.
Restart feilong.
Run FVT suite — all tests must pass against the migrated data.

#### 8.4 Validate SSL/TLS in remote mode

Configure the MariaDB server with `require_secure_transport = ON`.
Configure feilong with `ssl_ca`, `ssl_cert`, `ssl_key`.
Verify `verify_remote_connectivity()` succeeds and connections are encrypted
(confirm via `SHOW STATUS LIKE 'Ssl_cipher'`).

#### 8.5 Concurrent node startup test

Simulate 3 feilong nodes starting simultaneously against a fresh MariaDB.
Verify exactly one set of tables is created (no duplicate DDL errors).
Verify all 3 nodes register successfully in `compute_nodes`.

### Files changed
| File | Change |
|------|--------|
| `fvt-requirements.txt` | No change expected |

### Exit criteria
- All FVT tests pass in local-MariaDB mode.
- Remote-mode isolation verified manually.
- Migration tool FVT succeeds without data loss.
- Concurrent startup test shows no errors.

---

## Phase 9 — Hardening, Monitoring, and Documentation

### Goal
Production-readiness: connection health monitoring, credential management hardening,
operator documentation, and cleanup.

### Tasks

#### 9.1 Prometheus/Grafana metrics (optional but recommended)

Expose SQLAlchemy pool stats via the existing feilong metrics path (if any):
- Pool size (`pool_size`)
- Checked-out connections (`pool_checkedout`)
- Overflow connections (`pool_overflow`)
- Invalid (pre-ping reset) connections

Use SQLAlchemy's `event.listen(engine, 'checkout', ...)` hooks.

#### 9.2 Credential management hardening

- Read `ZVMSDK_DB_PASSWORD` environment variable as fallback if `password` is unset
  in config. Add to `config.py` with `os.environ.get('ZVMSDK_DB_PASSWORD', '')`.
- Document Barbican integration path in operator guide.
- Ensure `password` config key is masked in log output
  (`LOG.debug` must not print `CONF.database.password`).

#### 9.3 Stale node health-check

Implement a background thread or periodic check:
```python
def _mark_stale_nodes_inactive(threshold_seconds=300):
    with get_connection() as conn:
        conn.execute(text("""
            UPDATE compute_nodes SET status='inactive'
            WHERE last_seen < NOW() - INTERVAL :s SECOND AND status='active'
        """), {'s': threshold_seconds})
```

Expose this as a CLI command and as an optional startup check.

#### 9.4 Operator documentation

Write/update:
- `doc/source/admin/database_migration.rst` — step-by-step upgrade guide:
  1. Install new package (includes dependencies).
  2. Run `migrate_sqlite_to_mariadb.py`.
  3. Update `zvmsdk.conf`.
  4. Restart feilong.
- `doc/source/admin/database_ha.rst` — Galera Cluster and ProxySQL setup.
- `doc/source/admin/database_ssl.rst` — TLS configuration.
- `sample/zvmsdk.conf` — update with all new `[database]` options and comments.

#### 9.5 Remove deprecated constants and dead code

- Add deprecation warning (not removal yet) for `DATABASE_NETWORK`, `DATABASE_IMAGE`,
  `DATABASE_GUEST`, `DATABASE_FCP` constants in `constants.py` — they are superseded
  by the unified engine.
- Remove `DATABASE_VOLUME` comment stub once confirmed unused across all branches.

#### 9.6 Final code review and security audit

Run `bandit -r zvmsdk/` and resolve any new findings introduced by this work.
Key areas to audit:
- Password not logged anywhere.
- `subprocess` calls in `_resolve_compute_node_id()` use fixed argument lists (no shell=True).
- All `text()` SQL uses named parameters (no string interpolation into SQL).

### Files changed
| File | Change |
|------|--------|
| `zvmsdk/db/api.py` | Pool metrics hooks; credential env-var fallback; stale node check |
| `zvmsdk/config.py` | Deprecation warnings on old constants |
| `zvmsdk/constants.py` | Deprecation warning on `DATABASE_*` constants |
| `doc/source/admin/` | New RST files |
| `sample/zvmsdk.conf` | Updated |

### Exit criteria
- `bandit` reports no high-severity findings in `zvmsdk/db/`.
- Password is never printed in any log at any log level.
- All operator documentation covers the upgrade path end to end.
- Pool metrics are visible in whatever observability system feilong uses.

---

## Testing Strategy Summary

### Test pyramid

| Layer | Framework | Scope | DB required |
|-------|-----------|-------|-------------|
| Unit | `pytest` + `unittest.mock` | Single method; mock DB | None |
| Integration (SQLite) | `pytest` | Full operator; real DB | In-memory SQLite |
| Integration (MariaDB) | `pytest` | Full operator; real DB | MariaDB service |
| FVT | Existing fvt suite | REST API end to end | MariaDB or SQLite |

### Regression gates

The following must not regress at any phase boundary:
1. All existing unit tests pass.
2. All FVT tests pass in `backend=sqlite` mode.
3. `grep` checks for banned patterns (`conn.execute("`, `IS NOT ''`, `COLLATE NOCASE`) return empty.

---

## Rollout Sequence for Operators

For an existing single-node deployment:

```
1.  pip install --upgrade feilong        # installs SQLAlchemy, Alembic, PyMySQL
2.  feilong-db upgrade                   # runs: alembic upgrade head (adds compute_node_id)
3.  [optional] Install & configure MariaDB on the same host
4.  python tools/migrate_sqlite_to_mariadb.py \
        --sqlite-dir /var/lib/zvmsdk/databases/ \
        --config /etc/zvmsdk/zvmsdk.conf \
        --compute-node-id $(hostname)
5.  Edit zvmsdk.conf: backend=mariadb, mode=local
6.  systemctl restart feilong
7.  Verify: feilong-db check   # runs: alembic current == head
```

For a multi-node OpenStack deployment (adding remote mode):

```
1.  On management node: provision MariaDB, create database + user (§9.1 of architecture)
2.  On each compute node: perform steps 1–4 above (local data migrated per node)
3.  On ONE designated node: run alembic upgrade head to add remote FKs (migration 0004)
4.  On each compute node: edit zvmsdk.conf: mode=remote, host=<mgmt-node-ip>
5.  Rolling restart of feilong on all compute nodes
```

---

## Definition of Done (overall project)

- [ ] All 9 phases merged to `master`.
- [ ] All unit tests pass with zero failures.
- [ ] All MariaDB integration tests pass with zero failures.
- [ ] FVT suite passes in local-SQLite, local-MariaDB, and remote-MariaDB modes.
- [ ] `alembic upgrade head` / `alembic downgrade base` round-trip verified on both backends.
- [ ] Migration tool migrates a production-scale dataset (10k guests, 1k FCP devices)
  in under 5 minutes.
- [ ] No high-severity `bandit` findings.
- [ ] Operator documentation merged to `doc/`.
- [ ] `CHANGES` / release notes entry written.