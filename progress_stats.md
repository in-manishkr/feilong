# SQLite → MariaDB/MySQL Migration — Progress Stats

Reference: `dev.md`  
Last updated: 2026-06-28

---

## Phase Completion Status

| Phase | Name                                        | Status    | Completed  | Tests    |
|-------|---------------------------------------------|-----------|------------|----------|
| 1     | SQLAlchemy engine factory (SQLite only)     | ✅ DONE   | 2026-06-27 | Pass     |
| 2     | Table definitions + Alembic bootstrap       | ✅ DONE   | 2026-06-27 | Pass     |
| 3     | Refactor `database.py` connection managers  | ✅ DONE   | 2026-06-27 | Pass     |
| 4     | MariaDB/MySQL backend support               | ✅ DONE   | 2026-06-27 | Pass     |
| 5     | `compute_node_id` schema extension          | ✅ DONE   | 2026-06-27 | Pass     |
| 6     | Remote mode — node registration + scoped queries | ✅ DONE | 2026-06-28 | Pass |
| 7     | Data migration tool                         | ✅ DONE   | 2026-06-28 | Pass     |
| 8     | Integration testing (OpenStack + z/VM)      | ✅ DONE   | 2026-06-28 | Pass     |
| 9     | Hardening, monitoring, and documentation    | ✅ DONE   | 2026-06-28 | Pass     |

---

## Phase 1 — SQLAlchemy Engine Factory
**Branch:** `byodb`  
**Key deliverables:**
- `zvmsdk/db/__init__.py` — new package
- `zvmsdk/db/api.py` — `get_engine()`, `get_connection()`, `_resolve_compute_node_id()`
- `zvmsdk/config.py` — 17 new `[database]` opts
- `zvmsdk/tests/unit/test_db_api.py` — 12 unit tests

**Test count:** 12 tests (all pass)

---

## Phase 2 — Table Definitions + Alembic Bootstrap
**Key deliverables:**
- `zvmsdk/db/models.py` — 8 SQLAlchemy table definitions
- `zvmsdk/db/migration.py` — `ensure_schema_current()`
- `zvmsdk/db/alembic/` — alembic directory (`alembic.ini`, `env.py`, `script.py.mako`)
- `zvmsdk/db/alembic/versions/0001_initial_sqlite_baseline.py` — baseline migration
- `zvmsdk/tests/unit/test_db_models.py` — 5 unit tests
- `zvmsdk/tests/unit/test_alembic_sqlite.py` — 5 integration tests

**Test count:** 10 tests (all pass)

---

## Phase 3 — Refactor `database.py` Connection Managers
**Key deliverables:**
- `zvmsdk/database.py` — removed 5 conn globals, 5 RLocks, `_init_db_conn()`; converted all SQL to `text()` named params; added `_CompatRow` wrapper
- `zvmsdk/smtclient.py` — added `ensure_schema_current()` before operator init
- `zvmsdk/tests/unit/test_database.py` — updated 84 tests for SQLAlchemy
- `zvmsdk/tests/unit/test_database_connection_managers.py` — 13 new regression tests

**Key design — `_CompatRow`:** Wraps SQLAlchemy `Row` to support both positional (`row[0]`) and string-key (`row['col']`) access, mirroring the sqlite3.Row behavior.

**Test count:** 97 tests (84 existing + 13 new, all pass)

---

## Phase 4 — MariaDB/MySQL Backend Support
**Key deliverables:**
- `zvmsdk/db/api.py` — MariaDB engine path (QueuePool, pool_pre_ping, SSL)
- `zvmsdk/db/alembic/versions/0002_initial_mariadb.py` — MariaDB baseline migration
- `zvmsdk/db/migration.py` — `_stamp_mariadb_if_fresh()` to skip SQLite-specific migration
- `zvmsdk/constants.py` — comment on unused `DATABASE_VOLUME`
- `zvmsdk/tests/unit/test_mariadb_connectivity.py` — 8 smoke tests (auto-skip without ZVMSDK_TEST_DB_URL)
- `zvmsdk/tests/unit/test_database_mariadb.py` — 13 operator integration tests (auto-skip)

