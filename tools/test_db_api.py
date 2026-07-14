#!/usr/bin/env python3
"""
test_db_api.py — End-to-end smoke test for all feilong database API changes.

Usage:

  # SQLite (no extra setup needed — uses /tmp/zvmsdk_test/)
  python3 tools/test_db_api.py

  # MariaDB local/remote
  ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk" \
      python3 tools/test_db_api.py

  # Choose a specific compute_node_id (default: TEST-NODE)
  ZVMSDK_TEST_NODE_ID="node-A" python3 tools/test_db_api.py

Environment variables:
  ZVMSDK_TEST_DB_URL     Full SQLAlchemy URL for MariaDB.  When unset, SQLite is used.
  ZVMSDK_TEST_NODE_ID    compute_node_id to use (default: TEST-NODE).
  ZVMSDK_DB_PASSWORD     Password fallback for _build_url() (read by api.py automatically).

Exit code: 0 = all tests passed, 1 = one or more tests failed.
"""

import os
import sys
import shutil
import tempfile
import traceback
import uuid

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
_GREEN  = '\033[92m'
_RED    = '\033[91m'
_YELLOW = '\033[93m'
_RESET  = '\033[0m'

PASS = f'{_GREEN}PASS{_RESET}'
FAIL = f'{_RED}FAIL{_RESET}'
SKIP = f'{_YELLOW}SKIP{_RESET}'


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def record(self, name, ok, detail=''):
        if ok is None:
            self.skipped += 1
            tag = SKIP
        elif ok:
            self.passed += 1
            tag = PASS
        else:
            self.failed += 1
            tag = FAIL
        print(f'  [{tag}] {name}' + (f'  — {detail}' if detail else ''))

    def summary(self):
        total = self.passed + self.failed + self.skipped
        colour = _GREEN if self.failed == 0 else _RED
        print()
        print(f'{colour}Results: {self.passed} passed, '
              f'{self.failed} failed, {self.skipped} skipped '
              f'({total} total){_RESET}')
        return self.failed == 0


results = Results()


def run(name, fn, *args, skip_if=False, **kwargs):
    """Call fn(*args, **kwargs) and record pass/fail/skip."""
    if skip_if:
        results.record(name, None, 'skipped (condition not met)')
        return None
    try:
        ret = fn(*args, **kwargs)
        results.record(name, True)
        return ret
    except Exception as exc:
        results.record(name, False, f'{type(exc).__name__}: {exc}')
        if os.environ.get('ZVMSDK_TEST_VERBOSE'):
            traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Setup — configure zvmsdk before importing db modules
# ---------------------------------------------------------------------------

DB_URL   = os.environ.get('ZVMSDK_TEST_DB_URL', '')
NODE_ID  = os.environ.get('ZVMSDK_TEST_NODE_ID', 'TEST-NODE')
USE_MARIADB = bool(DB_URL)

# Temporary directory for SQLite test DB
_tmp_dir = tempfile.mkdtemp(prefix='zvmsdk_test_')

# Point zvmsdk config at our test environment before importing anything
from zvmsdk import config
CONF = config.CONF
CONF['database']['dir']             = _tmp_dir
CONF['database']['compute_node_id'] = NODE_ID

if USE_MARIADB:
    # Parse the URL just enough to set individual CONF options; the engine
    # factory also accepts the raw URL via CONF.database.connection.
    CONF['database']['backend']    = 'mariadb'
    CONF['database']['connection'] = DB_URL
    CONF['database']['mode']       = os.environ.get('ZVMSDK_TEST_MODE', 'local')
else:
    CONF['database']['backend'] = 'sqlite'
    CONF['database']['mode']    = 'local'

# network.my_ip is required=True; set a dummy value for non-z/VM hosts
CONF['network']['my_ip'] = '127.0.0.1'

# ---------------------------------------------------------------------------
# Import db modules (after config is patched)
# ---------------------------------------------------------------------------

from zvmsdk.db import api as db_api
from zvmsdk.db import migration as db_migration
from zvmsdk import database

# Reset engine globals so this script is idempotent when re-run in-process
db_api._ENGINE = None
db_api._COMPUTE_NODE_ID = ''
db_api._POOL_CHECKED_OUT = 0
db_api._POOL_CHECKED_IN  = 0
db_api._POOL_INVALIDATED = 0


# ---------------------------------------------------------------------------
# Section header printer
# ---------------------------------------------------------------------------

def section(title):
    print()
    print(f'{"─" * 60}')
    print(f'  {title}')
    print(f'{"─" * 60}')


# ===========================================================================
# 1. Migration — ensure_schema_current()
# ===========================================================================

section('1. Schema migration (ensure_schema_current)')

def _test_ensure_schema():
    db_migration.ensure_schema_current()
    return True

run('ensure_schema_current() creates tables', _test_ensure_schema)


# ===========================================================================
# 2. Engine factory — get_engine(), get_pool_status()
# ===========================================================================

section('2. Engine factory (get_engine / get_pool_status)')

def _test_get_engine_returns_engine():
    engine = db_api.get_engine()
    assert engine is not None
    return True

def _test_get_engine_is_singleton():
    e1 = db_api.get_engine()
    e2 = db_api.get_engine()
    assert e1 is e2
    return True

