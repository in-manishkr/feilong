#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""MariaDB/MySQL connectivity smoke tests for Phase 4.

These tests verify that get_engine() connects successfully to a real
MariaDB instance and that the database is configured with the expected
charset and collation.

Set ZVMSDK_TEST_DB_URL to a PyMySQL URL to enable:
  export ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk_test"

All tests are skipped automatically when ZVMSDK_TEST_DB_URL is unset.
"""

import os
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from zvmsdk import config
from zvmsdk.tests.unit import base


CONF = config.CONF

_DB_URL = os.environ.get('ZVMSDK_TEST_DB_URL', '')

_SKIP = unittest.skipUnless(
    _DB_URL,
    'ZVMSDK_TEST_DB_URL not set — skipping MariaDB connectivity tests',
)


def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


def _engine():
    return create_engine(_DB_URL, poolclass=NullPool)


@_SKIP
class TestMariaDBConnectivity(unittest.TestCase):
    """Smoke tests: can we connect and is the DB configured correctly?"""

    def test_mariadb_connect(self):
        engine = _engine()
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                row = result.fetchone()
                self.assertEqual(row[0], 1)
        finally:
            engine.dispose()

    def test_mariadb_charset(self):
        engine = _engine()
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SHOW VARIABLES LIKE 'character_set_database'"))
                row = result.fetchone()
                self.assertIsNotNone(row, "character_set_database not found")
                self.assertEqual(row[1], 'utf8mb4',
                                 "Expected utf8mb4 charset, got %r" % row[1])
        finally:
            engine.dispose()

    def test_mariadb_collation(self):
        engine = _engine()
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SHOW VARIABLES LIKE 'collation_database'"))
                row = result.fetchone()
                self.assertIsNotNone(row, "collation_database not found")
                self.assertEqual(row[1], 'utf8mb4_general_ci',
                                 "Expected utf8mb4_general_ci, got %r" % row[1])
        finally:
            engine.dispose()

    def test_pool_pre_ping(self):
        """get_engine() with pool_pre_ping=True must reconnect after stale conn.

        This test exercises the pre_ping path by killing the server-side
        connection directly via KILL CONNECTION and then issuing a new query.
        If pool_pre_ping is active the stale connection is discarded and a
        fresh one is issued transparently.
        """
        from zvmsdk.db import api as db_api

        _reset_engine_globals()
        base.set_conf('database', 'backend', 'mariadb')
        base.set_conf('database', 'connection', _DB_URL)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'smoke-test-node')
        base.set_conf('database', 'pool_size', 1)
        base.set_conf('database', 'pool_max_overflow', 0)
        base.set_conf('database', 'pool_timeout', 5)
        base.set_conf('database', 'pool_recycle', 3600)

        try:
            engine = db_api.get_engine()
            # Obtain a connection and record its process ID.
            with engine.connect() as conn:
                row = conn.execute(text("SELECT CONNECTION_ID()")).fetchone()
                conn_id = row[0]

            # Kill the server-side connection to simulate a stale conn.
            kill_engine = _engine()
            try:
                with kill_engine.connect() as kconn:
                    kconn.execute(text("KILL CONNECTION :cid"),
                                  {'cid': conn_id})
            except Exception:
                pass  # KILL may itself raise on the killed connection
            finally:
                kill_engine.dispose()

            # pool_pre_ping should silently replace the stale connection.
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchone()
                self.assertEqual(result[0], 1)
        finally:
            _reset_engine_globals()
            base.set_conf('database', 'backend', 'sqlite')
            base.set_conf('database', 'connection', None)
            base.set_conf('database', 'mode', 'local')
            base.set_conf('database', 'compute_node_id', None)
            base.set_conf('database', 'pool_size', 5)
            base.set_conf('database', 'pool_max_overflow', 10)
            base.set_conf('database', 'pool_timeout', 30)
            base.set_conf('database', 'pool_recycle', 3600)


@_SKIP
class TestMariaDBAlembicUpgrade(unittest.TestCase):
    """Verify alembic upgrade head creates all tables on fresh MariaDB."""

    _BASELINE_TABLES = {
        'switch', 'guests', 'image', 'fcp',
        'template', 'template_sp_mapping', 'template_fcp_mapping',
    }

    def setUp(self):
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'mariadb')
        base.set_conf('database', 'connection', _DB_URL)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'smoke-test-node')
        base.set_conf('database', 'pool_size', 5)
        base.set_conf('database', 'pool_max_overflow', 10)
        base.set_conf('database', 'pool_timeout', 30)
        base.set_conf('database', 'pool_recycle', 3600)
        # Drop all tables from any previous run.
        self._drop_all()

    def tearDown(self):
        self._drop_all()
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'connection', None)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', None)

    def _drop_all(self):
        engine = _engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                for tbl in list(self._BASELINE_TABLES) + ['alembic_version']:
                    conn.execute(
                        text("DROP TABLE IF EXISTS `%s`" % tbl))
                conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        finally:
            engine.dispose()

    def _get_tables(self):
        from sqlalchemy import inspect as sa_inspect
        engine = _engine()
        try:
            return set(sa_inspect(engine).get_table_names())
        finally:
            engine.dispose()

    def test_upgrade_head_creates_all_baseline_tables(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        tables = self._get_tables()
        for expected in self._BASELINE_TABLES:
            self.assertIn(expected, tables,
                          "Table %r missing after upgrade head" % expected)
        self.assertIn('alembic_version', tables)

    def test_table_engine_is_innodb(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        engine = _engine()
        try:
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT ENGINE FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'fcp'"))
                row = result.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0].upper(), 'INNODB')
        finally:
            engine.dispose()

    def test_table_charset_is_utf8mb4(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        engine = _engine()
        try:
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT CCSA.CHARACTER_SET_NAME "
                    "FROM information_schema.TABLES T "
                    "JOIN information_schema.COLLATION_CHARACTER_SET_APPLICABILITY "
                    "     CCSA ON CCSA.COLLATION_NAME = T.TABLE_COLLATION "
                    "WHERE T.TABLE_SCHEMA = DATABASE() "
                    "AND T.TABLE_NAME = 'guests'"))
                row = result.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], 'utf8mb4')
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self):
        """Running ensure_schema_current() twice must not raise."""
        from zvmsdk.db import migration
        migration.ensure_schema_current()
        migration.ensure_schema_current()
        tables = self._get_tables()
        for expected in self._BASELINE_TABLES:
            self.assertIn(expected, tables)


if __name__ == '__main__':
    unittest.main()
