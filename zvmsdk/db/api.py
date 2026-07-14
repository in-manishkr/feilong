#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import socket
import subprocess  # nosec B404 — used only with a fixed argument list, no shell=True
import threading

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import QueuePool, StaticPool

from zvmsdk import config
from zvmsdk import exception
from zvmsdk import log

CONF = config.CONF
LOG = log.LOG

_ENGINE = None
_ENGINE_LOCK = threading.Lock()
_COMPUTE_NODE_ID = ''

# Thread-local storage so nested get_connection() calls in the same thread
# reuse the same transaction instead of trying to open a second one on the
# same underlying SQLite connection (StaticPool shares a single connection).
_CONN_LOCAL = threading.local()

# ---------------------------------------------------------------------------
# Pool event counters (9.1)
# Integer increments are GIL-safe in CPython; no explicit lock needed.
# ---------------------------------------------------------------------------
_POOL_CHECKED_OUT = 0
_POOL_CHECKED_IN = 0
_POOL_INVALIDATED = 0


def get_compute_node_id():
    """Return the compute_node_id resolved at engine-init time."""
    return _COMPUTE_NODE_ID


def _resolve_compute_node_id():
    """Resolve this node's compute_node_id once at startup.

    Priority:
      1. CONF.database.compute_node_id  — explicit operator override
      2. vmcp query userid              — z/VM native: "USERID@ZVM_SYSTEM"
      3. CONF.network.my_ip             — always-available required config field
    """
    # Priority 1: explicit config
    explicit = getattr(CONF.database, 'compute_node_id', None)
    if explicit:
        LOG.info("compute_node_id set from config: %s", explicit)
        return explicit

    # Priority 2: vmcp query userid (z/VM guests only).
    # Both get_smt_userid() and get_zvm_name() in utils.py independently exec
    # the same vmcp command. We call it once here and split the result directly
    # to avoid the double subprocess overhead.
    try:
        out = subprocess.check_output(  # nosec B603,B607 — fixed args, no user input
            ["sudo", "/sbin/vmcp", "query", "userid"],
            close_fds=True,
            stderr=subprocess.STDOUT,
        )
        tokens = bytes.decode(out).split()   # e.g. ["IAAS01EF", "AT", "BOEM5401"]
        node_id = "%s@%s" % (tokens[0], tokens[-1])
        LOG.info("compute_node_id auto-detected via vmcp: %s", node_id)
        return node_id
    except Exception:  # nosec B110 — intentional: not a z/VM guest, fall through
        pass

    # Priority 3: my_ip is declared required=True in config.py so it is always
    # present in any correctly deployed feilong instance.
    node_id = CONF.network.my_ip or ''
    LOG.info("compute_node_id auto-detected from my_ip: %s", node_id)
    return node_id


def get_engine():
    """Return the shared SQLAlchemy engine, creating it on first call.

    Thread-safe via double-checked locking: the fast path (engine already
    built) avoids lock acquisition; the slow path (first call) serialises
    through _ENGINE_LOCK so _resolve_compute_node_id() runs exactly once.
    """
    global _ENGINE, _COMPUTE_NODE_ID

    # Fast path — no lock needed once the engine exists.
    if _ENGINE is not None:
        return _ENGINE

    with _ENGINE_LOCK:
        # Re-check under lock to handle the race where two threads both
        # passed the fast-path check before either acquired the lock.
        if _ENGINE is not None:
            return _ENGINE

        _COMPUTE_NODE_ID = _resolve_compute_node_id()
        LOG.info("Feilong compute_node_id for this session: %s",
                 _COMPUTE_NODE_ID)

        backend = getattr(CONF.database, 'backend', 'sqlite')
        mode = getattr(CONF.database, 'mode', 'local')

        if mode == 'remote' and backend == 'sqlite':
            raise exception.SDKInternalError(
                msg="database.mode=remote requires backend=mariadb or "
                    "backend=mysql, not backend=sqlite")

        if backend == 'sqlite':
            db_path = os.path.join(CONF.database.dir, 'zvmsdk.db')
            _ENGINE = create_engine(
                'sqlite:///%s' % db_path,
                connect_args={'check_same_thread': False},
                poolclass=StaticPool,
            )
        else:
            # MariaDB/MySQL path — implemented in Phase 4.
            url = getattr(CONF.database, 'connection', None) or _build_url()
            ssl_args = _build_ssl_args()
            _ENGINE = create_engine(
                url,
                poolclass=QueuePool,
                pool_size=CONF.database.pool_size,
                max_overflow=CONF.database.pool_max_overflow,
                pool_timeout=CONF.database.pool_timeout,
                pool_recycle=CONF.database.pool_recycle,
                pool_pre_ping=True,
                connect_args=ssl_args,
            )

        _register_pool_events(_ENGINE)

    return _ENGINE