def _test_get_pool_status_has_backend():
    status = db_api.get_pool_status()
    assert 'backend' in status
    expected = 'mariadb' if USE_MARIADB else 'sqlite'
    assert status['backend'] == expected, f"expected {expected}, got {status['backend']}"
    return True

def _test_pool_status_has_lifetime_counters():
    status = db_api.get_pool_status()
    for key in ('lifetime_checked_out', 'lifetime_checked_in', 'lifetime_invalidated'):
        assert key in status, f"missing key: {key}"
    return True

def _test_pool_checkout_increments():
    before = db_api._POOL_CHECKED_OUT
    with db_api.get_connection():
        pass
    assert db_api._POOL_CHECKED_OUT > before
    return True

run('get_engine() returns engine object',       _test_get_engine_returns_engine)
run('get_engine() returns same singleton',      _test_get_engine_is_singleton)
run('get_pool_status() has backend key',        _test_get_pool_status_has_backend)
run('get_pool_status() has lifetime counters',  _test_pool_status_has_lifetime_counters)
run('checkout counter increments on use',       _test_pool_checkout_increments)


# ===========================================================================
# 3. compute_node_id resolution
# ===========================================================================

section('3. compute_node_id resolution')

def _test_node_id_from_config():
    node_id = db_api.get_compute_node_id()
    assert node_id == NODE_ID, f"expected '{NODE_ID}', got '{node_id}'"
    return True

run('get_compute_node_id() returns configured value', _test_node_id_from_config)


# ===========================================================================
# 4. get_connection() context manager
# ===========================================================================

section('4. get_connection() context manager')

from sqlalchemy import text

def _test_get_connection_commit():
    with db_api.get_connection() as conn:
        conn.execute(text(
            "INSERT OR REPLACE INTO compute_nodes "
            "(id, hostname, ip_address, status, last_seen) "
            "VALUES ('CONN-TEST', 'host', '1.2.3.4', 'active', datetime('now'))"
            if not USE_MARIADB else
            "INSERT INTO compute_nodes (id, hostname, ip_address, status, last_seen) "
            "VALUES ('CONN-TEST', 'host', '1.2.3.4', 'active', NOW()) "
            "ON DUPLICATE KEY UPDATE last_seen=NOW()"
        ))
    # Verify the write is visible after the context exits
    engine = db_api.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM compute_nodes WHERE id='CONN-TEST'")
        ).fetchone()
    assert row is not None
    return True

def _test_get_connection_rollback_on_exception():
    """Writes inside a context that raises must not persist."""
    unique_id = 'ROLLBACK-' + uuid.uuid4().hex[:8]
    try:
        with db_api.get_connection() as conn:
            conn.execute(text(
                "INSERT OR REPLACE INTO compute_nodes "
                "(id, hostname, ip_address, status, last_seen) "
                f"VALUES ('{unique_id}', 'host', '1.2.3.4', 'active', datetime('now'))"
                if not USE_MARIADB else
                f"INSERT INTO compute_nodes (id, hostname, ip_address, status, last_seen) "
                f"VALUES ('{unique_id}', 'host', '1.2.3.4', 'active', NOW())"
            ))
            raise ValueError('intentional error')
    except ValueError:
        pass
    engine = db_api.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT id FROM compute_nodes WHERE id='{unique_id}'")
        ).fetchone()
    assert row is None, 'rolled-back row must not be visible'
    return True

run('get_connection() commits on success',            _test_get_connection_commit)
run('get_connection() rolls back on exception',       _test_get_connection_rollback_on_exception)


# ===========================================================================
# 5. Node registration
# ===========================================================================

section('5. Node registration (register / deregister / check_stale_nodes)')

def _test_register_compute_node():
    db_api._COMPUTE_NODE_ID = NODE_ID
    db_api.register_compute_node()
    engine = db_api.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()
    assert row is not None, 'node row must exist after register'
    assert row[0] == 'active'
    return True

def _test_register_is_idempotent():
    db_api.register_compute_node()
    db_api.register_compute_node()
    engine = db_api.get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()[0]
    assert count == 1, f'expected 1 row, got {count}'
    return True

def _test_deregister_sets_inactive():
    db_api.deregister_compute_node()
    engine = db_api.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()
    assert row is not None
    assert row[0] == 'inactive'
    return True

def _test_check_stale_nodes_no_raise():
    # Re-register so the node is active again
    db_api.register_compute_node()
    db_api.check_stale_nodes(threshold_seconds=9999)
    return True

def _test_mark_stale_inactive():
    """Backdate a node's last_seen and verify it becomes inactive."""
    stale_id = 'STALE-' + uuid.uuid4().hex[:6]
    engine = db_api.get_engine()
    # Insert a node with a very old last_seen
    if USE_MARIADB:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO compute_nodes "
                "(id, hostname, ip_address, status, last_seen) "
                "VALUES (:id, 'old-host', '9.9.9.9', 'active', "
                "NOW() - INTERVAL 600 SECOND)"
            ), {'id': stale_id})
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT OR REPLACE INTO compute_nodes "
                "(id, hostname, ip_address, status, last_seen) "
                "VALUES (:id, 'old-host', '9.9.9.9', 'active', "
                "datetime('now', '-600 seconds'))"
            ), {'id': stale_id})

    db_api._mark_stale_nodes_inactive(threshold_seconds=1)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM compute_nodes WHERE id=:id"),
            {'id': stale_id}
        ).fetchone()
    assert row is not None
    assert row[0] == 'inactive', f'expected inactive, got {row[0]}'
    return True

