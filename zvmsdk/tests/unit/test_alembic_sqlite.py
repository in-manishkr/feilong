#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Integration tests for the alembic migration layer against SQLite.

These tests exercise the full alembic upgrade/downgrade path without any
mocking of the database layer — they run against a real (temporary) SQLite
file.  They live in the unit test tree for convenience but are tagged as
integration via the class name so they can be filtered separately.
"""

import os
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text

from zvmsdk import config
from zvmsdk.tests.unit import base


CONF = config.CONF

_BASELINE_TABLES = {
    'switch',
    'guests',
    'image',
    'fcp',
    'template',
    'template_sp_mapping',
    'template_fcp_mapping',
}


def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


class TestAlembicSQLiteIntegration(unittest.TestCase):
    """Alembic upgrade / downgrade round-trip on an ephemeral SQLite file."""

    def setUp(self):
        _reset_engine_globals()
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, 'zvmsdk.db')
        # Point CONF at the temp directory so migration.py builds the right URL.
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'dir', self._tmpdir)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'test-node')
        base.set_conf('database', 'alembic_config', None)

    def tearDown(self):
        _reset_engine_globals()
        # Clean up temp files.
        for f in os.listdir(self._tmpdir):
            os.remove(os.path.join(self._tmpdir, f))
        os.rmdir(self._tmpdir)
        base.set_conf('database', 'dir', '/tmp/')
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', None)

    def _get_tables(self):
        engine = create_engine('sqlite:///%s' % self._db_path)
        try:
            return set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    def test_upgrade_head_creates_baseline_tables(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        tables = self._get_tables()
        # All 7 baseline tables must exist after upgrade.
        for expected in _BASELINE_TABLES:
            self.assertIn(expected, tables,
                          "Table %r missing after upgrade head" % expected)
        # alembic bookkeeping table must exist.
        self.assertIn('alembic_version', tables)

    def test_downgrade_to_base_removes_all_tables(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        # Verify we're at HEAD.
        tables_after_upgrade = self._get_tables()
        for expected in _BASELINE_TABLES:
            self.assertIn(expected, tables_after_upgrade)

        # Downgrade to base (before 0001) — all schema tables must disappear.
        migration.downgrade('base')

        tables_after_downgrade = self._get_tables()
        for removed in _BASELINE_TABLES:
            self.assertNotIn(removed, tables_after_downgrade,
                             "Table %r still present after downgrade base"
                             % removed)

    def test_upgrade_is_idempotent(self):
        """Running ensure_schema_current() twice must not raise."""
        from zvmsdk.db import migration
        migration.ensure_schema_current()
        migration.ensure_schema_current()  # second call must be a no-op

        tables = self._get_tables()
        for expected in _BASELINE_TABLES:
            self.assertIn(expected, tables)

    def test_guests_table_has_expected_columns(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        engine = create_engine('sqlite:///%s' % self._db_path)
        try:
            cols = {c['name'] for c in inspect(engine).get_columns('guests')}
        finally:
            engine.dispose()

        self.assertIn('id', cols)
        self.assertIn('userid', cols)
        self.assertIn('metadata', cols)
        self.assertIn('net_set', cols)
        self.assertIn('comments', cols)

    def test_fcp_table_has_expected_columns(self):
        from zvmsdk.db import migration
        migration.ensure_schema_current()

        engine = create_engine('sqlite:///%s' % self._db_path)
        try:
            cols = {c['name'] for c in inspect(engine).get_columns('fcp')}
        finally:
            engine.dispose()

        for expected in ('fcp_id', 'assigner_id', 'connections', 'reserved',
                         'wwpn_npiv', 'wwpn_phy', 'chpid', 'pchid',
                         'state', 'owner', 'tmpl_id'):
            self.assertIn(expected, cols,
                          "fcp column %r missing" % expected)


if __name__ == '__main__':
    unittest.main()
