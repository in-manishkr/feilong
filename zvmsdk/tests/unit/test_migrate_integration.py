#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""End-to-end integration tests for the SQLite→MariaDB migration tool — Phase 8 Task 8.3.

SQLite-to-SQLite tests run without any external dependencies and always execute.
SQLite-to-MariaDB tests are skipped unless ZVMSDK_TEST_DB_URL is set.

Set ZVMSDK_TEST_DB_URL to a PyMySQL URL to enable MariaDB target tests:
  export ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk_test"
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from zvmsdk import config
from zvmsdk.tests.unit import base

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from tools import migrate_sqlite_to_mariadb as mig

CONF = config.CONF
_DB_URL = os.environ.get('ZVMSDK_TEST_DB_URL', '')
_SKIP_MARIADB = unittest.skipUnless(
    _DB_URL,
    'ZVMSDK_TEST_DB_URL not set — skipping MariaDB migration integration tests',
)

_BASELINE_TABLES = {
    'switch', 'guests', 'image', 'fcp',
    'template', 'template_sp_mapping', 'template_fcp_mapping',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


def _drop_all_mariadb_tables():
    engine = create_engine(_DB_URL, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for tbl in list(_BASELINE_TABLES) + ['compute_nodes', 'alembic_version']:
                conn.execute(text("DROP TABLE IF EXISTS `%s`" % tbl))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        engine.dispose()


def _run_main(argv):
    """Run mig.main(), catching the SystemExit it always produces.

    Returns the exit code (0 = success, 1 = error).
    """
    try:
        mig.main(argv)
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


def _create_source_switch_sqlite(src_dir, rows=2):
    """Create sdk_network.sqlite with old pre-migration schema."""
    path = os.path.join(src_dir, 'sdk_network.sqlite')
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE switch "
                "(userid TEXT, interface TEXT, switch TEXT, "
                "port TEXT, comments TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO switch VALUES (?,?,?,?,?)",
                    ('VM%03d' % i, 'eth0', 'VS1', str(i), ''))
    con.commit()
    con.close()
    return path


def _create_source_guest_sqlite(src_dir, rows=3):
    """Create sdk_guest.sqlite with old pre-migration schema."""
    path = os.path.join(src_dir, 'sdk_guest.sqlite')
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE guests "
                "(id TEXT, userid TEXT, metadata TEXT, "
                "net_set INTEGER, comments TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO guests VALUES (?,?,?,?,?)",
                    ('uuid-%04d' % i, 'GU%04d' % i, '', 0, ''))
    con.commit()
    con.close()
    return path


def _create_source_image_sqlite(src_dir, rows=1):
    """Create sdk_image.sqlite with old pre-migration schema."""
    path = os.path.join(src_dir, 'sdk_image.sqlite')
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE image "
                "(imagename TEXT, imageosdistro TEXT, md5sum TEXT, "
                "disk_size_units TEXT, image_size_in_bytes TEXT, "
                "type TEXT, comments TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO image VALUES (?,?,?,?,?,?,?)",
                    ('img-%04d' % i, 'rhel8', 'abc%d' % i,
                     '3338:CYL', '5368709120', 'netboot', ''))
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------------------
# Task 8.3 — SQLite-to-SQLite (no MariaDB required)
# ---------------------------------------------------------------------------

