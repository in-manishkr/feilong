#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

import tempfile
import threading
import unittest

import mock

from zvmsdk import config
from zvmsdk import exception
from zvmsdk.tests.unit import base


CONF = config.CONF


def _reset_engine_globals():
    """Reset module-level engine globals between tests."""
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


class TestResolveComputeNodeId(base.SDKTestCase):

    def setUp(self):
        super().setUp()
        _reset_engine_globals()
        import zvmsdk.db.api as db_api
        self.db_api = db_api

    # --- priority 1: explicit config ---

    def test_resolve_node_id_from_config(self):
        base.set_conf('database', 'compute_node_id', 'my-explicit-node')
        result = self.db_api._resolve_compute_node_id()
        self.assertEqual('my-explicit-node', result)

    def tearDown(self):
        base.set_conf('database', 'compute_node_id', None)
        super().tearDown()

    # --- priority 2: vmcp ---

    @mock.patch('subprocess.check_output',
                return_value=b'IAAS01EF AT BOEM5401\n')
    def test_resolve_node_id_from_vmcp(self, mock_sub):
        base.set_conf('database', 'compute_node_id', None)
        result = self.db_api._resolve_compute_node_id()
        self.assertEqual('IAAS01EF@BOEM5401', result)
        mock_sub.assert_called_once()

    @mock.patch('subprocess.check_output',
                return_value=b'IAAS01EF AT BOEM5401\n')
    def test_vmcp_called_only_once_not_twice(self, mock_sub):
        """get_smt_userid() + get_zvm_name() historically called vmcp twice.
        _resolve_compute_node_id() must call it exactly once."""
        base.set_conf('database', 'compute_node_id', None)
        self.db_api._resolve_compute_node_id()
        self.assertEqual(1, mock_sub.call_count)

    # --- priority 3: my_ip fallback ---

    @mock.patch('subprocess.check_output', side_effect=OSError("no vmcp"))
    def test_resolve_node_id_fallback_to_my_ip(self, _mock_sub):
        base.set_conf('database', 'compute_node_id', None)
        base.set_conf('network', 'my_ip', '10.0.0.42')
        result = self.db_api._resolve_compute_node_id()
        self.assertEqual('10.0.0.42', result)