run('register_compute_node() creates active row',     _test_register_compute_node)
run('register_compute_node() is idempotent',          _test_register_is_idempotent)
run('deregister_compute_node() sets inactive',        _test_deregister_sets_inactive)
run('check_stale_nodes() does not raise',             _test_check_stale_nodes_no_raise)
run('_mark_stale_nodes_inactive() marks old nodes',   _test_mark_stale_inactive)

# Re-register so operators can use the node
db_api.register_compute_node()


# ===========================================================================
# 6. verify_remote_connectivity()
# ===========================================================================

section('6. verify_remote_connectivity()')

def _test_verify_remote_noop_in_local():
    CONF['database']['mode'] = 'local'
    db_api.verify_remote_connectivity()  # must not raise
    return True

def _test_verify_remote_succeeds_when_reachable():
    CONF['database']['mode'] = 'remote'
    db_api.verify_remote_connectivity()
    return True

run('verify_remote_connectivity() is no-op in local mode',
    _test_verify_remote_noop_in_local)
run('verify_remote_connectivity() succeeds when reachable (remote mode)',
    _test_verify_remote_succeeds_when_reachable,
    skip_if=not USE_MARIADB)

# Restore mode
CONF['database']['mode'] = 'remote' if USE_MARIADB else 'local'


# ===========================================================================
# 7. NetworkDbOperator (switch table)
# ===========================================================================

section('7. NetworkDbOperator (switch table)')

net_op = database.NetworkDbOperator()

def _test_switch_add_record():
    net_op.switch_add_record('TESTUSER', 'eth0', port='1234', switch='VSWITCH1')
    return True

def _test_switch_select_record():
    rows = net_op.switch_select_record(userid='TESTUSER')
    assert len(rows) >= 1, 'expected at least one row'
    return True

def _test_switch_select_table():
    rows = net_op.switch_select_table()
    assert isinstance(rows, list)
    return True

def _test_switch_select_record_for_userid():
    rows = net_op.switch_select_record_for_userid('TESTUSER')
    assert len(rows) >= 1
    return True

def _test_switch_update_record():
    net_op.switch_update_record_with_switch('TESTUSER', 'eth0', 'VSWITCH2')
    rows = net_op.switch_select_record(userid='TESTUSER')
    switches = [r['switch'] for r in rows]
    assert 'VSWITCH2' in switches
    return True

def _test_switch_delete_record_for_nic():
    net_op.switch_delete_record_for_nic('TESTUSER', 'eth0')
    rows = net_op.switch_select_record(userid='TESTUSER')
    assert len(rows) == 0
    return True

def _test_switch_delete_record_for_userid():
    net_op.switch_add_record('DELUSER', 'eth0')
    net_op.switch_delete_record_for_userid('DELUSER')
    rows = net_op.switch_select_record(userid='DELUSER')
    assert len(rows) == 0
    return True

run('switch_add_record() inserts row',              _test_switch_add_record)
run('switch_select_record() returns rows',          _test_switch_select_record)
run('switch_select_table() returns list',           _test_switch_select_table)
run('switch_select_record_for_userid() works',      _test_switch_select_record_for_userid)
run('switch_update_record_with_switch() updates',   _test_switch_update_record)
run('switch_delete_record_for_nic() removes row',   _test_switch_delete_record_for_nic)
run('switch_delete_record_for_userid() removes all',_test_switch_delete_record_for_userid)


# ===========================================================================
# 8. GuestDbOperator (guests table)
# ===========================================================================

section('8. GuestDbOperator (guests table)')

guest_op = database.GuestDbOperator()
_GUEST_USERID = 'TESTGUEST'
_GUEST_META   = 'key1=val1,key2=val2'

def _test_add_guest():
    guest_op.add_guest(_GUEST_USERID, meta=_GUEST_META, comments=None)
    return True

def _test_get_guest_list():
    rows = guest_op.get_guest_list()
    userids = [r['userid'] for r in rows]
    assert _GUEST_USERID in userids
    return True

def _test_get_guest_by_userid():
    row = guest_op.get_guest_by_userid(_GUEST_USERID)
    assert row is not None
    assert row['userid'] == _GUEST_USERID
    return True

def _test_get_guest_metadata():
    result = guest_op.get_guest_metadata_with_userid(_GUEST_USERID)
    assert len(result) >= 1, 'expected at least one metadata row'
    assert result[0]['metadata'] == _GUEST_META, \
        f'expected "{_GUEST_META}", got "{result[0]["metadata"]}"'
    return True

def _test_update_guest_by_userid():
    guest_op.update_guest_by_userid(_GUEST_USERID, meta='updated=yes')
    row = guest_op.get_guest_by_userid(_GUEST_USERID)
    assert row['metadata'] == 'updated=yes'
    return True

def _test_get_comments_by_userid():
    result = guest_op.get_comments_by_userid(_GUEST_USERID)
    assert isinstance(result, dict)
    return True

def _test_get_metadata_by_userid():
    meta_str = guest_op.get_metadata_by_userid(_GUEST_USERID)
    assert isinstance(meta_str, str)
    return True