def _build_url():
    """Build a SQLAlchemy URL using URL.create() so that passwords containing
    special characters (@, :, /, ?) are percent-encoded and never appear in
    log output.

    Password priority:
      1. CONF.database.password (zvmsdk.conf [database] password=...)
      2. ZVMSDK_DB_PASSWORD environment variable (preferred for production —
         avoids storing credentials in config files)
    The password value is never written to any log.
    """
    password = (getattr(CONF.database, 'password', '') or
                os.environ.get('ZVMSDK_DB_PASSWORD', ''))
    return URL.create(
        drivername='mysql+pymysql',
        username=CONF.database.user,
        password=password,
        host=CONF.database.host,
        port=int(CONF.database.port),
        database=CONF.database.name,
        query={'charset': 'utf8mb4'},
    )


def _build_ssl_args():
    """Build the connect_args ssl dict for PyMySQL.

    Only include keys whose values are non-None — PyMySQL raises TypeError on
    None values in the ssl dict and may silently disable TLS if they are present.
    """
    ssl_ca = getattr(CONF.database, 'ssl_ca', None)
    ssl_cert = getattr(CONF.database, 'ssl_cert', None)
    ssl_key = getattr(CONF.database, 'ssl_key', None)
    if not ssl_ca:
        return {}
    ssl_dict = {'ca': ssl_ca}
    if ssl_cert:
        ssl_dict['cert'] = ssl_cert
    if ssl_key:
        ssl_dict['key'] = ssl_key
    return {'ssl': ssl_dict}


def _register_pool_events(engine):
    """Register SQLAlchemy pool event listeners for connection tracking (9.1).

    Increments module-level counters on checkout, checkin, and invalidation
    so callers can retrieve live pool statistics via get_pool_status().
    """
    global _POOL_CHECKED_OUT, _POOL_CHECKED_IN, _POOL_INVALIDATED

    @event.listens_for(engine, 'checkout')
    def _on_checkout(dbapi_conn, conn_record, conn_proxy):
        global _POOL_CHECKED_OUT
        _POOL_CHECKED_OUT += 1

    @event.listens_for(engine, 'checkin')
    def _on_checkin(dbapi_conn, conn_record):
        global _POOL_CHECKED_IN
        _POOL_CHECKED_IN += 1

    @event.listens_for(engine, 'invalidate')
    def _on_invalidate(dbapi_conn, conn_record, exception):
        global _POOL_INVALIDATED
        _POOL_INVALIDATED += 1


def get_pool_status():
    """Return a snapshot of connection pool statistics.

    For QueuePool (MariaDB/MySQL) returns pool_size, checked_out, overflow and
    lifetime counters.  For StaticPool (SQLite) returns only lifetime counters
    since the pool holds at most one connection.

    Returns {} when the engine has not been initialised yet.
    """
    engine = _ENGINE
    if engine is None:
        return {}
    pool = engine.pool
    base = {
        'backend': getattr(CONF.database, 'backend', 'sqlite'),
        'lifetime_checked_out': _POOL_CHECKED_OUT,
        'lifetime_checked_in': _POOL_CHECKED_IN,
        'lifetime_invalidated': _POOL_INVALIDATED,
    }
    if isinstance(pool, QueuePool):
        base.update({
            'pool_size': pool.size(),
            'checked_out': pool.checkedout(),
            'overflow': pool.overflow(),
        })
    return base


@contextlib.contextmanager
def get_connection():
    """Thread-safe, reentrant context manager yielding a SQLAlchemy connection.

    Reentrant: if a connection is already active in this thread (e.g., an
    outer method holds a transaction and calls inner helpers that also call
    get_connection()), the same connection object is yielded.  The transaction
    is committed/rolled-back only when the outermost get_connection() block
    exits.  This mirrors the old RLock + shared sqlite3.Connection pattern.
    """
    existing = getattr(_CONN_LOCAL, 'conn', None)
    if existing is not None:
        yield existing
    else:
        with get_engine().begin() as conn:
            _CONN_LOCAL.conn = conn
            try:
                yield conn
            finally:
                _CONN_LOCAL.conn = None


