#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Remote-mode integration tests — Phase 8 Task 8.2.

Validates that two feilong nodes sharing the same MariaDB database cannot see
each other's guests, FCPs, or switch records when mode=remote.  Also covers
upsert idempotency, deregistration, FK cascade on node removal, and optional
SSL connectivity.

Set ZVMSDK_TEST_DB_URL to a PyMySQL URL to enable:
  export ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk_test"

All tests are skipped automatically when ZVMSDK_TEST_DB_URL is unset.

Set ZVMSDK_TEST_DB_SSL_URL for SSL-specific connectivity tests:
  export ZVMSDK_TEST_DB_SSL_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk_test"
  export ZVMSDK_TEST_DB_SSL_CA="/etc/ssl/certs/ca.pem"
"""

import os
import time
import unittest
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from zvmsdk import config
from zvmsdk.tests.unit import base

CONF = config.CONF

_DB_URL = os.environ.get('ZVMSDK_TEST_DB_URL', '')
_SSL_URL = os.environ.get('ZVMSDK_TEST_DB_SSL_URL', '')
_SSL_CA = os.environ.get('ZVMSDK_TEST_DB_SSL_CA', '')

_SKIP = unittest.skipUnless(
    _DB_URL,
    'ZVMSDK_TEST_DB_URL not set — skipping remote mode MariaDB tests',
)
_SKIP_SSL = unittest.skipUnless(
    _SSL_URL and _SSL_CA,
    'ZVMSDK_TEST_DB_SSL_URL/ZVMSDK_TEST_DB_SSL_CA not set — skipping SSL tests',
)

NODE_A = 'NODEA@ZVM1'
NODE_B = 'NODEB@ZVM1'

_BASELINE_TABLES = {
    'switch', 'guests', 'image', 'fcp',
    'template', 'template_sp_mapping', 'template_fcp_mapping',
}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

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
            for tbl in list(_BASELINE_TABLES) + ['compute_nodes', 'alembic_version']:
                conn.execute(text("DROP TABLE IF EXISTS `%s`" % tbl))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        engine.dispose()


def _setup_remote_conf(node_id=NODE_A):
    base.set_conf('database', 'backend', 'mariadb')
    base.set_conf('database', 'connection', _DB_URL)
    base.set_conf('database', 'mode', 'remote')
    base.set_conf('database', 'compute_node_id', node_id)
    base.set_conf('database', 'pool_size', 5)
    base.set_conf('database', 'pool_max_overflow', 10)
    base.set_conf('database', 'pool_timeout', 30)
    base.set_conf('database', 'pool_recycle', 3600)


def _teardown_remote_conf():
    base.set_conf('database', 'backend', 'sqlite')
    base.set_conf('database', 'connection', None)
    base.set_conf('database', 'mode', 'local')
    base.set_conf('database', 'compute_node_id', None)
    base.set_conf('database', 'ssl_ca', None)
    base.set_conf('database', 'ssl_cert', None)
    base.set_conf('database', 'ssl_key', None)


def _set_node(node_id):
    """Swap the active compute_node_id to simulate a different feilong node."""
    import zvmsdk.db.api as db_api
    db_api._COMPUTE_NODE_ID = node_id


def _register_node(node_id):
    """Register a node in compute_nodes using the real API."""
    _set_node(node_id)
    import zvmsdk.db.api as db_api
    db_api.register_compute_node()


def _uid():
    return ('T' + uuid.uuid4().hex[:7]).upper()


# ---------------------------------------------------------------------------
# Task 8.2 — Remote-mode data isolation
# ---------------------------------------------------------------------------

@_SKIP
class TestRemoteModeIsolationMariaDB(unittest.TestCase):
    """Two virtual nodes sharing MariaDB; verify per-node data isolation."""

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        _setup_remote_conf(node_id=NODE_A)
        _drop_all_tables()
        from zvmsdk.db import migration
        migration.ensure_schema_current()
        # Register both test nodes so FK constraints are satisfied
        _register_node(NODE_A)
        _register_node(NODE_B)

    @classmethod
    def tearDownClass(cls):
        _drop_all_tables()
        _reset_engine_globals()
        _teardown_remote_conf()

    # ------------------------------------------------------------------
    # Guest isolation
    # ------------------------------------------------------------------

    def test_guest_isolation_node_b_cannot_see_node_a_guest(self):
        """Guest created under node A must not appear in node B's query."""
        from zvmsdk.database import GuestDbOperator
        uid = _uid()

        _set_node(NODE_A)
        GuestDbOperator().add_guest(uid)

        _set_node(NODE_B)
        userids = [r[1] for r in GuestDbOperator().get_guest_list()]
        self.assertNotIn(uid, userids,
                         "Node B must not see Node A's guest in remote mode")

        # Cleanup
        _set_node(NODE_A)
        GuestDbOperator().delete_guest_by_userid(uid)

    def test_guest_visible_from_same_node(self):
        """Guest created under node A must appear in node A's own query."""
        from zvmsdk.database import GuestDbOperator
        uid = _uid()

        _set_node(NODE_A)
        op = GuestDbOperator()
        op.add_guest(uid)
        userids = [r[1] for r in op.get_guest_list()]
        self.assertIn(uid, userids)

        op.delete_guest_by_userid(uid)

    # ------------------------------------------------------------------
    # Switch / network isolation
    # ------------------------------------------------------------------

    def test_switch_record_isolation(self):
        """Switch record created by node A is invisible to node B."""
        from zvmsdk.database import NetworkDbOperator
        uid = _uid()

        _set_node(NODE_A)
        NetworkDbOperator().switch_add_record(uid, 'eth0')

        _set_node(NODE_B)
        result = NetworkDbOperator().switch_select_record_for_userid(uid)
        self.assertEqual(len(result), 0,
                         "Node B must not see Node A's switch record")

        # Cleanup
        _set_node(NODE_A)
        NetworkDbOperator().switch_delete_record_for_userid(uid)

    # ------------------------------------------------------------------
    # Image global sharing
    # ------------------------------------------------------------------

    def test_image_global_shared_across_nodes(self):
        """Image with compute_node_id='GLOBAL' is visible from both nodes."""
        from zvmsdk.database import ImageDbOperator
        imgname = 'test-img-' + uuid.uuid4().hex[:8]

        _set_node(NODE_A)
        ImageDbOperator().image_add_record(
            imgname, 'rhel8', 'abc123', '3338:CYL', '5368709120', 'netboot')

        # Node B should see the GLOBAL image
        _set_node(NODE_B)
        result = ImageDbOperator().image_query_record(imgname)
        self.assertGreater(len(result), 0,
                           "GLOBAL image must be visible from all nodes")

        # Cleanup
        _set_node(NODE_A)
        ImageDbOperator().image_delete_record(imgname)

    # ------------------------------------------------------------------
    # Task 8.2 — register_compute_node() upsert behaviour
    # ------------------------------------------------------------------

    def test_compute_node_upsert_updates_last_seen(self):
        """Calling register_compute_node() twice updates last_seen monotonically."""
        import zvmsdk.db.api as db_api

        _set_node(NODE_A)
        db_api.register_compute_node()

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                row1 = conn.execute(
                    text("SELECT last_seen FROM compute_nodes WHERE id=:id"),
                    {'id': NODE_A}).fetchone()
            ts1 = row1[0]

            # Allow NOW() to advance by at least 1 second
            time.sleep(1)
            db_api.register_compute_node()

            with engine.connect() as conn:
                row2 = conn.execute(
                    text("SELECT last_seen FROM compute_nodes WHERE id=:id"),
                    {'id': NODE_A}).fetchone()
            ts2 = row2[0]
        finally:
            engine.dispose()

        self.assertGreater(ts2, ts1,
                           "last_seen must increase on second register call")

    def test_compute_node_status_is_active_after_register(self):
        """Node status is 'active' immediately after register_compute_node()."""
        import zvmsdk.db.api as db_api
        _set_node(NODE_A)
        db_api.register_compute_node()

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM compute_nodes WHERE id=:id"),
                    {'id': NODE_A}).fetchone()
        finally:
            engine.dispose()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'active')

    # ------------------------------------------------------------------
    # Task 8.2 — deregister_compute_node()
    # ------------------------------------------------------------------

    def test_deregister_sets_status_inactive(self):
        """deregister_compute_node() transitions node status to 'inactive'."""
        import zvmsdk.db.api as db_api
        _set_node(NODE_B)
        db_api.register_compute_node()  # ensure active
        db_api.deregister_compute_node()

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM compute_nodes WHERE id=:id"),
                    {'id': NODE_B}).fetchone()
        finally:
            engine.dispose()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'inactive')

    def test_re_register_after_deregister_is_active(self):
        """Re-registering an inactive node makes it active again."""
        import zvmsdk.db.api as db_api
        _set_node(NODE_B)
        db_api.register_compute_node()
        db_api.deregister_compute_node()
        db_api.register_compute_node()  # simulates restart

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM compute_nodes WHERE id=:id"),
                    {'id': NODE_B}).fetchone()
        finally:
            engine.dispose()

        self.assertEqual(row[0], 'active')

    # ------------------------------------------------------------------
    # Task 8.2 — FK cascade on node removal
    # ------------------------------------------------------------------

    def test_fk_cascade_deletes_guests_when_node_removed(self):
        """Deleting a compute_nodes row must cascade-delete its guest rows."""
        from zvmsdk.database import GuestDbOperator

        TEMP_NODE = 'TEMP@ZVM1'
        uid = _uid()

        # Register temp node and insert a guest under it
        _register_node(TEMP_NODE)
        _set_node(TEMP_NODE)
        GuestDbOperator().add_guest(uid)

        engine = _plain_engine()
        try:
            # Verify guest exists
            with engine.connect() as conn:
                before = conn.execute(
                    text("SELECT COUNT(*) FROM guests "
                         "WHERE userid=:u AND compute_node_id=:n"),
                    {'u': uid, 'n': TEMP_NODE}).fetchone()[0]
            self.assertEqual(before, 1)

            # Delete node — FK CASCADE should remove the guest row
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM compute_nodes WHERE id=:id"),
                    {'id': TEMP_NODE})

            with engine.connect() as conn:
                after = conn.execute(
                    text("SELECT COUNT(*) FROM guests "
                         "WHERE userid=:u AND compute_node_id=:n"),
                    {'u': uid, 'n': TEMP_NODE}).fetchone()[0]
        finally:
            engine.dispose()

        self.assertEqual(after, 0,
                         "FK CASCADE must delete guest rows when node deleted")

    def test_fk_cascade_deletes_switch_records_when_node_removed(self):
        """Deleting a compute_nodes row must cascade-delete its switch rows."""
        from zvmsdk.database import NetworkDbOperator

        TEMP_NODE = 'TEMP2@ZVM1'
        uid = _uid()

        _register_node(TEMP_NODE)
        _set_node(TEMP_NODE)
        NetworkDbOperator().switch_add_record(uid, 'eth0')

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                before = conn.execute(
                    text("SELECT COUNT(*) FROM switch "
                         "WHERE userid=:u AND compute_node_id=:n"),
                    {'u': uid, 'n': TEMP_NODE}).fetchone()[0]
            self.assertEqual(before, 1)

            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM compute_nodes WHERE id=:id"),
                    {'id': TEMP_NODE})

            with engine.connect() as conn:
                after = conn.execute(
                    text("SELECT COUNT(*) FROM switch "
                         "WHERE userid=:u AND compute_node_id=:n"),
                    {'u': uid, 'n': TEMP_NODE}).fetchone()[0]
        finally:
            engine.dispose()

        self.assertEqual(after, 0)

    def test_node_restart_recreates_compute_nodes_entry(self):
        """register_compute_node() after FK-delete recreates the entry."""
        import zvmsdk.db.api as db_api
        RESTART_NODE = 'RESTART@ZVM1'

        _register_node(RESTART_NODE)

        # Simulate node being wiped from compute_nodes (e.g., admin cleanup)
        engine = _plain_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM compute_nodes WHERE id=:id"),
                    {'id': RESTART_NODE})
        finally:
            engine.dispose()

        # Simulate restart: register again
        _set_node(RESTART_NODE)
        db_api.register_compute_node()

        engine = _plain_engine()
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM compute_nodes WHERE id=:id"),
                    {'id': RESTART_NODE}).fetchone()
        finally:
            engine.dispose()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'active')