def _test_delete_guest_by_userid():
    guest_op.delete_guest_by_userid(_GUEST_USERID)
    row = guest_op.get_guest_by_userid(_GUEST_USERID)
    assert row is None
    return True

def _test_add_guest_registered():
    uid = 'REGUEST'
    guest_op.add_guest_registered(uid, meta='', net_set=1, comments=None)
    row = guest_op.get_guest_by_userid(uid)
    assert row is not None
    guest_op.delete_guest_by_userid(uid)
    return True

run('add_guest() inserts guest row',                 _test_add_guest)
run('get_guest_list() returns user in list',         _test_get_guest_list)
run('get_guest_by_userid() returns row',             _test_get_guest_by_userid)
run('get_guest_metadata_with_userid() returns meta', _test_get_guest_metadata)
run('update_guest_by_userid() changes metadata',     _test_update_guest_by_userid)
run('get_comments_by_userid() returns value',        _test_get_comments_by_userid)
run('get_metadata_by_userid() returns dict',         _test_get_metadata_by_userid)
run('delete_guest_by_userid() removes row',          _test_delete_guest_by_userid)
run('add_guest_registered() inserts full row',       _test_add_guest_registered)


# ===========================================================================
# 9. ImageDbOperator (image table)
# ===========================================================================

section('9. ImageDbOperator (image table)')

img_op = database.ImageDbOperator()
_IMG_NAME = 'test-image-' + uuid.uuid4().hex[:6]

def _test_image_add_record():
    img_op.image_add_record(
        imagename=_IMG_NAME,
        imageosdistro='rhel9',
        md5sum='abc123',
        disk_size_units='3339:CYL',
        image_size_in_bytes='4294967296',
        type='rootonly',
        comments='test image'
    )
    return True

def _test_image_query_record_all():
    rows = img_op.image_query_record()
    names = [r['imagename'] for r in rows]
    assert _IMG_NAME in names
    return True

def _test_image_query_record_by_name():
    rows = img_op.image_query_record(imagename=_IMG_NAME)
    assert len(rows) == 1
    assert rows[0]['imagename'] == _IMG_NAME
    assert rows[0]['imageosdistro'] == 'rhel9'
    return True

def _test_image_delete_record():
    img_op.image_delete_record(_IMG_NAME)
    all_rows = img_op.image_query_record()
    names = [r['imagename'] for r in all_rows]
    assert _IMG_NAME not in names
    return True

run('image_add_record() inserts image row',          _test_image_add_record)
run('image_query_record() lists all images',         _test_image_query_record_all)
run('image_query_record(name) returns exact image',  _test_image_query_record_by_name)
run('image_delete_record() removes image',           _test_image_delete_record)


# ===========================================================================
# 10. FCPDbOperator (fcp + template tables)
# ===========================================================================

section('10. FCPDbOperator (fcp + template tables)')

fcp_op = database.FCPDbOperator()
_FCP_ID = '1A01'
_TMPL_ID = 'tmpl-' + uuid.uuid4().hex[:6]

def _test_fcp_bulk_insert():
    fcp_info = [(_FCP_ID, 'c050760a0001801a', 'c050760a00018000', '1A', '01A0', 'free', '')]
    fcp_op.bulk_insert_zvm_fcp_info_into_fcp_table(fcp_info)
    return True

def _test_fcp_get_all():
    rows = fcp_op.get_all()
    fcp_ids = [r['fcp_id'] for r in rows]
    assert _FCP_ID in fcp_ids
    return True

def _test_fcp_get_usage():
    row = fcp_op.get_usage_of_fcp(_FCP_ID)
    assert row is not None
    return True

def _test_fcp_reserve():
    fcp_op.reserve_fcps([_FCP_ID], assigner_id='GUEST1',
                        fcp_template_id=_TMPL_ID)
    return True

def _test_fcp_get_all_of_assigner():
    rows = fcp_op.get_all_fcps_of_assigner(assigner_id='GUEST1')
    assert any(r['fcp_id'] == _FCP_ID for r in rows)
    return True

def _test_fcp_unreserve():
    fcp_op.unreserve_fcps([_FCP_ID])
    return True

def _test_fcp_create_template():
    fcp_op.create_fcp_template(
        fcp_template_id=_TMPL_ID,
        name='Test Template',
        description='Created by test_db_api.py',
        fcp_devices_by_path={},
        host_default=False,
        default_sp_list=[],
        min_fcp_paths_count=0
    )
    return True

def _test_fcp_template_exists():
    exists = fcp_op.fcp_template_exist_in_db(_TMPL_ID)
    assert exists
    return True

def _test_fcp_get_templates():
    rows = fcp_op.get_fcp_templates(template_id_list=[_TMPL_ID])
    assert len(rows) >= 1
    return True

def _test_fcp_delete_template():
    fcp_op.delete_fcp_template(_TMPL_ID)
    exists = fcp_op.fcp_template_exist_in_db(_TMPL_ID)
    assert not exists
    return True

def _test_fcp_bulk_delete():
    fcp_op.bulk_delete_from_fcp_table([_FCP_ID])
    rows = fcp_op.get_all()
    assert not any(r['fcp_id'] == _FCP_ID for r in rows)
    return True

