#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Unit tests: every write-path method injects compute_node_id.

Each test mocks db_api.get_compute_node_id() to return a known sentinel,
then calls the write-path method with a mocked database connection and verifies
that:
  1. The SQL text passed to conn.execute() contains ':node_id'.
  2. The parameters dict passed to conn.execute() contains the sentinel value.
"""

import unittest
from unittest import mock
from unittest.mock import MagicMock, patch, call

from sqlalchemy import text

from zvmsdk import database
from zvmsdk.tests.unit import base


_NODE_ID = 'TESTNODE@ZHOST1'


def _make_conn():
    """Return a mock connection whose execute() records all calls."""
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    return conn


class _PatchNodeId:
    """Context manager / base that patches get_compute_node_id()."""

    def setUp(self):
        super().setUp()
        self._patcher = patch(
            'zvmsdk.database.db_api.get_compute_node_id',
            return_value=_NODE_ID,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _assert_node_id_injected(self, conn_mock):
        """Assert at least one execute() call included :node_id = _NODE_ID."""
        found = False
        for c in conn_mock.execute.call_args_list:
            args, kwargs = c
            if not args:
                continue
            sql_obj = args[0]
            sql_str = str(sql_obj) if not isinstance(sql_obj, str) else sql_obj
            if ':node_id' not in sql_str:
                continue
            params = args[1] if len(args) > 1 else (kwargs or {})
            if isinstance(params, list):
                # bulk execute — check the first row dict
                params = params[0] if params else {}
            if params.get('node_id') == _NODE_ID:
                found = True
                break
        self.assertTrue(
            found,
            "No execute() call contained ':node_id' bound to %r.\n"
            "Calls were: %s" % (_NODE_ID, conn_mock.execute.call_args_list),
        )


# ---------------------------------------------------------------------------
# NetworkDbOperator
# ---------------------------------------------------------------------------

class TestSwitchAddRecord(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.NetworkDbOperator()

    @patch('zvmsdk.database.get_network_conn')
    def test_switch_add_record_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.switch_add_record('USER1', '1000', port='p1')

        self._assert_node_id_injected(conn)

    @patch('zvmsdk.database.get_network_conn')
    def test_switch_add_record_migrated_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.switch_add_record_migrated('USER1', '1000', 'VSWITCH1')

        self._assert_node_id_injected(conn)


# ---------------------------------------------------------------------------
# GuestDbOperator
# ---------------------------------------------------------------------------

class TestGuestAddRecord(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.GuestDbOperator()

    @patch('zvmsdk.database.get_guest_conn')
    def test_add_guest_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.add_guest('TESTUSER', meta='k=v')

        self._assert_node_id_injected(conn)

    @patch('zvmsdk.database.get_guest_conn')
    def test_add_guest_registered_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.add_guest_registered('TESTUSER', 'meta=1', net_set=1)

        self._assert_node_id_injected(conn)


# ---------------------------------------------------------------------------
# ImageDbOperator
# ---------------------------------------------------------------------------

class TestImageAddRecord(base.SDKTestCase):
    """image_add_record always uses compute_node_id='GLOBAL'."""

    def setUp(self):
        super().setUp()
        self.op = database.ImageDbOperator()

    def _assert_global_injected(self, conn_mock):
        for c in conn_mock.execute.call_args_list:
            args, _ = c
            if not args:
                continue
            sql_obj = args[0]
            sql_str = str(sql_obj) if not isinstance(sql_obj, str) else sql_obj
            if 'compute_node_id' not in sql_str and ':node_id' not in sql_str:
                continue
            params = args[1] if len(args) > 1 else {}
            if params.get('node_id') == 'GLOBAL':
                return
        self.fail(
            "No execute() call used node_id='GLOBAL'.\n"
            "Calls: %s" % conn_mock.execute.call_args_list
        )

    @patch('zvmsdk.database.get_image_conn')
    def test_image_add_record_uses_global_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.image_add_record(
            'img1', 'rhel8', 'abc123', '100:CYL', '102400', 'netboot')

        self._assert_global_injected(conn)

    @patch('zvmsdk.database.get_image_conn')
    def test_image_add_record_with_comments_uses_global_node_id(self,
                                                                  mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        self.op.image_add_record(
            'img1', 'rhel8', 'abc123', '100:CYL', '102400', 'netboot',
            comments='some comment')

        self._assert_global_injected(conn)


# ---------------------------------------------------------------------------
# FCPDbOperator — fcp table INSERT
# ---------------------------------------------------------------------------

class TestFcpBulkInsert(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.FCPDbOperator()

    @patch('zvmsdk.database.get_fcp_conn')
    def test_bulk_insert_zvm_fcp_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        fcp_info = [('1a00', 'aabbcc', 'ddeeff', '27', '02e4', 'active', '')]
        self.op.bulk_insert_zvm_fcp_info_into_fcp_table(fcp_info)

        self._assert_node_id_injected(conn)


# ---------------------------------------------------------------------------
# FCPDbOperator — template_fcp_mapping INSERT
# ---------------------------------------------------------------------------

class TestFcpTemplateFcpMappingInsert(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.FCPDbOperator()

    @patch('zvmsdk.database.get_fcp_conn')
    def test_bulk_insert_fcp_device_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        records = [('tmpl_001', '1a00', 0), ('tmpl_001', '1b00', 1)]
        database.FCPDbOperator.bulk_insert_fcp_device_into_fcp_template(records)

        self._assert_node_id_injected(conn)


# ---------------------------------------------------------------------------
# FCPDbOperator — template_sp_mapping INSERT
# ---------------------------------------------------------------------------

class TestFcpTemplateSPMappingInsert(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.FCPDbOperator()

    @patch('zvmsdk.database.get_fcp_conn')
    def test_bulk_set_sp_default_injects_node_id(self, mock_conn_ctx):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        database.FCPDbOperator.bulk_set_sp_default_by_fcp_template(
            'tmpl_001', ['sp1', 'sp2'])

        self._assert_node_id_injected(conn)


# ---------------------------------------------------------------------------
# FCPDbOperator — create_fcp_template (template + mappings)
# ---------------------------------------------------------------------------

class TestCreateFcpTemplate(_PatchNodeId, base.SDKTestCase):

    def setUp(self):
        super().setUp()
        self.op = database.FCPDbOperator()

    @patch('zvmsdk.database.FCPDbOperator.fcp_template_exist_in_db',
           return_value=False)
    @patch('zvmsdk.database.FCPDbOperator.sp_name_exist_in_db',
           return_value=False)
    @patch('zvmsdk.database.get_fcp_conn')
    def test_create_fcp_template_injects_node_id(self,
                                                  mock_conn_ctx,
                                                  mock_sp_exist,
                                                  mock_tmpl_exist):
        conn = _make_conn()
        mock_conn_ctx.return_value.__enter__ = lambda s: conn
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

        fcp_by_path = {0: {'1a00'}, 1: {'1b00'}}
        self.op.create_fcp_template(
            fcp_template_id='tmpl_001',
            name='Test Template',
            description='desc',
            fcp_devices_by_path=fcp_by_path,
            host_default=False,
            default_sp_list=['sp1'],
        )

        self._assert_node_id_injected(conn)


if __name__ == '__main__':
    unittest.main()