**Alembic location:** `zvmsdk/db/alembic/` (not repo-root `alembic/`)

**Test count:** 21 new tests (auto-skip without MariaDB; pass when ZVMSDK_TEST_DB_URL is set)

---

## Phase 5 — `compute_node_id` Schema Extension
**Key deliverables:**
- `zvmsdk/db/alembic/versions/0003_add_compute_node_support.py` — adds `compute_node_id` to all data tables, creates `compute_nodes` registry
- `zvmsdk/db/models.py` — updated PKs to composite keys
- `zvmsdk/database.py` — injected `compute_node_id` into all write-path INSERT methods
- `zvmsdk/tests/unit/test_compute_node_id_injection.py` — 10 unit tests

**Key design — write-path injection:** All INSERTs to node-scoped tables call `db_api.get_compute_node_id()`. Read-path queries intentionally do NOT filter by node (local mode backward-compat; filtering added in Phase 6).

**Test count:** 10 tests (all pass)

---

## Phase 6 — Remote Mode: Node Registration + Scoped Queries
**Key deliverables:**
- `zvmsdk/db/api.py` — added `register_compute_node()` (UPSERT on startup), `deregister_compute_node()` (set inactive on shutdown)
- `zvmsdk/db/alembic/versions/0004_add_remote_mode_fks.py` — conditionally adds FK constraints to `compute_nodes` when `mode=remote` (no-op in local mode)
- `zvmsdk/database.py` — added `_node_filter(prefix=None)` helper; applied to all read-path queries in NetworkDbOperator, FCPDbOperator, ImageDbOperator, GuestDbOperator
- `zvmsdk/smtclient.py` — startup sequence now calls `verify_remote_connectivity()` then `register_compute_node()` after `ensure_schema_current()`
- `zvmsdk/tests/unit/test_remote_mode.py` — 12 unit tests

**Key design decisions:**
- `_node_filter()` returns `("", {})` in local mode → zero behavioral change for existing deployments
- `_node_filter(prefix='fcp')` returns `" AND fcp.compute_node_id = :node_id"` in remote mode for JOIN queries
- Migration 0004 is a no-op for SQLite (FK enforcement not needed) and for local-mode MariaDB
- `deregister_compute_node()` silently logs on failure (SDK shutdown should not raise)

**Methods with node-scoped reads (remote mode only):**

| Operator | Methods |
|---|---|
| NetworkDbOperator | `switch_select_table()`, `switch_select_record_for_userid()`, `switch_select_record()` |
| GuestDbOperator | `get_guest_list()`, `get_guest_by_userid()`, `get_guest_metadata_with_userid()` |
| ImageDbOperator | `image_query_record()` |
| FCPDbOperator | `get_all()`, `get_all_fcps_of_assigner()`, `get_usage_of_fcp()`, `get_connections_from_fcp()`, `get_inuse_fcp_device_by_fcp_template()`, `get_path_count()`, `fcp_template_exist_in_db()`, `get_min_fcp_paths_count_from_db()`, `get_allocated_fcps_from_assigner()`, `get_reserved_fcps_from_assigner()`, `get_fcp_devices_with_same_index()`, `get_pchids_by_fcp_template()`, `get_free_pchids_by_fcp_template()`, `get_host_default_fcp_template()`, `get_sp_default_fcp_template()`, `get_fcp_template_by_assigner_id()`, `get_fcp_templates()`, `get_fcp_templates_details()`, `get_wwpn_phy_from_pchids()`, `get_pchids_from_all_fcp_templates()`, `get_pchids_of_all_inuse_fcp_devices()` |