run('bulk_insert_zvm_fcp_info_into_fcp_table() works', _test_fcp_bulk_insert)
run('get_all() lists FCP rows',                         _test_fcp_get_all)
run('get_usage_of_fcp() returns row',                   _test_fcp_get_usage)
run('reserve_fcps() updates assigner',                  _test_fcp_reserve)
run('get_all_fcps_of_assigner() filters by assigner',   _test_fcp_get_all_of_assigner)
run('unreserve_fcps() clears assigner',                 _test_fcp_unreserve)
run('create_fcp_template() inserts template',           _test_fcp_create_template)
run('fcp_template_exist_in_db() returns True',          _test_fcp_template_exists)
run('get_fcp_templates() returns template list',        _test_fcp_get_templates)
run('delete_fcp_template() removes template',           _test_fcp_delete_template)
run('bulk_delete_from_fcp_table() removes FCP rows',    _test_fcp_bulk_delete)


# ===========================================================================
# 11. _node_filter() helper
# ===========================================================================

section('11. _node_filter() helper (mode-aware read scoping)')

def _test_node_filter_empty_in_local():
    original = CONF['database']['mode']
    CONF['database']['mode'] = 'local'
    sql, params = database._node_filter()
    CONF['database']['mode'] = original
    assert sql == '' and params == {}
    return True

def _test_node_filter_clause_in_remote():
    original = CONF['database']['mode']
    CONF['database']['mode'] = 'remote'
    sql, params = database._node_filter()
    CONF['database']['mode'] = original
    assert 'compute_node_id' in sql
    assert 'node_id' in params
    return True

def _test_node_filter_with_prefix():
    original = CONF['database']['mode']
    CONF['database']['mode'] = 'remote'
    sql, params = database._node_filter(prefix='fcp')
    CONF['database']['mode'] = original
    assert 'fcp.compute_node_id' in sql
    return True

run('_node_filter() returns empty in local mode',       _test_node_filter_empty_in_local)
run('_node_filter() returns clause in remote mode',     _test_node_filter_clause_in_remote)
run('_node_filter(prefix) uses qualified column',       _test_node_filter_with_prefix)


# ===========================================================================
# 12. Credential hardening — ZVMSDK_DB_PASSWORD env var
# ===========================================================================

section('12. Credential hardening (ZVMSDK_DB_PASSWORD)')

def _test_password_from_env():
    """_build_url() uses ZVMSDK_DB_PASSWORD when config password is empty."""
    original_backend = CONF['database']['backend']
    original_pass    = CONF['database'].get('password', '')
    CONF['database']['backend']    = 'mariadb'
    CONF['database']['password']   = ''
    CONF['database']['host']       = '127.0.0.1'
    CONF['database']['port']       = 3306
    CONF['database']['user']       = 'zvmsdk'
    CONF['database']['name']       = 'zvmsdk'
    os.environ['ZVMSDK_DB_PASSWORD'] = 'env-secret-test'
    try:
        url = db_api._build_url()
        assert url.password == 'env-secret-test', \
            f"expected 'env-secret-test', got '{url.password}'"
        assert 'env-secret-test' not in str(url), \
            'password must not appear in str(url)'
    finally:
        CONF['database']['backend']  = original_backend
        CONF['database']['password'] = original_pass
        del os.environ['ZVMSDK_DB_PASSWORD']
    return True

def _test_password_not_in_url_str():
    original_backend = CONF['database']['backend']
    original_pass    = CONF['database'].get('password', '')
    CONF['database']['backend']  = 'mariadb'
    CONF['database']['password'] = 'do-not-log-me'
    CONF['database']['host']     = '127.0.0.1'
    CONF['database']['port']     = 3306
    CONF['database']['user']     = 'zvmsdk'
    CONF['database']['name']     = 'zvmsdk'
    try:
        url = db_api._build_url()
        assert 'do-not-log-me' not in str(url)
    finally:
        CONF['database']['backend']  = original_backend
        CONF['database']['password'] = original_pass
    return True

run('_build_url() uses ZVMSDK_DB_PASSWORD when config password empty',
    _test_password_from_env)
run('password absent from str(url) (log safety)',
    _test_password_not_in_url_str)


# ===========================================================================
# 13. Remote mode isolation (MariaDB only)
# ===========================================================================

section('13. Remote mode isolation (MariaDB only)')

def _test_remote_isolation_guests():
    """Guest written by node A must not be visible when querying as node B."""
    original_node = db_api._COMPUTE_NODE_ID
    original_mode = CONF['database']['mode']
    CONF['database']['mode'] = 'remote'

    try:
        # Write as NODE-A
        db_api._COMPUTE_NODE_ID = 'ISO-NODE-A'
        db_api.register_compute_node()
        gop = database.GuestDbOperator()
        gop.add_guest('ISOGST', meta='', comments='isolation test')

        # Read as NODE-B
        db_api._COMPUTE_NODE_ID = 'ISO-NODE-B'
        db_api.register_compute_node()
        row = gop.get_guest_by_userid('ISOGST')
        assert row is None, \
            'NODE-B must not see NODE-A\'s guest in remote mode'
    finally:
        # Cleanup
        db_api._COMPUTE_NODE_ID = 'ISO-NODE-A'
        gop.delete_guest_by_userid('ISOGST')
        db_api._COMPUTE_NODE_ID = original_node
        CONF['database']['mode'] = original_mode
    return True

