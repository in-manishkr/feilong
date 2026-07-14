#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Unit tests for Phase 9 hardening, monitoring, and credential management.

Covers:
  - 9.1  Pool metrics: get_pool_status() returns expected keys; checkout
         counter increments on connection use.
  - 9.2  Credential hardening: ZVMSDK_DB_PASSWORD env var is used when config
         password is empty; config password takes priority when set.
  - 9.3  Stale node health-check: _mark_stale_nodes_inactive() issues correct
         dialect-aware SQL; check_stale_nodes() swallows errors gracefully.
  - 9.6  Security audit: no medium/high-severity bandit findings in zvmsdk/db/.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from zvmsdk import config
from zvmsdk.tests.unit import base

CONF = config.CONF


def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''
    db_api._POOL_CHECKED_OUT = 0
    db_api._POOL_CHECKED_IN = 0
    db_api._POOL_INVALIDATED = 0


class TestGetPoolStatus(unittest.TestCase):
    """get_pool_status() returns a meaningful dict after the engine is created."""

    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'dir', self.db_dir)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'POOL-TEST-NODE')

    def tearDown(self):
        _reset_engine_globals()
        base.set_conf('database', 'compute_node_id', None)
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_get_pool_status_returns_empty_before_engine_init(self):
        import zvmsdk.db.api as db_api
        self.assertEqual(db_api.get_pool_status(), {})

    def test_get_pool_status_has_backend_key_after_engine_init(self):
        import zvmsdk.db.api as db_api
        db_api.get_engine()
        status = db_api.get_pool_status()
        self.assertIn('backend', status)
        self.assertEqual(status['backend'], 'sqlite')

    def test_get_pool_status_has_lifetime_counters(self):
        import zvmsdk.db.api as db_api
        db_api.get_engine()
        status = db_api.get_pool_status()
        self.assertIn('lifetime_checked_out', status)
        self.assertIn('lifetime_checked_in', status)
        self.assertIn('lifetime_invalidated', status)

    def test_checkout_counter_increments_on_connection_use(self):
        import zvmsdk.db.api as db_api
        db_api.get_engine()
        before = db_api._POOL_CHECKED_OUT
        with db_api.get_connection():
            pass
        self.assertGreater(db_api._POOL_CHECKED_OUT, before,
                           "checkout counter must increment on each connection use")

    def test_checkin_counter_increments_after_connection_release(self):
        import zvmsdk.db.api as db_api
        db_api.get_engine()
        before = db_api._POOL_CHECKED_IN
        with db_api.get_connection():
            pass
        self.assertGreater(db_api._POOL_CHECKED_IN, before)

    def test_queuepool_status_has_pool_size_key(self):
        """QueuePool (MariaDB) status includes pool_size, checked_out, overflow."""
        import zvmsdk.db.api as db_api
        from sqlalchemy.pool import QueuePool
        from unittest.mock import MagicMock
        mock_pool = MagicMock(spec=QueuePool)
        mock_pool.size.return_value = 5
        mock_pool.checkedout.return_value = 2
        mock_pool.overflow.return_value = 0
        mock_engine = MagicMock()
        mock_engine.pool = mock_pool
        db_api._ENGINE = mock_engine
        try:
            status = db_api.get_pool_status()
            self.assertIn('pool_size', status)
            self.assertEqual(status['pool_size'], 5)
            self.assertIn('checked_out', status)
            self.assertIn('overflow', status)
        finally:
            db_api._ENGINE = None


class TestCredentialHardening(unittest.TestCase):
    """_build_url() reads ZVMSDK_DB_PASSWORD env var as fallback."""

    def setUp(self):
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'mariadb')
        base.set_conf('database', 'host', '127.0.0.1')
        base.set_conf('database', 'port', 3306)
        base.set_conf('database', 'user', 'zvmsdk')
        base.set_conf('database', 'name', 'zvmsdk')
        base.set_conf('database', 'password', '')

    def tearDown(self):
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'password', '')

    def test_env_var_password_used_when_config_password_empty(self):
        import zvmsdk.db.api as db_api
        with mock.patch.dict(os.environ, {'ZVMSDK_DB_PASSWORD': 'env-secret'}):
            url = db_api._build_url()
        self.assertEqual(url.password, 'env-secret')

    def test_config_password_takes_priority_over_env_var(self):
        import zvmsdk.db.api as db_api
        base.set_conf('database', 'password', 'config-secret')
        with mock.patch.dict(os.environ, {'ZVMSDK_DB_PASSWORD': 'env-secret'}):
            url = db_api._build_url()
        self.assertEqual(url.password, 'config-secret')

    def test_empty_config_empty_env_gives_empty_password(self):
        import zvmsdk.db.api as db_api
        env = {k: v for k, v in os.environ.items() if k != 'ZVMSDK_DB_PASSWORD'}
        with mock.patch.dict(os.environ, env, clear=True):
            url = db_api._build_url()
        self.assertEqual(url.password or '', '')

    def test_password_not_in_url_str_representation(self):
        import zvmsdk.db.api as db_api
        base.set_conf('database', 'password', 'super-secret')
        url_str = str(db_api._build_url())
        self.assertNotIn('super-secret', url_str,
                         "Password must not appear in URL string representation")

    def test_log_calls_do_not_include_password(self):
        import zvmsdk.db.api as db_api
        logged = []

        class CapturingLog:
            def info(self, msg, *args):
                logged.append(msg % args if args else msg)
            def warning(self, msg, *args):
                logged.append(msg % args if args else msg)
            def debug(self, msg, *args):
                logged.append(msg % args if args else msg)
            def error(self, msg, *args):
                logged.append(msg % args if args else msg)

        base.set_conf('database', 'password', 'log-test-secret')
        original_log = db_api.LOG
        db_api.LOG = CapturingLog()
        try:
            db_api._build_url()
        finally:
            db_api.LOG = original_log

        for entry in logged:
            self.assertNotIn('log-test-secret', entry,
                             "Password must never appear in log output")