class TestMigrationIntegrationSQLite(unittest.TestCase):
    """End-to-end migration: old-style per-table SQLite → new consolidated SQLite."""

    def setUp(self):
        self.src_dir = tempfile.mkdtemp()
        self.tgt_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'dir', self.tgt_dir)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'INTEG-TEST-NODE')

    def tearDown(self):
        shutil.rmtree(self.src_dir, ignore_errors=True)
        shutil.rmtree(self.tgt_dir, ignore_errors=True)
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'compute_node_id', None)
        base.set_conf('database', 'mode', 'local')

    def _tgt_db(self):
        return os.path.join(self.tgt_dir, 'zvmsdk.db')

    def test_switch_rows_migrated_with_compute_node_id(self):
        """switch rows appear in target with correct compute_node_id tag."""
        _create_source_switch_sqlite(self.src_dir, rows=2)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 0)

        con = sqlite3.connect(self._tgt_db())
        rows = con.execute(
            "SELECT userid, compute_node_id FROM switch").fetchall()
        con.close()

        self.assertEqual(len(rows), 2)
        for _, node_id in rows:
            self.assertEqual(node_id, 'INTEG-TEST-NODE')

    def test_guest_rows_migrated_with_compute_node_id(self):
        """guests rows appear in target with correct compute_node_id tag."""
        _create_source_guest_sqlite(self.src_dir, rows=3)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 0)

        con = sqlite3.connect(self._tgt_db())
        rows = con.execute(
            "SELECT userid, compute_node_id FROM guests").fetchall()
        con.close()

        self.assertEqual(len(rows), 3)
        for _, node_id in rows:
            self.assertEqual(node_id, 'INTEG-TEST-NODE')

    def test_image_rows_migrated_with_global_node_id(self):
        """image rows always get compute_node_id='GLOBAL' regardless of node."""
        _create_source_image_sqlite(self.src_dir, rows=2)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 0)

        con = sqlite3.connect(self._tgt_db())
        rows = con.execute(
            "SELECT imagename, compute_node_id FROM image").fetchall()
        con.close()

        self.assertEqual(len(rows), 2)
        for _, node_id in rows:
            self.assertEqual(node_id, 'GLOBAL',
                             "Image rows must always use compute_node_id='GLOBAL'")

    def test_idempotent_rerun_no_duplicate_rows(self):
        """Running the migration twice must not insert duplicate rows."""
        _create_source_switch_sqlite(self.src_dir, rows=5)

        # First run
        code1 = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code1, 0)

        # Reset engine so second run calls get_engine() fresh
        _reset_engine_globals()
        base.set_conf('database', 'dir', self.tgt_dir)

        # Second run — must not fail, must not duplicate
        code2 = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code2, 0)

        con = sqlite3.connect(self._tgt_db())
        count = con.execute("SELECT COUNT(*) FROM switch").fetchone()[0]
        con.close()

        self.assertEqual(count, 5, "No duplicate rows after idempotent rerun")

    def test_dry_run_writes_no_rows_to_target(self):
        """--dry-run must not write any data rows to the target database."""
        _create_source_switch_sqlite(self.src_dir, rows=4)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
            '--dry-run',
        ])
        self.assertEqual(code, 0)

        tgt = self._tgt_db()
        if os.path.exists(tgt):
            con = sqlite3.connect(tgt)
            try:
                count = con.execute("SELECT COUNT(*) FROM switch").fetchone()[0]
            except sqlite3.OperationalError:
                # Table may not exist at all in dry-run if schema not created
                count = 0
            finally:
                con.close()
            self.assertEqual(count, 0,
                             "--dry-run must not write data rows to target")

    def test_missing_source_file_is_skipped_no_exception(self):
        """A missing source SQLite file logs a warning and continues."""
        # Only create one source file; others in SOURCE_MAP are absent
        _create_source_guest_sqlite(self.src_dir, rows=2)

        # Should succeed (exit 0) even though most source files are missing
        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 0,
                         "Missing source files must be warned/skipped, not raise")

    def test_exit_code_1_on_count_mismatch(self):
        """Exit code is 1 when PK conflicts prevent source rows from landing.

        Strategy: pre-populate the target guests table with the SAME row ids
        but a different compute_node_id.  INSERT OR IGNORE skips those rows
        (PK conflict on the `id` column).  The post-migration count WHERE
        compute_node_id='INTEG-TEST-NODE' is 0, while source count is 3 →
        mismatch → exit 1.
        """
        _create_source_guest_sqlite(self.src_dir, rows=3)

        # Create schema without migrating data
        from zvmsdk.db import migration as db_migration
        from zvmsdk.db import api as db_api
        from sqlalchemy import text as sa_text

        db_migration.ensure_schema_current()
        db_api.register_compute_node()

        # Pre-populate with same UUIDs under a *different* compute_node_id
        engine = db_api.get_engine()
        with engine.begin() as conn:
            for i in range(3):
                conn.execute(
                    sa_text("INSERT INTO guests "
                            "(id, userid, compute_node_id, net_set) "
                            "VALUES (:id, :uid, 'OTHER-NODE', 0)"),
                    {'id': 'uuid-%04d' % i, 'uid': 'GU%04d' % i})

        # Reset so migration tool creates a fresh engine pointing at same file
        _reset_engine_globals()
        base.set_conf('database', 'dir', self.tgt_dir)
        base.set_conf('database', 'compute_node_id', 'INTEG-TEST-NODE')

        # Run migration — INSERT OR IGNORE skips every row (PK conflict on id)
        # COUNT WHERE compute_node_id='INTEG-TEST-NODE' == 0, source == 3
        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 1,
                         "Count mismatch must produce exit code 1")

    def test_multiple_source_tables_in_one_run(self):
        """All provided source tables are migrated in a single invocation."""
        _create_source_switch_sqlite(self.src_dir, rows=2)
        _create_source_guest_sqlite(self.src_dir, rows=3)
        _create_source_image_sqlite(self.src_dir, rows=1)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
        ])
        self.assertEqual(code, 0)

        con = sqlite3.connect(self._tgt_db())
        switch_count = con.execute("SELECT COUNT(*) FROM switch").fetchone()[0]
        guest_count = con.execute("SELECT COUNT(*) FROM guests").fetchone()[0]
        image_count = con.execute("SELECT COUNT(*) FROM image").fetchone()[0]
        con.close()

        self.assertEqual(switch_count, 2)
        self.assertEqual(guest_count, 3)
        self.assertEqual(image_count, 1)

    def test_batch_size_respected_for_large_dataset(self):
        """--batch-size controls INSERT granularity; all rows still arrive."""
        _create_source_guest_sqlite(self.src_dir, rows=50)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'sqlite',
            '--compute-node-id', 'INTEG-TEST-NODE',
            '--batch-size', '10',
        ])
        self.assertEqual(code, 0)

        con = sqlite3.connect(self._tgt_db())
        count = con.execute("SELECT COUNT(*) FROM guests").fetchone()[0]
        con.close()

        self.assertEqual(count, 50, "All 50 rows must arrive regardless of batch size")