def _test_remote_image_global_sharing():
    """Images with compute_node_id='GLOBAL' are visible from all nodes."""
    original_node = db_api._COMPUTE_NODE_ID
    original_mode = CONF['database']['mode']
    CONF['database']['mode'] = 'remote'
    global_img = 'global-img-' + uuid.uuid4().hex[:6]

    try:
        # Write global image as NODE-A
        db_api._COMPUTE_NODE_ID = 'IMG-NODE-A'
        db_api.register_compute_node()
        iop = database.ImageDbOperator()
        iop.image_add_record(global_img, 'rhel9', 'abc', '100:CYL', '1024', 'rootonly')

        # Read as NODE-B — global images should be visible
        db_api._COMPUTE_NODE_ID = 'IMG-NODE-B'
        db_api.register_compute_node()
        rows = iop.image_query_record(imagename=global_img)
        # Images use GLOBAL node_id so they are accessible from any node
        assert len(rows) >= 1, 'global image must be visible from any node'
    finally:
        db_api._COMPUTE_NODE_ID = 'IMG-NODE-A'
        iop.image_delete_record(global_img)
        db_api._COMPUTE_NODE_ID = original_node
        CONF['database']['mode'] = original_mode
    return True

run('Remote: guest isolation between nodes',
    _test_remote_isolation_guests,
    skip_if=not USE_MARIADB)
run('Remote: global images visible from all nodes',
    _test_remote_image_global_sharing,
    skip_if=not USE_MARIADB)


# ===========================================================================
# 14. deregister on clean shutdown
# ===========================================================================

section('14. deregister_compute_node() on shutdown')

def _test_deregister_on_shutdown():
    db_api._COMPUTE_NODE_ID = NODE_ID
    db_api.register_compute_node()  # ensure active
    db_api.deregister_compute_node()
    engine = db_api.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()
    assert row is not None
    assert row[0] == 'inactive'
    return True

run('deregister_compute_node() marks node inactive', _test_deregister_on_shutdown)

# Re-register so subsequent sections have a live node row.
db_api.register_compute_node()


# ===========================================================================
# 15. SDKAPI layer — image_query() (full feilong API stack)
# ===========================================================================
# dev.md Phase 4/8 requirement: verify the full chain
#   SDKAPI → imageops → smtclient → ImageDbOperator.image_query_record()
# works end-to-end with the new SQLAlchemy backend.

section('15. SDKAPI layer — image_query() full stack')

# SDKAPI.__init__ pulls in smtclient, vmops, networkops, etc.  Those modules
# initialise fine without a real z/VM — they only touch z/VM during actual
# SMT requests.  Wrap the instantiation so tests are skipped gracefully on
# environments where config is incomplete.
_sdkapi = None
_sdkapi_skip_reason = ''
try:
    from zvmsdk import api as _sdk_module
    _sdkapi = _sdk_module.SDKAPI()
    _sdkapi_available = True
except Exception as _sdkapi_exc:
    _sdkapi_available = False
    _sdkapi_skip_reason = f'{type(_sdkapi_exc).__name__}: {_sdkapi_exc}'
    print(f'  [note] SDKAPI unavailable — {_sdkapi_skip_reason}; '
          f'sections 15-16 will be skipped')

_API_IMG_NAME = 'api-img-' + uuid.uuid4().hex[:6]

def _test_sdkapi_image_query_finds_seeded_record():
    """SDKAPI.image_query() returns a record seeded via ImageDbOperator."""
    img_op.image_add_record(
        imagename=_API_IMG_NAME,
        imageosdistro='rhel9',
        md5sum='deadbeef00',
        disk_size_units='500:CYL',
        image_size_in_bytes='536870912',
        type='rootonly',
        comments='sdkapi layer test'
    )
    try:
        rows = _sdkapi.image_query(imagename=_API_IMG_NAME)
        assert len(rows) >= 1, f'expected ≥1 row, got {len(rows)}'
        names = [r['imagename'] for r in rows]
        assert _API_IMG_NAME in names, f'{_API_IMG_NAME!r} not in result'
        assert rows[0]['imageosdistro'] == 'rhel9'
    finally:
        img_op.image_delete_record(_API_IMG_NAME)
    return True

def _test_sdkapi_image_query_returns_empty_for_missing():
    """SDKAPI.image_query() returns [] for an image that does not exist."""
    rows = _sdkapi.image_query(imagename='no-such-img-' + uuid.uuid4().hex[:6])
    assert rows == [], f'expected [], got {rows}'
    return True

def _test_sdkapi_image_query_all_returns_list():
    """SDKAPI.image_query() with no name returns a list (possibly empty)."""
    rows = _sdkapi.image_query()
    assert isinstance(rows, list)
    return True

run('SDKAPI.image_query(name) finds seeded image via full stack',
    _test_sdkapi_image_query_finds_seeded_record,
    skip_if=not _sdkapi_available)
run('SDKAPI.image_query(missing) returns []',
    _test_sdkapi_image_query_returns_empty_for_missing,
    skip_if=not _sdkapi_available)
run('SDKAPI.image_query() with no args returns list',
    _test_sdkapi_image_query_all_returns_list,
    skip_if=not _sdkapi_available)


