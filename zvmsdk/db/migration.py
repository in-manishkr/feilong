#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

import os
import threading

from sqlalchemy.engine import URL

from zvmsdk import config
from zvmsdk import log

CONF = config.CONF
LOG = log.LOG

# Serialise concurrent calls from different threads in the same process.
# Alembic creates its own NullPool connection to the SQLite file; without this
# lock two threads calling ensure_schema_current() simultaneously race on the
# alembic_version table and can crash (SQLite) or produce duplicate DDL errors
# (MariaDB).  The fast path (schema already at head) returns in microseconds so
# the serialisation overhead is negligible in practice.
_MIGRATION_LOCK = threading.Lock()


def _get_alembic_ini_path():
    """Return path to alembic.ini.

    Checked in order:
      1. CONF.database.alembic_config — operator-specified override
      2. <package_dir>/alembic/alembic.ini — default installed location
    """
    configured = getattr(CONF.database, 'alembic_config', None)
    if configured and os.path.isfile(configured):
        return configured
    # zvmsdk/db/migration.py → parent → zvmsdk/db → parent → zvmsdk →
    # parent → repo root (or installed package).  The alembic directory
    # lives at zvmsdk/db/alembic/ relative to this file.
    pkg_dir = os.path.dirname(os.path.abspath(__file__))  # zvmsdk/db/
    default = os.path.join(pkg_dir, 'alembic', 'alembic.ini')
    return default


def _get_db_url_str():
    """Return the DB connection URL as a plain string for alembic consumption."""
    backend = getattr(CONF.database, 'backend', 'sqlite')
    if backend == 'sqlite':
        return 'sqlite:///%s' % os.path.join(CONF.database.dir, 'zvmsdk.db')
    conn = getattr(CONF.database, 'connection', None)
    if conn:
        return conn
    url = URL.create(
        drivername='mysql+pymysql',
        username=CONF.database.user,
        password=CONF.database.password,
        host=CONF.database.host,
        port=int(CONF.database.port),
        database=CONF.database.name,
        query={'charset': 'utf8mb4'},
    )
    # render_as_string(hide_password=False) is required — str(url) in
    # SQLAlchemy 2.x hides the password behind '***'.
    return url.render_as_string(hide_password=False)


def _stamp_mariadb_if_fresh(cfg):
    """Stamp revision 0001 on a fresh MariaDB so upgrade('head') skips the
    SQLite-specific NOCASE baseline and goes straight to 0002.

    Does nothing if alembic_version already exists (existing or already-stamped
    MariaDB installation).
    """
    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    url = _get_db_url_str()
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            try:
                conn.execute(text(
                    "SELECT version_num FROM alembic_version LIMIT 1"))
                return  # alembic_version already exists
            except Exception:  # nosec B110 — intentional: table absent = fresh DB
                pass
    finally:
        engine.dispose()

    LOG.info("Fresh MariaDB detected — stamping baseline revision 0001.")
    command.stamp(cfg, '0001')


def ensure_schema_current():
    """Upgrade the schema to HEAD using alembic.

    Called at service startup. On a fresh database this creates all tables;
    on an existing database it applies only pending migrations.  Idempotent.
    Thread-safe: a module-level lock serialises concurrent calls so that
    parallel startup threads don't race on the alembic_version table.
    """
    with _MIGRATION_LOCK:
        from alembic import command
        from alembic.config import Config

        alembic_ini = _get_alembic_ini_path()
        LOG.info("Running alembic upgrade head (config: %s)", alembic_ini)
        cfg = Config(alembic_ini)
        # Inject the runtime URL so env.py does not need to parse zvmsdk.conf.
        cfg.set_main_option('sqlalchemy.url', _get_db_url_str())

        backend = getattr(CONF.database, 'backend', 'sqlite')
        if backend in ('mariadb', 'mysql'):
            _stamp_mariadb_if_fresh(cfg)

        command.upgrade(cfg, 'head')
        LOG.info("Schema is up to date.")


def downgrade(target='base'):
    """Downgrade to *target* revision (default: base = drop everything).

    Only used during testing and data-migration rollback scenarios.
    """
    from alembic import command
    from alembic.config import Config

    alembic_ini = _get_alembic_ini_path()
    cfg = Config(alembic_ini)
    cfg.set_main_option('sqlalchemy.url', _get_db_url_str())
    command.downgrade(cfg, target)