class TestGetEngine(base.SDKTestCase):

    def setUp(self):
        super().setUp()
        _reset_engine_globals()
        import zvmsdk.db.api as db_api
        self.db_api = db_api
        # Default to sqlite so tests don't need a real MariaDB.
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'test-node')

    def tearDown(self):
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', None)
        super().tearDown()

    def test_get_engine_sqlite_returns_engine(self):
        engine = self.db_api.get_engine()
        self.assertIsNotNone(engine)
        self.assertEqual('sqlite', engine.dialect.name)

    def test_get_engine_is_singleton(self):
        engine1 = self.db_api.get_engine()
        engine2 = self.db_api.get_engine()
        self.assertIs(engine1, engine2)

    def test_get_engine_sets_compute_node_id(self):
        self.db_api.get_engine()
        self.assertEqual('test-node', self.db_api.get_compute_node_id())

    def test_get_engine_thread_safety(self):
        """20 concurrent threads must all receive the same engine object and
        _resolve_compute_node_id() must run exactly once."""
        call_count = []
        original = self.db_api._resolve_compute_node_id

        def counting_resolve():
            call_count.append(1)
            return 'thread-test-node'

        results = []

        def worker():
            results.append(self.db_api.get_engine())

        with mock.patch.object(self.db_api, '_resolve_compute_node_id',
                               side_effect=counting_resolve):
            threads = [threading.Thread(target=worker) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All threads must return the same engine instance.
        self.assertEqual(1, len(set(id(e) for e in results)))
        # _resolve_compute_node_id must have been called exactly once.
        self.assertEqual(1, len(call_count))

    def test_mode_remote_backend_sqlite_raises(self):
        base.set_conf('database', 'mode', 'remote')
        base.set_conf('database', 'backend', 'sqlite')
        self.assertRaises(exception.SDKInternalError, self.db_api.get_engine)


class TestBuildSslArgs(base.SDKTestCase):

    def setUp(self):
        super().setUp()
        import zvmsdk.db.api as db_api
        self.db_api = db_api
        base.set_conf('database', 'ssl_ca', None)
        base.set_conf('database', 'ssl_cert', None)
        base.set_conf('database', 'ssl_key', None)

    def tearDown(self):
        base.set_conf('database', 'ssl_ca', None)
        base.set_conf('database', 'ssl_cert', None)
        base.set_conf('database', 'ssl_key', None)
        super().tearDown()

    def test_build_ssl_args_empty_when_no_ssl_ca(self):
        self.assertEqual({}, self.db_api._build_ssl_args())

    def test_build_ssl_args_only_ca(self):
        base.set_conf('database', 'ssl_ca', '/etc/ssl/ca.pem')
        result = self.db_api._build_ssl_args()
        self.assertIn('ssl', result)
        self.assertEqual({'ca': '/etc/ssl/ca.pem'}, result['ssl'])
        self.assertNotIn('cert', result['ssl'])
        self.assertNotIn('key', result['ssl'])

    def test_build_ssl_args_full(self):
        base.set_conf('database', 'ssl_ca', '/etc/ssl/ca.pem')
        base.set_conf('database', 'ssl_cert', '/etc/ssl/cert.pem')
        base.set_conf('database', 'ssl_key', '/etc/ssl/key.pem')
        result = self.db_api._build_ssl_args()
        self.assertEqual(
            {'ca': '/etc/ssl/ca.pem',
             'cert': '/etc/ssl/cert.pem',
             'key': '/etc/ssl/key.pem'},
            result['ssl'])

    def test_build_ssl_args_no_none_values(self):
        """PyMySQL breaks if None appears in the ssl dict."""
        base.set_conf('database', 'ssl_ca', '/etc/ssl/ca.pem')
        result = self.db_api._build_ssl_args()
        for v in result.get('ssl', {}).values():
            self.assertIsNotNone(v)


class TestGetConnection(base.SDKTestCase):
    """Verify get_connection() transaction semantics against in-memory SQLite."""

    def setUp(self):
        super().setUp()
        _reset_engine_globals()
        import zvmsdk.db.api as db_api
        self.db_api = db_api
        base.set_conf('database', 'backend', 'sqlite')
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'conn-test-node')
        self._tmpdir = tempfile.mkdtemp()
        base.set_conf('database', 'dir', self._tmpdir)

    def tearDown(self):
        _reset_engine_globals()
        base.set_conf('database', 'dir', '/tmp/')
        base.set_conf('database', 'compute_node_id', None)
        super().tearDown()

    def _make_table(self, conn):
        from sqlalchemy import text
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS _test (id INTEGER PRIMARY KEY, val TEXT)"))

    def test_get_connection_commits_on_success(self):
        from sqlalchemy import text
        # Create table in its own transaction first.
        with self.db_api.get_connection() as conn:
            self._make_table(conn)

        with self.db_api.get_connection() as conn:
            conn.execute(text("INSERT INTO _test (id, val) VALUES (1, 'hello')"))

        with self.db_api.get_connection() as conn:
            row = conn.execute(
                text("SELECT val FROM _test WHERE id=1")).fetchone()
        self.assertEqual('hello', row[0])

    def test_get_connection_rolls_back_on_exception(self):
        from sqlalchemy import text
        with self.db_api.get_connection() as conn:
            self._make_table(conn)

        try:
            with self.db_api.get_connection() as conn:
                conn.execute(
                    text("INSERT INTO _test (id, val) VALUES (2, 'rolled_back')"))
                raise RuntimeError("deliberate error")
        except RuntimeError:
            pass

        with self.db_api.get_connection() as conn:
            row = conn.execute(
                text("SELECT val FROM _test WHERE id=2")).fetchone()
        self.assertIsNone(row)


class TestVerifyRemoteConnectivity(base.SDKTestCase):

    def setUp(self):
        super().setUp()
        import zvmsdk.db.api as db_api
        self.db_api = db_api

    def test_noop_in_local_mode(self):
        base.set_conf('database', 'mode', 'local')
        # Should return without touching the engine at all.
        with mock.patch.object(self.db_api, 'get_engine') as mock_eng:
            self.db_api.verify_remote_connectivity()
            mock_eng.assert_not_called()

    def test_raises_sdk_internal_error_when_unreachable(self):
        base.set_conf('database', 'mode', 'remote')
        mock_engine = mock.MagicMock()
        mock_engine.connect.side_effect = Exception("connection refused")
        with mock.patch.object(self.db_api, 'get_engine',
                               return_value=mock_engine):
            self.assertRaises(exception.SDKInternalError,
                              self.db_api.verify_remote_connectivity)

    def tearDown(self):
        base.set_conf('database', 'mode', 'local')
        super().tearDown()


if __name__ == '__main__':
    unittest.main()