# ===========================================================================
# 16. SDKAPI layer — guests_get_nic_info() (full feilong API stack)
# ===========================================================================
# dev.md Phase 3/4 requirement: verify the full chain
#   SDKAPI → networkops → smtclient → NetworkDbOperator.switch_select_record()
# reaches the database correctly.

section('16. SDKAPI layer — guests_get_nic_info() full stack')

_NIC_USERID = 'APINIST'
_NIC_PORT   = 'port-' + uuid.uuid4().hex[:6]

def _test_sdkapi_nic_info_by_userid():
    """guests_get_nic_info(userid) reads switch table through the full API chain."""
    net_op.switch_add_record(_NIC_USERID, 'eth0',
                             port=_NIC_PORT, switch='VSWTST')
    try:
        rows = _sdkapi.guests_get_nic_info(userid=_NIC_USERID)
        assert len(rows) >= 1, f'expected ≥1 row, got {len(rows)}'
        found_userids = [r['userid'] for r in rows]
        assert _NIC_USERID in found_userids, \
            f'{_NIC_USERID!r} not in result userids'
    finally:
        net_op.switch_delete_record_for_userid(_NIC_USERID)
    return True

def _test_sdkapi_nic_info_by_nic_id():
    """guests_get_nic_info(nic_id=port) reads switch table by port column."""
    net_op.switch_add_record(_NIC_USERID, 'eth1',
                             port=_NIC_PORT, switch='VSWTST')
    try:
        rows = _sdkapi.guests_get_nic_info(nic_id=_NIC_PORT)
        assert len(rows) >= 1, 'nic_id lookup returned no rows'
        ports = [r['port'] for r in rows]
        assert _NIC_PORT in ports, f'{_NIC_PORT!r} not in ports'
    finally:
        net_op.switch_delete_record_for_userid(_NIC_USERID)
    return True

def _test_sdkapi_nic_info_returns_empty_for_unknown_user():
    """guests_get_nic_info() returns [] for a userid with no NIC records."""
    rows = _sdkapi.guests_get_nic_info(userid='NO-SUCH-USER')
    assert isinstance(rows, list)
    assert len(rows) == 0
    return True

run('SDKAPI.guests_get_nic_info(userid) finds NIC via full stack',
    _test_sdkapi_nic_info_by_userid,
    skip_if=not _sdkapi_available)
run('SDKAPI.guests_get_nic_info(nic_id) finds NIC by port ID',
    _test_sdkapi_nic_info_by_nic_id,
    skip_if=not _sdkapi_available)
run('SDKAPI.guests_get_nic_info() returns [] for unknown user',
    _test_sdkapi_nic_info_returns_empty_for_unknown_user,
    skip_if=not _sdkapi_available)


# ===========================================================================
# 17. compute_node_id injection verification (Phase 5 — dev.md)
# ===========================================================================
# dev.md §5: "test_backfill_writes_node_id — after migration, insert a guest;
# read back and assert compute_node_id equals the resolved node ID."
# Extended to cover switch and image tables as well.

section('17. compute_node_id injection (Phase 5 dev.md)')

_CID_USER = 'CIDTST'
_CID_IMG  = 'cid-img-' + uuid.uuid4().hex[:6]

def _test_guest_row_carries_compute_node_id():
    """INSERT via GuestDbOperator must stamp compute_node_id on the row."""
    guest_op.add_guest(_CID_USER, meta='', comments=None)
    try:
        expected = db_api.get_compute_node_id()
        with db_api.get_connection() as conn:
            row = conn.execute(
                text("SELECT compute_node_id FROM guests WHERE userid=:uid"),
                {'uid': _CID_USER}
            ).fetchone()
        assert row is not None, 'guest row missing'
        assert row[0] == expected, \
            f'guest compute_node_id: expected {expected!r}, got {row[0]!r}'
    finally:
        guest_op.delete_guest_by_userid(_CID_USER)
    return True

def _test_switch_row_carries_compute_node_id():
    """INSERT via NetworkDbOperator must stamp compute_node_id on the row."""
    net_op.switch_add_record(_CID_USER, 'eth0', port=None, switch='VSWTST')
    try:
        expected = db_api.get_compute_node_id()
        with db_api.get_connection() as conn:
            row = conn.execute(
                text("SELECT compute_node_id FROM switch "
                     "WHERE userid=:uid AND interface='eth0'"),
                {'uid': _CID_USER}
            ).fetchone()
        assert row is not None, 'switch row missing'
        assert row[0] == expected, \
            f'switch compute_node_id: expected {expected!r}, got {row[0]!r}'
    finally:
        net_op.switch_delete_record_for_userid(_CID_USER)
    return True

def _test_image_row_compute_node_id_populated():
    """INSERT via ImageDbOperator must populate compute_node_id (not blank)."""
    img_op.image_add_record(
        imagename=_CID_IMG,
        imageosdistro='ubuntu22',
        md5sum='abc',
        disk_size_units='200:CYL',
        image_size_in_bytes='1024',
        type='rootonly',
        comments=None
    )
    try:
        with db_api.get_connection() as conn:
            row = conn.execute(
                text("SELECT compute_node_id FROM image WHERE imagename=:n"),
                {'n': _CID_IMG}
            ).fetchone()
        assert row is not None, 'image row missing'
        assert row[0] is not None and row[0] != '', \
            f'image compute_node_id must not be empty, got {row[0]!r}'
    finally:
        img_op.image_delete_record(_CID_IMG)
    return True

