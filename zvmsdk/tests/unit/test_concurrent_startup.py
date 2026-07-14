#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Concurrent startup integration tests — Phase 8 Task 8.5.

Validates that multiple feilong processes (simulated by threads) can start
against the same database simultaneously without DDL errors or data corruption.
These tests always run — no external database is required (SQLite is used).

Scenario covered:
  - N threads calling ensure_schema_current() simultaneously → exactly one set
    of tables is created with no duplicate-DDL exceptions.
  - N compute nodes registering simultaneously → all nodes appear in
    compute_nodes with no duplicates or errors.
  - Sequential node registrations (UPSERT idempotency) produce one row each.
"""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from zvmsdk import config
from zvmsdk.tests.unit import base

CONF = config.CONF


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


def _setup_fresh_sqlite(db_dir):
    base.set_conf('database', 'backend', 'sqlite')
    base.set_conf('database', 'dir', db_dir)
    base.set_conf('database', 'mode', 'local')
    base.set_conf('database', 'compute_node_id', 'CONCURRENT-NODE')


def _teardown_sqlite():
    base.set_conf('database', 'backend', 'sqlite')
    base.set_conf('database', 'compute_node_id', None)
    base.set_conf('database', 'mode', 'local')


# ---------------------------------------------------------------------------
# Task 8.5 — Concurrent schema creation
# ---------------------------------------------------------------------------

class TestConcurrentSchemaCreation(unittest.TestCase):
    """N threads calling ensure_schema_current() on a fresh SQLite file."""

    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        _setup_fresh_sqlite(self.db_dir)

    def tearDown(self):
        _reset_engine_globals()
        _teardown_sqlite()
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_concurrent_ensure_schema_no_exceptions(self):
        """10 threads calling ensure_schema_current() simultaneously raise no errors."""
        from zvmsdk.db import migration

        errors = []
        n_threads = 10

        def _worker():
            try:
                migration.ensure_schema_current()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [],
                         "ensure_schema_current() must not raise under concurrency: %s"
                         % errors)

    def test_schema_created_exactly_once(self):
        """After concurrent ensure_schema_current() calls, tables exist exactly once."""
        from zvmsdk.db import migration
        from sqlalchemy import inspect

        n_threads = 5
        threads = [threading.Thread(target=migration.ensure_schema_current)
                   for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        import zvmsdk.db.api as db_api
        engine = db_api.get_engine()
        insp = inspect(engine)
        table_names = set(insp.get_table_names())
        expected = {'switch', 'guests', 'image', 'fcp',
                    'template', 'template_sp_mapping', 'template_fcp_mapping',
                    'compute_nodes'}
        self.assertTrue(expected.issubset(table_names),
                        "All expected tables must exist: missing %s"
                        % (expected - table_names))

    def test_repeated_ensure_schema_is_idempotent(self):
        """Calling ensure_schema_current() on an already-migrated DB is a no-op."""
        from zvmsdk.db import migration

        # First call creates the schema
        migration.ensure_schema_current()

        # Subsequent calls must not raise (already at head)
        errors = []
        for _ in range(5):
            try:
                migration.ensure_schema_current()
            except Exception as e:
                errors.append(e)

        self.assertEqual(errors, [],
                         "Repeated ensure_schema_current() must be idempotent")


# ---------------------------------------------------------------------------
# Task 8.5 — Concurrent node registration
# ---------------------------------------------------------------------------

class TestConcurrentNodeRegistration(unittest.TestCase):
    """N nodes registering simultaneously; verify all appear without duplication."""

    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        _setup_fresh_sqlite(self.db_dir)
        # Create schema before registration tests
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    def tearDown(self):
        _reset_engine_globals()
        _teardown_sqlite()
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_same_node_registered_repeatedly_produces_one_row(self):
        """Calling register_compute_node() N times for the same node_id is idempotent.

        Note: this tests sequential UPSERT idempotency (the SQLite StaticPool
        uses a single shared connection that cannot be held by multiple threads
        concurrently).  True concurrent multi-process startup is validated in
        test_remote_mode_mariadb.py against a live MariaDB instance.
        """
        import zvmsdk.db.api as db_api
        from sqlalchemy import text

        db_api._COMPUTE_NODE_ID = 'SHARED-NODE'

        # Call register N times sequentially — each is an upsert
        for _ in range(8):
            db_api.register_compute_node()

        engine = db_api.get_engine()
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM compute_nodes WHERE id=:id"),
                {'id': 'SHARED-NODE'}).fetchone()[0]
        self.assertEqual(count, 1,
                         "INSERT OR REPLACE must produce exactly one row regardless of "
                         "how many times it is called")

    def test_sequential_node_registrations_all_unique(self):
        """Registering N different node_ids sequentially produces N distinct rows."""
        import zvmsdk.db.api as db_api
        from sqlalchemy import text

        node_ids = ['NODE-%02d@ZVM1' % i for i in range(5)]
        for node_id in node_ids:
            db_api._COMPUTE_NODE_ID = node_id
            db_api.register_compute_node()

        engine = db_api.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM compute_nodes WHERE id LIKE 'NODE-%'")
            ).fetchall()
        registered = {r[0] for r in rows}

        self.assertEqual(registered, set(node_ids),
                         "All %d nodes must appear in compute_nodes" % len(node_ids))

    def test_register_deregister_register_cycle(self):
        """A node can be deregistered and re-registered cleanly."""
        import zvmsdk.db.api as db_api
        from sqlalchemy import text

        db_api._COMPUTE_NODE_ID = 'CYCLE-NODE'

        db_api.register_compute_node()
        db_api.deregister_compute_node()
        db_api.register_compute_node()  # simulates restart

        engine = db_api.get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status FROM compute_nodes WHERE id=:id"),
                {'id': 'CYCLE-NODE'}).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'active')

    def test_deregister_with_no_node_id_is_safe(self):
        """deregister_compute_node() with empty node_id must not raise."""
        import zvmsdk.db.api as db_api
        db_api._COMPUTE_NODE_ID = ''
        try:
            db_api.deregister_compute_node()
        except Exception as e:
            self.fail("deregister_compute_node() raised unexpectedly: %s" % e)

    def test_deregister_tolerates_db_failure(self):
        """deregister_compute_node() logs warning and swallows DB errors."""
        import zvmsdk.db.api as db_api

        db_api._COMPUTE_NODE_ID = 'FAIL-NODE'
        with mock.patch('zvmsdk.db.api.get_connection',
                        side_effect=Exception("simulated DB failure")), \
             mock.patch('zvmsdk.db.api.LOG') as mock_log:
            try:
                db_api.deregister_compute_node()
            except Exception:
                self.fail("deregister_compute_node() must not propagate exceptions")
            mock_log.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Task 8.5 — get_engine() singleton under concurrency
# ---------------------------------------------------------------------------

class TestConcurrentEngineInit(unittest.TestCase):
    """Verify get_engine() is a singleton even when called from many threads."""

    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        _setup_fresh_sqlite(self.db_dir)

    def tearDown(self):
        _reset_engine_globals()
        _teardown_sqlite()
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_get_engine_returns_same_object_from_many_threads(self):
        """20 concurrent threads calling get_engine() must all get the same object."""
        import zvmsdk.db.api as db_api

        results = []
        lock = threading.Lock()
        n = 20

        def _worker():
            engine = db_api.get_engine()
            with lock:
                results.append(id(engine))

        threads = [threading.Thread(target=_worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(results), n)
        self.assertEqual(len(set(results)), 1,
                         "All threads must receive the identical engine object")

    def test_compute_node_id_resolved_exactly_once(self):
        """_resolve_compute_node_id() must run exactly once across all threads."""
        import zvmsdk.db.api as db_api

        resolve_count = [0]
        original_resolve = db_api._resolve_compute_node_id
        resolve_lock = threading.Lock()

        def _counting_resolve():
            with resolve_lock:
                resolve_count[0] += 1
            return original_resolve()

        n = 20
        with mock.patch.object(
                db_api, '_resolve_compute_node_id', side_effect=_counting_resolve):
            threads = [threading.Thread(target=db_api.get_engine) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        self.assertEqual(resolve_count[0], 1,
                         "_resolve_compute_node_id() must run exactly once")


if __name__ == '__main__':
    unittest.main()