def verify_remote_connectivity():
    """Verify the remote DB is reachable at startup. No-op in local mode."""
    mode = getattr(CONF.database, 'mode', 'local')
    if mode != 'remote':
        return
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        LOG.info("Remote database connectivity verified.")
    except Exception as e:
        raise exception.SDKInternalError(
            msg="Cannot connect to remote database: %s" % str(e))


def register_compute_node():
    """UPSERT this node into compute_nodes on startup."""
    node_id = get_compute_node_id()
    hostname = socket.gethostname()
    ip = getattr(CONF.network, 'my_ip', '') or ''
    dialect = get_engine().dialect.name
    with get_connection() as conn:
        if dialect in ('mysql', 'mariadb'):
            conn.execute(text("""
                INSERT INTO compute_nodes (id, hostname, ip_address, status, last_seen)
                VALUES (:id, :hostname, :ip, 'active', NOW())
                ON DUPLICATE KEY UPDATE
                    last_seen = NOW(),
                    status = 'active',
                    hostname = VALUES(hostname),
                    ip_address = VALUES(ip_address)
            """), {'id': node_id, 'hostname': hostname, 'ip': ip})
        else:
            conn.execute(text("""
                INSERT OR REPLACE INTO compute_nodes
                    (id, hostname, ip_address, status, last_seen)
                VALUES (:id, :hostname, :ip, 'active', datetime('now'))
            """), {'id': node_id, 'hostname': hostname, 'ip': ip})
    LOG.info("Registered compute node '%s' in database.", node_id)


def deregister_compute_node():
    """Mark this node inactive on clean shutdown."""
    node_id = get_compute_node_id()
    if not node_id:
        return
    dialect = get_engine().dialect.name
    try:
        with get_connection() as conn:
            if dialect in ('mysql', 'mariadb'):
                conn.execute(
                    text("UPDATE compute_nodes SET status='inactive',"
                         " last_seen=NOW() WHERE id=:id"),
                    {'id': node_id})
            else:
                conn.execute(
                    text("UPDATE compute_nodes SET status='inactive',"
                         " last_seen=datetime('now') WHERE id=:id"),
                    {'id': node_id})
        LOG.info("Deregistered compute node '%s'.", node_id)
    except Exception as e:
        LOG.warning("Failed to deregister compute node '%s': %s", node_id, e)


# ---------------------------------------------------------------------------
# 9.3 — Stale node health-check
# ---------------------------------------------------------------------------

def _mark_stale_nodes_inactive(threshold_seconds=300):
    """UPDATE compute_nodes: set status='inactive' for nodes not seen recently.

    A node is considered stale when its last_seen timestamp is older than
    *threshold_seconds* seconds and its status is still 'active'.  This catches
    nodes that crashed without calling deregister_compute_node().

    Dialect-aware: MariaDB uses INTERVAL arithmetic; SQLite uses datetime().
    """
    dialect = get_engine().dialect.name
    with get_connection() as conn:
        if dialect in ('mysql', 'mariadb'):
            conn.execute(
                text("UPDATE compute_nodes SET status='inactive' "
                     "WHERE last_seen < NOW() - INTERVAL :s SECOND "
                     "AND status='active'"),
                {'s': threshold_seconds})
        else:
            conn.execute(
                text("UPDATE compute_nodes SET status='inactive' "
                     "WHERE last_seen < datetime('now', :offset) "
                     "AND status='active'"),
                {'offset': '-%d seconds' % threshold_seconds})


def check_stale_nodes(threshold_seconds=300):
    """Mark stale compute nodes inactive; swallows errors so startup is safe.

    Call this at service startup (after ensure_schema_current()) to clean up
    entries from nodes that previously crashed without deregistering.
    threshold_seconds defaults to 300 (5 minutes).
    """
    try:
        _mark_stale_nodes_inactive(threshold_seconds)
        LOG.info("Stale node check complete (threshold: %ds).", threshold_seconds)
    except Exception as e:
        LOG.warning("Stale node check failed (non-fatal): %s", e)