run('Guest INSERT stamps correct compute_node_id',  _test_guest_row_carries_compute_node_id)
run('Switch INSERT stamps correct compute_node_id', _test_switch_row_carries_compute_node_id)
run('Image INSERT populates compute_node_id',       _test_image_row_compute_node_id_populated)


# ===========================================================================
# 18. last_seen upsert on re-register (Phase 6 — dev.md)
# ===========================================================================
# dev.md §6: "test_compute_node_upsert_updates_last_seen — call
# register_compute_node() twice; assert last_seen timestamp increases."

section('18. last_seen upsert on re-register (Phase 6 dev.md)')

def _test_register_twice_advances_last_seen():
    """Second register_compute_node() call must update last_seen."""
    db_api.register_compute_node()
    engine = db_api.get_engine()

    # Backdate last_seen so the next register is guaranteed to produce a newer
    # timestamp even at sub-second precision on fast hardware.
    if USE_MARIADB:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE compute_nodes "
                "SET last_seen = NOW() - INTERVAL 10 SECOND "
                "WHERE id=:id"
            ), {'id': NODE_ID})
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE compute_nodes "
                "SET last_seen = datetime('now', '-10 seconds') "
                "WHERE id=:id"
            ), {'id': NODE_ID})

    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT last_seen FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()[0]

    db_api.register_compute_node()

    with engine.connect() as conn:
        after_row = conn.execute(
            text("SELECT last_seen, status FROM compute_nodes WHERE id=:id"),
            {'id': NODE_ID}
        ).fetchone()

    assert after_row is not None
    assert after_row[1] == 'active', \
        f'expected status=active, got {after_row[1]!r}'
    assert after_row[0] >= before, \
        f'last_seen did not advance: before={before}, after={after_row[0]}'
    return True

run('register_compute_node() advances last_seen on re-register',
    _test_register_twice_advances_last_seen)


# ===========================================================================
# 19. FK cascade delete on node removal (Phase 6 — dev.md)
# ===========================================================================
# dev.md §6: "test_fk_cascade_on_node_removal — delete a compute_nodes row;
# assert its fcp/switch/guest rows are cascade-deleted."
# FK constraints are only active in MariaDB + remote mode (migration 0004).

section('19. FK cascade delete on node removal (Phase 6 dev.md, MariaDB+remote only)')

_CASCADE_NODE = 'CAS-' + uuid.uuid4().hex[:6]
_CASCADE_USER = 'CASUSR'
_USE_FK = USE_MARIADB and (CONF['database'].get('mode') == 'remote')

def _test_fk_cascade_on_node_removal():
    """Delete compute_nodes row → guest + switch rows are cascade-deleted."""
    engine = db_api.get_engine()

    # Insert the throwaway compute_node
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO compute_nodes "
            "(id, hostname, ip_address, status, last_seen) "
            "VALUES (:id, 'cas-host', '10.99.99.99', 'active', NOW())"
        ), {'id': _CASCADE_NODE})

    # Insert scoped guest (bypass operator to control compute_node_id directly)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO guests (id, userid, compute_node_id, net_set) "
            "VALUES (:gid, :uid, :nid, 0)"
        ), {'gid': str(uuid.uuid4()), 'uid': _CASCADE_USER,
            'nid': _CASCADE_NODE})

    # Insert scoped switch record
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO switch (userid, interface, compute_node_id) "
            "VALUES (:uid, 'eth0', :nid)"
        ), {'uid': _CASCADE_USER, 'nid': _CASCADE_NODE})

    # Delete the compute_nodes row — FK ON DELETE CASCADE must remove the
    # scoped guest and switch rows automatically.
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM compute_nodes WHERE id=:id"),
            {'id': _CASCADE_NODE}
        )

    with engine.connect() as conn:
        g_count = conn.execute(
            text("SELECT COUNT(*) FROM guests WHERE compute_node_id=:nid"),
            {'nid': _CASCADE_NODE}
        ).fetchone()[0]
        s_count = conn.execute(
            text("SELECT COUNT(*) FROM switch WHERE compute_node_id=:nid"),
            {'nid': _CASCADE_NODE}
        ).fetchone()[0]

    assert g_count == 0, \
        f'expected 0 guest rows after cascade delete, got {g_count}'
    assert s_count == 0, \
        f'expected 0 switch rows after cascade delete, got {s_count}'
    return True

run('FK cascade: guest+switch rows deleted when compute_node removed',
    _test_fk_cascade_on_node_removal,
    skip_if=not _USE_FK)


# ===========================================================================
# Cleanup
# ===========================================================================

# Deregister cleanly
try:
    db_api.deregister_compute_node()
except Exception:
    pass

shutil.rmtree(_tmp_dir, ignore_errors=True)


# ===========================================================================
# Final summary
# ===========================================================================

print()
backend_label = f'MariaDB ({DB_URL.split("@")[-1]})' if USE_MARIADB else f'SQLite ({_tmp_dir})'
print(f'Backend: {backend_label}')
print(f'Node ID: {NODE_ID}')

ok = results.summary()
sys.exit(0 if ok else 1)