**Test count:** 12 new tests (all pass). Total db-layer tests: 146 pass, 21 skip (MariaDB).

---

## Phase 7 — Data Migration Tool
**Key deliverables:**
- `tools/migrate_sqlite_to_mariadb.py` — CLI tool to migrate per-table SQLite files to MariaDB (or consolidated SQLite)
- `zvmsdk/tests/unit/test_migrate_tool.py` — 19 unit tests

**Architecture:**
- `SOURCE_MAP`: maps each source SQLite file to its tables, with `src_cols` (old schema) and `tgt_cols` (new schema including `compute_node_id`)
- `_build_insert_sql()`: dialect-aware `INSERT IGNORE` (MariaDB/MySQL) vs `INSERT OR IGNORE` (SQLite)
- `_inject_node_id()`: stamps every migrated row with the resolved `compute_node_id`; images use `'GLOBAL'`
- `_migrate_table()`: reads source rows, injects node_id, inserts in configurable batches (default 500), verifies count in target
- `main()`: parses args, applies config, upgrades target schema, registers node, then migrates all tables; prints summary with OK/MISMATCH/ERROR per table; exits 1 on any mismatch

**Key design decisions:**
- SDK imports (`db_api`, `db_migration`, `zvm_config`) at module level so tests can patch them via `mock.patch('tools.migrate_sqlite_to_mariadb.db_api')` without reaching inside `main()`
- Source SQLite files are never modified (idempotent — re-run is safe because INSERT IGNORE/INSERT OR IGNORE skips duplicates)
- `--dry-run` prints source counts only; no rows written, no schema changes
- Image rows always get `compute_node_id='GLOBAL'` regardless of the node running the migration

**Test count:** 19 tests (all pass). Total db-layer tests: 165 pass (no skips in unit tests).

---

## Phase 8 — Integration Testing
**Key deliverables:**
- `zvmsdk/tests/unit/test_remote_mode_mariadb.py` — Task 8.2: remote-mode isolation (guest/switch/image), upsert idempotency, deregister, FK cascade, SSL/TLS. 13 tests (skip without `ZVMSDK_TEST_DB_URL`).
- `zvmsdk/tests/unit/test_migrate_integration.py` — Task 8.3: end-to-end migration tests. 9 SQLite tests (always run) + 5 MariaDB tests (skip without URL).
- `zvmsdk/tests/unit/test_concurrent_startup.py` — Task 8.5: concurrent schema creation, sequential node registration UPSERT idempotency, engine singleton under concurrency. 10 tests (always run).
- `zvmsdk/db/migration.py` — Added `_MIGRATION_LOCK` to serialise concurrent `ensure_schema_current()` calls within a process (prevents SQLite "database is locked" and MariaDB duplicate-DDL races).

**Key design decisions:**
- `test_remote_mode_mariadb.py` simulates two nodes by swapping `db_api._COMPUTE_NODE_ID` between `NODE_A` and `NODE_B` — no separate process needed for isolation tests
- `test_migrate_integration.py` tests count-mismatch exit 1 by pre-populating target with same `id` values under a different `compute_node_id`, causing INSERT OR IGNORE to skip all rows
- Concurrent SQLite tests are sequential (StaticPool single-connection limitation); true multi-process concurrency tests are in `test_remote_mode_mariadb.py` for MariaDB

**Tasks 8.1 and 8.4 notes:**
- Task 8.1 (local-mode MariaDB regression): covered by existing `test_database_mariadb.py` (13 tests, skip without URL)
- Task 8.4 (SSL/TLS): `TestSSLConnectionMariaDB` in `test_remote_mode_mariadb.py` covers SSL cipher verification (skip without `ZVMSDK_TEST_DB_SSL_URL` + `ZVMSDK_TEST_DB_SSL_CA`)

**Test count:** 32 new tests (10 always-run SQLite, 22 MariaDB-skip). Total: 184 pass, 18 skip.

---

## Running Tests