# ---------------------------------------------------------------------------
# Task 8.4 — SSL/TLS connectivity (optional, requires env vars)
# ---------------------------------------------------------------------------

@_SKIP_SSL
class TestSSLConnectionMariaDB(unittest.TestCase):
    """Verify that SSL/TLS connections work when ssl_ca is configured."""

    @classmethod
    def setUpClass(cls):
        _reset_engine_globals()
        base.set_conf('database', 'backend', 'mariadb')
        base.set_conf('database', 'connection', _SSL_URL)
        base.set_conf('database', 'mode', 'local')
        base.set_conf('database', 'compute_node_id', 'ssl-test-node')
        base.set_conf('database', 'ssl_ca', _SSL_CA)
        base.set_conf('database', 'pool_size', 2)
        base.set_conf('database', 'pool_max_overflow', 2)
        base.set_conf('database', 'pool_timeout', 10)
        base.set_conf('database', 'pool_recycle', 3600)

    @classmethod
    def tearDownClass(cls):
        _reset_engine_globals()
        _teardown_remote_conf()

    def test_ssl_connection_succeeds(self):
        """verify_remote_connectivity() succeeds over an SSL-enabled URL."""
        base.set_conf('database', 'mode', 'remote')
        import zvmsdk.db.api as db_api
        _reset_engine_globals()
        try:
            db_api.verify_remote_connectivity()
        except Exception as e:
            self.fail("SSL connectivity check failed: %s" % e)
        finally:
            base.set_conf('database', 'mode', 'local')
            _reset_engine_globals()

    def test_ssl_cipher_is_set(self):
        """Active SSL connection should report a non-empty cipher."""
        from zvmsdk.db import api as db_api
        _reset_engine_globals()
        base.set_conf('database', 'mode', 'local')
        engine = db_api.get_engine()
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SHOW STATUS LIKE 'Ssl_cipher'")).fetchone()
            # row[1] is the cipher value; must be non-empty for encrypted conn
            self.assertIsNotNone(row)
            self.assertGreater(len(row[1]), 0,
                               "Ssl_cipher must be non-empty for TLS connections")
        finally:
            _reset_engine_globals()


if __name__ == '__main__':
    unittest.main()