# ---------------------------------------------------------------------------
# Task 8.3 — SQLite-to-MariaDB (requires ZVMSDK_TEST_DB_URL)
# ---------------------------------------------------------------------------

@_SKIP_MARIADB
class TestMigrationIntegrationMariaDB(unittest.TestCase):
    """Full migration: old-style SQLite files → live MariaDB."""

    def setUp(self):
        self.src_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        _drop_all_mariadb_tables()
        base.set_conf('database', 'backend', 'mariadb')
        base.set_conf('database', 'connection', _DB_URL)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'MARIADB-INTEG-NODE')
        base.set_conf('database', 'pool_size', 5)
        base.set_conf('database', 'pool_max_overflow', 10)
        base.set_conf('database', 'pool_timeout', 30)
        base.set_conf('database', 'pool_recycle', 3600)

    def tearDown(self):
        shutil.rmtree(self.src_dir, ignore_errors=True)
        _drop_all_mariadb_tables()
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'connection', None)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', None)

    def _count_in_mariadb(self, table, node_id='MARIADB-INTEG-NODE'):
        engine = create_engine(_DB_URL, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                effective = 'GLOBAL' if table == 'image' else node_id
                return conn.execute(
                    text("SELECT COUNT(*) FROM `%s` "
                         "WHERE compute_node_id=:n" % table),
                    {'n': effective}).fetchone()[0]
        finally:
            engine.dispose()

    def test_full_migration_switch_to_mariadb(self):
        """switch rows are migrated from SQLite to MariaDB with correct node tag."""
        _create_source_switch_sqlite(self.src_dir, rows=5)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'mariadb',
            '--compute-node-id', 'MARIADB-INTEG-NODE',
        ])
        self.assertEqual(code, 0)
        self.assertEqual(self._count_in_mariadb('switch'), 5)

    def test_full_migration_guests_to_mariadb(self):
        """guests rows are migrated to MariaDB with correct compute_node_id."""
        _create_source_guest_sqlite(self.src_dir, rows=4)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'mariadb',
            '--compute-node-id', 'MARIADB-INTEG-NODE',
        ])
        self.assertEqual(code, 0)
        self.assertEqual(self._count_in_mariadb('guests'), 4)

    def test_full_migration_images_use_global_node_id(self):
        """image rows are migrated to MariaDB with compute_node_id='GLOBAL'."""
        _create_source_image_sqlite(self.src_dir, rows=2)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'mariadb',
            '--compute-node-id', 'MARIADB-INTEG-NODE',
        ])
        self.assertEqual(code, 0)
        self.assertEqual(self._count_in_mariadb('image'), 2)

    def test_idempotent_rerun_mariadb_no_duplicates(self):
        """Re-running the migration against MariaDB produces no duplicate rows."""
        _create_source_switch_sqlite(self.src_dir, rows=3)

        argv = [
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'mariadb',
            '--compute-node-id', 'MARIADB-INTEG-NODE',
        ]
        code1 = _run_main(argv)
        self.assertEqual(code1, 0)

        _reset_engine_globals()
        base.set_conf('database', 'connection', _DB_URL)
        base.set_conf('database', 'compute_node_id', 'MARIADB-INTEG-NODE')

        code2 = _run_main(argv)
        self.assertEqual(code2, 0)
        self.assertEqual(self._count_in_mariadb('switch'), 3,
                         "Idempotent rerun must not create duplicates")

    def test_migration_row_counts_match_source(self):
        """Source and target row counts match for all migrated tables."""
        _create_source_switch_sqlite(self.src_dir, rows=7)
        _create_source_guest_sqlite(self.src_dir, rows=9)
        _create_source_image_sqlite(self.src_dir, rows=3)

        code = _run_main([
            '--sqlite-dir', self.src_dir,
            '--target-backend', 'mariadb',
            '--compute-node-id', 'MARIADB-INTEG-NODE',
        ])
        self.assertEqual(code, 0)
        self.assertEqual(self._count_in_mariadb('switch'), 7)
        self.assertEqual(self._count_in_mariadb('guests'), 9)
        self.assertEqual(self._count_in_mariadb('image'), 3)


if __name__ == '__main__':
    unittest.main()