```bash
# All DB layer unit tests (no external dependencies)
python3 -m pytest zvmsdk/tests/unit/test_database.py \
  zvmsdk/tests/unit/test_database_connection_managers.py \
  zvmsdk/tests/unit/test_db_api.py \
  zvmsdk/tests/unit/test_db_models.py \
  zvmsdk/tests/unit/test_alembic_sqlite.py \
  zvmsdk/tests/unit/test_compute_node_id_injection.py \
  zvmsdk/tests/unit/test_remote_mode.py \
  zvmsdk/tests/unit/test_migrate_tool.py \
  zvmsdk/tests/unit/test_migrate_integration.py \
  zvmsdk/tests/unit/test_concurrent_startup.py \
  zvmsdk/tests/unit/test_remote_mode_mariadb.py \
  -v

# MariaDB integration tests (requires ZVMSDK_TEST_DB_URL)
ZVMSDK_TEST_DB_URL="mysql+pymysql://user:pass@host/zvmsdk" \
  python3 -m pytest zvmsdk/tests/unit/test_mariadb_connectivity.py \
                    zvmsdk/tests/unit/test_database_mariadb.py -v
```

---

## Phase 9 — Hardening, Monitoring, and Documentation
**Key deliverables:**
- `zvmsdk/db/api.py` — Pool event listeners (`_register_pool_events`), `get_pool_status()`, `ZVMSDK_DB_PASSWORD` env-var fallback in `_build_url()`, `_mark_stale_nodes_inactive()`, `check_stale_nodes()`, bandit `# nosec` suppressions
- `zvmsdk/db/migration.py` — `_MIGRATION_LOCK` for concurrent Alembic safety; bandit `# nosec B110` on try/except/pass
- `zvmsdk/constants.py` — Deprecation notices on all `DATABASE_*` constants
- `doc/source/admin/database_migration.rst` — Step-by-step SQLite → SQLite and SQLite → MariaDB upgrade guides with rollback procedure
- `doc/source/admin/database_ha.rst` — Galera Cluster and ProxySQL HA guides; pool sizing table; stale node detection; FK cascade warning
- `doc/source/admin/database_ssl.rst` — TLS/mTLS certificate generation, MariaDB and feilong config, verification, `ZVMSDK_DB_PASSWORD` security note, troubleshooting table
- `data/zvmsdk.conf` — Comprehensive `[database]` section documenting all 17+ new configuration options
- `zvmsdk/tests/unit/test_hardening.py` — 18 unit tests covering pool metrics, credential hardening, stale node health-check, deprecated constants, bandit audit

**Key design decisions:**
- `ZVMSDK_DB_PASSWORD` env var acts as fallback only when config password is empty (config wins if set)
- `check_stale_nodes()` swallows all exceptions — startup must never fail due to stale-node check
- `_mark_stale_nodes_inactive()` is dialect-aware: `NOW() - INTERVAL :s SECOND` (MariaDB) vs `datetime('now', '-N seconds')` (SQLite)
- bandit: 0 medium/high findings in `zvmsdk/db/`; 5 low-severity all legitimately suppressed with `# nosec` and justification comments
- Pool events registered via `event.listens_for` on engine creation; module-level counters survive across connection checkouts

**Test count:** 18 new tests (all always-run, 0 skip). Total: 202 pass, 26 skip.

---

## Alembic Migration Chain

```
0001_initial_sqlite_baseline  →  0002_initial_mariadb  →  0003_add_compute_node_support  →  0004_add_remote_mode_fks
```

- **0001**: SQLite baseline (all 7 data tables, no compute_node_id)
- **0002**: MariaDB baseline (same 7 tables with InnoDB/utf8mb4; no-op for SQLite)
- **0003**: Adds compute_node_id to all tables, creates compute_nodes registry
- **0004**: Adds FK constraints to compute_nodes (only when mode=remote; no-op otherwise)