class TestStaleNodeCheck(unittest.TestCase):
    """_mark_stale_nodes_inactive() and check_stale_nodes() behave correctly."""

    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'dir', self.db_dir)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'STALE-TEST-NODE')
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    def tearDown(self):
        _reset_engine_globals()
        base.set_conf('database', 'compute_node_id', None)
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_mark_stale_uses_active_inactive_in_sql(self):
        """SQL issued by _mark_stale_nodes_inactive() references active and inactive."""
        import zvmsdk.db.api as db_api
        with mock.patch.object(db_api, 'get_connection') as mock_conn:
            mock_inner = mock.MagicMock()
            mock_conn.return_value.__enter__ = mock.Mock(return_value=mock_inner)
            mock_conn.return_value.__exit__ = mock.Mock(return_value=False)
            db_api._mark_stale_nodes_inactive(threshold_seconds=120)
            mock_inner.execute.assert_called_once()
            sql_text = str(mock_inner.execute.call_args[0][0])
        self.assertIn('inactive', sql_text)
        self.assertIn('active', sql_text)

    def test_check_stale_nodes_swallows_exceptions(self):
        import zvmsdk.db.api as db_api
        with mock.patch.object(db_api, 'get_engine',
                               side_effect=Exception("DB unavailable")):
            try:
                db_api.check_stale_nodes(threshold_seconds=300)
            except Exception:
                self.fail("check_stale_nodes() must not propagate exceptions")

    def test_check_stale_nodes_logs_warning_on_failure(self):
        import zvmsdk.db.api as db_api
        with mock.patch.object(db_api, 'get_engine',
                               side_effect=Exception("DB down")), \
             mock.patch.object(db_api, 'LOG') as mock_log:
            db_api.check_stale_nodes()
            mock_log.warning.assert_called_once()

    def test_mark_stale_nodes_inactive_runs_without_error_on_sqlite(self):
        import zvmsdk.db.api as db_api
        db_api._COMPUTE_NODE_ID = 'STALE-TEST-NODE'
        db_api.register_compute_node()
        try:
            db_api._mark_stale_nodes_inactive(threshold_seconds=1)
        except Exception as e:
            self.fail("_mark_stale_nodes_inactive() raised: %s" % e)

    def test_stale_node_becomes_inactive_after_threshold(self):
        import zvmsdk.db.api as db_api
        from sqlalchemy import text
        db_api._COMPUTE_NODE_ID = 'OLD-NODE'
        db_api.register_compute_node()
        engine = db_api.get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE compute_nodes SET last_seen = datetime('now', '-10 minutes') "
                     "WHERE id = 'OLD-NODE'"))
        db_api._mark_stale_nodes_inactive(threshold_seconds=1)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status FROM compute_nodes WHERE id='OLD-NODE'")
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'inactive',
                         "Node with old last_seen must be marked inactive")


class TestDeprecatedConstants(unittest.TestCase):
    """DATABASE_* constants are still importable and hold correct filenames."""

    def test_deprecated_constants_still_importable(self):
        from zvmsdk.constants import (DATABASE_NETWORK, DATABASE_GUEST,
                                       DATABASE_IMAGE, DATABASE_FCP,
                                       DATABASE_VOLUME)
        self.assertEqual(DATABASE_NETWORK, 'sdk_network.sqlite')
        self.assertEqual(DATABASE_GUEST, 'sdk_guest.sqlite')
        self.assertEqual(DATABASE_IMAGE, 'sdk_image.sqlite')
        self.assertEqual(DATABASE_FCP, 'sdk_fcp.sqlite')
        self.assertEqual(DATABASE_VOLUME, 'sdk_volume.sqlite')


class TestBanditSecurityAudit(unittest.TestCase):
    """bandit must report no medium or high severity issues in zvmsdk/db/."""

    def test_no_medium_or_high_severity_bandit_findings(self):
        try:
            import bandit  # noqa: F401
        except ImportError:
            self.skipTest("bandit not installed — skipping security audit test")

        import subprocess
        import json

        db_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'db'))

        result = subprocess.run(  # nosec B603,B607
            ['python3', '-m', 'bandit', '-r', db_dir,
             '-f', 'json', '--severity-level', 'medium'],
            capture_output=True, text=True)

        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail("bandit did not produce valid JSON: %s" % result.stdout[:500])

        metrics = report.get('metrics', {}).get('_totals', {})
        medium = metrics.get('SEVERITY.MEDIUM', 0)
        high = metrics.get('SEVERITY.HIGH', 0)

        self.assertEqual(
            medium + high, 0,
            "bandit found %d medium and %d high issues:\n%s"
            % (medium, high,
               '\n'.join(i['issue_text'] for i in report.get('results', []))))


if __name__ == '__main__':
    unittest.main()
