#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Unit tests for Phase 6 — remote mode node registration and scoped queries."""

import unittest
from unittest import mock

from zvmsdk import database
from zvmsdk.db import api as db_api


class TestNodeFilter(unittest.TestCase):
    """Tests for database._node_filter() helper."""

    def test_node_filter_returns_empty_in_local_mode(self):
        with mock.patch('zvmsdk.database.CONF') as mock_conf:
            mock_conf.database.mode = 'local'
            sql, params = database._node_filter()
        self.assertEqual(sql, "")
        self.assertEqual(params, {})

    def test_node_filter_returns_clause_in_remote_mode(self):
        with mock.patch('zvmsdk.database.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='test-node'):
            mock_conf.database.mode = 'remote'
            sql, params = database._node_filter()
        self.assertIn("compute_node_id", sql)
        self.assertIn(":node_id", sql)
        self.assertIn("AND", sql)
        self.assertEqual(params, {'node_id': 'test-node'})

    def test_node_filter_with_prefix_in_remote_mode(self):
        with mock.patch('zvmsdk.database.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='my-node'):
            mock_conf.database.mode = 'remote'
            sql, params = database._node_filter(prefix='fcp')
        self.assertIn("fcp.compute_node_id", sql)
        self.assertEqual(params['node_id'], 'my-node')

    def test_node_filter_prefix_ignored_in_local_mode(self):
        with mock.patch('zvmsdk.database.CONF') as mock_conf:
            mock_conf.database.mode = 'local'
            sql, params = database._node_filter(prefix='fcp')
        self.assertEqual(sql, "")
        self.assertEqual(params, {})


class TestVerifyRemoteConnectivity(unittest.TestCase):
    """Tests for db_api.verify_remote_connectivity()."""

    def test_verify_connectivity_noop_in_local_mode(self):
        with mock.patch('zvmsdk.db.api.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_engine') as mock_engine:
            mock_conf.database.mode = 'local'
            db_api.verify_remote_connectivity()
            mock_engine.assert_not_called()

    def test_verify_connectivity_succeeds_in_remote_mode(self):
        with mock.patch('zvmsdk.db.api.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_engine') as mock_engine:
            mock_conf.database.mode = 'remote'
            mock_conn = mock.MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = \
                mock.Mock(return_value=mock_conn)
            mock_engine.return_value.connect.return_value.__exit__ = \
                mock.Mock(return_value=False)
            db_api.verify_remote_connectivity()
            mock_conn.execute.assert_called_once()

    def test_verify_connectivity_raises_sdk_internal_error_on_failure(self):
        from zvmsdk import exception
        with mock.patch('zvmsdk.db.api.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_engine') as mock_engine:
            mock_conf.database.mode = 'remote'
            mock_engine.return_value.connect.side_effect = Exception("refused")
            with self.assertRaises(exception.SDKInternalError):
                db_api.verify_remote_connectivity()


class TestRegisterDeregisterComputeNode(unittest.TestCase):
    """Tests for register_compute_node() and deregister_compute_node()."""

    def _make_engine_mock(self, dialect_name='sqlite'):
        engine = mock.MagicMock()
        engine.dialect.name = dialect_name
        return engine

    def test_register_compute_node_sqlite(self):
        engine = self._make_engine_mock('sqlite')
        mock_conn = mock.MagicMock()

        with mock.patch('zvmsdk.db.api.get_engine', return_value=engine), \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='MYNODE@ZVM1'), \
             mock.patch('zvmsdk.db.api.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_connection') as mock_get_conn, \
             mock.patch('socket.gethostname', return_value='myhost'):
            mock_conf.network.my_ip = '192.168.1.1'
            mock_get_conn.return_value.__enter__ = mock.Mock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = mock.Mock(return_value=False)
            db_api.register_compute_node()

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        sql_str = str(call_args[0][0])
        self.assertIn("INSERT OR REPLACE", sql_str)
        params = call_args[0][1]
        self.assertEqual(params['id'], 'MYNODE@ZVM1')
        self.assertEqual(params['hostname'], 'myhost')
        self.assertEqual(params['ip'], '192.168.1.1')

    def test_register_compute_node_mariadb(self):
        engine = self._make_engine_mock('mariadb')
        mock_conn = mock.MagicMock()

        with mock.patch('zvmsdk.db.api.get_engine', return_value=engine), \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='NODE@ZVM'), \
             mock.patch('zvmsdk.db.api.CONF') as mock_conf, \
             mock.patch('zvmsdk.db.api.get_connection') as mock_get_conn, \
             mock.patch('socket.gethostname', return_value='dbhost'):
            mock_conf.network.my_ip = '10.0.0.1'
            mock_get_conn.return_value.__enter__ = mock.Mock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = mock.Mock(return_value=False)
            db_api.register_compute_node()

        mock_conn.execute.assert_called_once()
        sql_str = str(mock_conn.execute.call_args[0][0])
        self.assertIn("ON DUPLICATE KEY UPDATE", sql_str)

    def test_deregister_compute_node_sets_inactive_sqlite(self):
        engine = self._make_engine_mock('sqlite')
        mock_conn = mock.MagicMock()

        with mock.patch('zvmsdk.db.api.get_engine', return_value=engine), \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='MYNODE@ZVM1'), \
             mock.patch('zvmsdk.db.api.get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__ = mock.Mock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = mock.Mock(return_value=False)
            db_api.deregister_compute_node()

        mock_conn.execute.assert_called_once()
        sql_str = str(mock_conn.execute.call_args[0][0])
        self.assertIn("inactive", sql_str)

    def test_deregister_skips_when_no_node_id(self):
        with mock.patch('zvmsdk.db.api.get_compute_node_id', return_value=''), \
             mock.patch('zvmsdk.db.api.get_engine') as mock_engine:
            db_api.deregister_compute_node()
            mock_engine.assert_not_called()

    def test_deregister_logs_warning_on_failure(self):
        engine = self._make_engine_mock('sqlite')
        with mock.patch('zvmsdk.db.api.get_engine', return_value=engine), \
             mock.patch('zvmsdk.db.api.get_compute_node_id',
                        return_value='MYNODE'), \
             mock.patch('zvmsdk.db.api.get_connection',
                        side_effect=Exception("db down")), \
             mock.patch('zvmsdk.db.api.LOG') as mock_log:
            db_api.deregister_compute_node()
            mock_log.warning.assert_called_once()


if __name__ == '__main__':
    unittest.main()
