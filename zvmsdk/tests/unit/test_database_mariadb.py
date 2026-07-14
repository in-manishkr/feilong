#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""MariaDB/MySQL operator integration tests for Phase 4.

Run all four DbOperator classes against a live MariaDB to verify that
every SQL query works in both dialects.  The schema is created fresh via
alembic before each test class and torn down afterward.

Set ZVMSDK_TEST_DB_URL to a PyMySQL URL to enable:
  export ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk_test"

All tests are skipped automatically when ZVMSDK_TEST_DB_URL is unset.
"""

import os
import uuid
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from zvmsdk import config
from zvmsdk.tests.unit import base


CONF = config.CONF

_DB_URL = os.environ.get('ZVMSDK_TEST_DB_URL', '')

_SKIP = unittest.skipUnless(
    _DB_URL,
    'ZVMSDK_TEST_DB_URL not set — skipping MariaDB operator tests',
)

_BASELINE_TABLES = {
    'switch', 'guests', 'image', 'fcp',
    'template', 'template_sp_mapping', 'template_fcp_mapping',
}


def _reset_engine_globals():
    import zvmsdk.db.api as db_api
    db_api._ENGINE = None
    db_api._COMPUTE_NODE_ID = ''


def _plain_engine():
    return create_engine(_DB_URL, poolclass=NullPool)


def _drop_all_tables():
    engine = _plain_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for tbl in list(_BASELINE_TABLES) + ['alembic_version']:
                conn.execute(
                    text("DROP TABLE IF EXISTS `%s`" % tbl))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        engine.dispose()


def _setup_mariadb_conf():
    base.set_conf('database', 'backend', 'mariadb')
    base.set_conf('database', 'connection', _DB_URL)
    base.set_conf('database', 'mode', 'local')
    base.set_conf('database', 'compute_node_id', 'test-node-mariadb')
    base.set_conf('database', 'pool_size', 5)
    base.set_conf('database', 'pool_max_overflow', 10)
    base.set_conf('database', 'pool_timeout', 30)
    base.set_conf('database', 'pool_recycle', 3600)


def _teardown_mariadb_conf():
    base.set_conf('database', 'backend', 'sqlite')
    base.set_conf('database', 'connection', None)
    base.set_conf('database', 'mode', 'local')
    base.set_conf('database', 'compute_node_id', None)


@_SKIP
class TestGuestDbOperatorMariaDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        _setup_mariadb_conf()
        _drop_all_tables()
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    @classmethod
    def tearDownClass(cls):
        _drop_all_tables()
        _reset_engine_globals()
        _teardown_mariadb_conf()

    def setUp(self):
        from zvmsdk.database import GuestDbOperator
        self.op = GuestDbOperator()

    def _unique_userid(self):
        return ('T' + uuid.uuid4().hex[:7]).upper()

    def test_add_and_get_guest(self):
        uid = self._unique_userid()
        self.op.add_guest(uid)
        result = self.op.get_guest_list()
        userids = [r[1] for r in result]
        self.assertIn(uid, userids)

    def test_add_guest_duplicate_raises(self):
        uid = self._unique_userid()
        self.op.add_guest(uid)
        from zvmsdk import exception
        self.assertRaises(exception.SDKGuestOperationError,
                          self.op.add_guest, uid)

    def test_update_and_get_metadata(self):
        uid = self._unique_userid()
        self.op.add_guest(uid)
        self.op.update_guest_by_userid(uid, meta='key=val')
        row = self.op.get_guest_metadata(uid)
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'key=val')

    def test_delete_guest(self):
        uid = self._unique_userid()
        self.op.add_guest(uid)
        self.op.delete_guest_by_userid(uid)
        result = self.op.get_guest_list()
        userids = [r[1] for r in result]
        self.assertNotIn(uid, userids)


@_SKIP
class TestNetworkDbOperatorMariaDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        _setup_mariadb_conf()
        _drop_all_tables()
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    @classmethod
    def tearDownClass(cls):
        _drop_all_tables()
        _reset_engine_globals()
        _teardown_mariadb_conf()

    def setUp(self):
        from zvmsdk.database import NetworkDbOperator
        self.op = NetworkDbOperator()

    def _unique_userid(self):
        return ('N' + uuid.uuid4().hex[:7]).upper()

    def test_add_and_select_switch_record(self):
        uid = self._unique_userid()
        self.op.switch_add_record(uid, 'eth0')
        result = self.op.switch_select_record_for_userid(uid)
        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0][0], uid)

    def test_update_switch_record(self):
        uid = self._unique_userid()
        self.op.switch_add_record(uid, 'eth0')
        self.op.switch_update_record_with_switch(uid, 'eth0', 'VSLAN1')
        result = self.op.switch_select_record_for_userid(uid)
        self.assertEqual(result[0][2], 'VSLAN1')

    def test_delete_switch_record_for_userid(self):
        uid = self._unique_userid()
        self.op.switch_add_record(uid, 'eth0')
        self.op.switch_delete_record_for_userid(uid)
        result = self.op.switch_select_record_for_userid(uid)
        self.assertEqual(result, [])


@_SKIP
class TestImageDbOperatorMariaDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        _setup_mariadb_conf()
        _drop_all_tables()
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    @classmethod
    def tearDownClass(cls):
        _drop_all_tables()
        _reset_engine_globals()
        _teardown_mariadb_conf()

    def setUp(self):
        from zvmsdk.database import ImageDbOperator
        self.op = ImageDbOperator()

    def _unique_name(self):
        return 'img-' + uuid.uuid4().hex[:8]

    def test_add_and_query_image(self):
        name = self._unique_name()
        self.op.image_add_record(name, 'rhel8', 'abc123',
                                 '10g', '9000000000', 'netboot')
        result = self.op.image_query_record(name)
        self.assertIsNotNone(result)
        self.assertEqual(result[0][0], name)

    def test_delete_image(self):
        name = self._unique_name()
        self.op.image_add_record(name, 'rhel8', 'abc123',
                                 '10g', '9000000000', 'netboot')
        self.op.image_delete_record(name)
        result = self.op.image_query_record(name)
        self.assertIsNone(result)

    def test_update_image_comments(self):
        name = self._unique_name()
        self.op.image_add_record(name, 'rhel8', 'abc123',
                                 '10g', '9000000000', 'netboot')
        self.op.image_update_record(name, comments='test comment')
        result = self.op.image_query_record(name)
        self.assertEqual(result[0][6], 'test comment')


@_SKIP
class TestFCPDbOperatorMariaDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        _setup_mariadb_conf()
        _drop_all_tables()
        from zvmsdk.db import migration
        migration.ensure_schema_current()

    @classmethod
    def tearDownClass(cls):
        _drop_all_tables()
        _reset_engine_globals()
        _teardown_mariadb_conf()

    def setUp(self):
        from zvmsdk.database import FCPDbOperator
        self.op = FCPDbOperator()

    def _fcp_row(self, fcp_id):
        """Return a minimal fcp info tuple for bulk_insert."""
        return (fcp_id, '', 0, 0, '', '', '', '', 'free', '', '')

    def test_bulk_insert_and_get_usage(self):
        fcp_list = [self._fcp_row('1a01'), self._fcp_row('1a02')]
        self.op.bulk_insert_zfcp_info_to_db(fcp_list)
        usage = self.op.get_usage_of_fcp('1a01')
        self.assertIsNotNone(usage)

    def test_reserve_and_unreserve_fcp(self):
        fcp_list = [self._fcp_row('1b01')]
        self.op.bulk_insert_zfcp_info_to_db(fcp_list)
        self.op.reserve_fcps(['1b01'])
        usage = self.op.get_usage_of_fcp('1b01')
        self.assertEqual(usage[1], 1)  # reserved=1

        self.op.unreserve_fcps(['1b01'])
        usage = self.op.get_usage_of_fcp('1b01')
        self.assertEqual(usage[1], 0)  # reserved=0

    def test_bulk_delete_fcp(self):
        fcp_list = [self._fcp_row('1c01'), self._fcp_row('1c02')]
        self.op.bulk_insert_zfcp_info_to_db(fcp_list)
        self.op.bulk_delete_zfcp_from_db(['1c01', '1c02'])
        usage = self.op.get_usage_of_fcp('1c01')
        self.assertIsNone(usage)


if __name__ == '__main__':
    unittest.main()
