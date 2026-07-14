# Proposed Architecture: SQLite3 → MariaDB/MySQL Migration for Feilong (z/VM Cloud Connector)

## 1. Executive Summary

This document describes the architecture for migrating feilong's embedded SQLite3 databases to
MariaDB/MySQL, supporting both **local mode** (one DB per compute node, current behavior) and
**remote/centralized mode** (all compute nodes share one DB on the management/controller node).
The migration uses **SQLAlchemy Core** for the database abstraction layer and **Alembic** for
schema versioning.

---

## 2. Current State

### 2.1 Database Files

| Constant              | File                 | Operator            |
|-----------------------|----------------------|---------------------|
| `DATABASE_NETWORK`    | `sdk_network.sqlite` | `NetworkDbOperator` |
| `DATABASE_IMAGE`      | `sdk_image.sqlite`   | `ImageDbOperator`   |
| `DATABASE_GUEST`      | `sdk_guest.sqlite`   | `GuestDbOperator`   |
| `DATABASE_FCP`        | `sdk_fcp.sqlite`     | `FCPDbOperator`     |
| `DATABASE_VOLUME`     | `sdk_volume.sqlite`  | *(constant declared in `constants.py` but no operator, connection, or table body uses it — no volume DB exists in practice; excluded from this migration)* |

### 2.2 Current Tables

**switch** (network)
```
userid varchar(8), interface varchar(4), switch varchar(8),
port varchar(128), comments varchar(128)
PK: (userid, interface)
```

**guests**
```
id char(36) PK, userid varchar(8) UNIQUE, metadata varchar(255),
net_set smallint DEFAULT 0, comments text
```

**image**
```
imagename varchar(128) PK, imageosdistro varchar(16), md5sum varchar(512),
disk_size_units varchar(512), image_size_in_bytes varchar(512),
type varchar(16), comments varchar(128)
```

**fcp**
```
fcp_id char(4) PK, assigner_id varchar(8), connections integer,
reserved integer, wwpn_npiv varchar(16), wwpn_phy varchar(16),
chpid char(2), pchid char(4), state varchar(8), owner varchar(8), tmpl_id varchar(32)
```

**template**, **template_sp_mapping**, **template_fcp_mapping**
(FCP Multipath Template tables — see `database.py:FCPDbOperator._initialize_table`)

### 2.3 Current Limitations

- **No multi-node**: each z/VM node owns its own SQLite files; no shared state.
- **Per-DB thread locks**: `threading.RLock()` per connection — does not scale across processes.
- **SQLite-specific constructs**: `COLLATE NOCASE`, `sqlite3.Row`, `conn.in_transaction`,
  `executemany` with raw tuples, `IS NOT ''` comparisons.
- **No migration framework**: schema changes require manual DDL.
- **No connection pooling**: single persistent connection per database file.

---

## 3. Deployment Topologies

### 3.1 Local Mode (default — backward compatible)

```
┌─────────────────────────────────┐
│  Compute Node (z/VM host A)     │
│                                 │
│  feilong (zvmsdk) ──────────►  MariaDB/MySQL (localhost)  │
│                                 │  Database: zvmsdk        │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│  Compute Node (z/VM host B)     │
│                                 │
│  feilong (zvmsdk) ──────────►  MariaDB/MySQL (localhost)  │
│                                 │  Database: zvmsdk        │
└─────────────────────────────────┘
```

Behavior is identical to current SQLite: each node is fully independent, `compute_node_id` is
not used in queries (only stored for observability).

### 3.2 Remote/Centralized Mode (new — multi-node OpenStack)

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenStack Controller / Management Node                         │
│                                                                 │
│  ┌──────────────────────────────────────────┐                  │
│  │  MariaDB/MySQL (centralized)              │                  │
│  │  Database: zvmsdk                         │                  │
│  │  User: zvmsdk_user (per-node or shared)   │                  │
│  └──────────────────────────────────────────┘                  │
│                 ▲              ▲              ▲                  │
└─────────────────┼──────────────┼──────────────┼─────────────────┘
                  │  TLS/SSL     │              │
     ┌────────────┘      ┌───────┘      ┌───────┘
     │                   │              │
┌────┴────────┐  ┌────────┴────┐  ┌────┴────────┐
│ Compute A   │  │ Compute B   │  │ Compute C   │
│ feilong     │  │ feilong     │  │ feilong     │
│ node_id=A   │  │ node_id=B   │  │ node_id=C   │
└─────────────┘  └─────────────┘  └─────────────┘
```

All compute nodes write/read to/from the centralized DB.  A `compute_node_id` column on all
node-specific tables scopes each row to its originating node.

---

## 4. Tech Stack

| Component          | Choice                     | Rationale                                                      |
|--------------------|----------------------------|----------------------------------------------------------------|
| Database           | MariaDB ≥ 10.6 / MySQL ≥ 8.0 | Production-grade, OpenStack-native, ACID, replication          |
| DB Abstraction     | **SQLAlchemy Core 2.x**    | Matches existing raw-SQL style; avoids ORM overhead; dialect-agnostic |
| Migrations         | **Alembic**                | Industry standard; integrates with SQLAlchemy; supports offline mode |
| Python Driver      | `PyMySQL` (pure Python)    | No C extension; works on s390x; compatible with SQLAlchemy     |
| Fallback Driver    | `mysqlclient` (libmysqlclient) | Higher performance if C extensions available on target arch   |
| Connection Pooling | SQLAlchemy `QueuePool`     | Built-in; thread-safe; configurable                            |
| SSL/TLS            | `PyMySQL` SSL args         | Required for remote mode security                              |
| Config             | Existing `zvmsdk.conf`     | Add new options under `[database]` section                     |

> **Why SQLAlchemy Core instead of ORM?**
> The existing code has ~2,600 lines of hand-written SQL with raw tuple binding. SQLAlchemy Core
> provides dialect translation and connection pooling without requiring a rewrite to ORM-style
> models, preserving the existing logic.

> **Why not keep raw `sqlite3` + add MariaDB support separately?**
> SQLAlchemy abstracts `?` vs `%s` placeholder syntax, `AUTOINCREMENT` vs `AUTO_INCREMENT`,
> boolean storage differences, and `COLLATE` differences — all of which differ between SQLite
> and MariaDB/MySQL.

---

## 5. Schema Changes

### 5.1 `compute_nodes` Registry Table (new)

Tracks all registered compute nodes. Populated on feilong startup.

```sql
CREATE TABLE IF NOT EXISTS compute_nodes (
    id           VARCHAR(64)  NOT NULL,          -- e.g. hostname or UUID
    hostname     VARCHAR(255) NOT NULL,
    ip_address   VARCHAR(45)  NOT NULL,          -- supports IPv6
    zvm_host     VARCHAR(255),                   -- z/VM hypervisor LPAR name
    registered_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status       VARCHAR(16)  NOT NULL DEFAULT 'active',  -- active|inactive
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
```

### 5.2 Adding `compute_node_id` to Existing Tables

All node-scoped tables receive a `compute_node_id` column in **both modes**. The FK to
`compute_nodes` is only enforced in remote mode (see FK strategy below).

| Table                  | `compute_node_id` role                         |
|------------------------|------------------------------------------------|
| `switch`               | Scopes NIC/switch records to a node            |
| `guests`               | Scopes guest VMs to a node                     |
| `fcp`                  | Scopes FCP devices to a node                   |
| `template`             | Scopes FCP templates to a node                 |
| `template_sp_mapping`  | Scopes SP-template mappings to a node          |
| `template_fcp_mapping` | Scopes FCP-template-path mappings to a node    |

The `image` table is **global by default** (images may be shared across nodes via a shared
repository). A `compute_node_id` column is added as `NOT NULL DEFAULT 'GLOBAL'` so the PK
can be expanded to `(imagename, compute_node_id)` to prevent name collisions in remote mode
when two nodes each have a same-named local image.

> **FK strategy — local vs. remote mode**
>
> In local mode `compute_node_id` defaults to `''` (empty string). Adding a FK
> `REFERENCES compute_nodes(id)` in local mode would immediately break every INSERT because
> there is no `compute_nodes` row with `id = ''`.
>
> **Fix**: FK constraints from data tables to `compute_nodes` are **omitted from the base DDL**
> and added by the Alembic `0003_add_compute_node_support.py` migration **only when
> `mode = remote`**. In local mode the column is stored and indexed but unconstrained. The
> `register_compute_node()` call at startup (§12.4) is still executed in both modes so
> `compute_nodes` is always populated, but the FK enforcement is deferred to remote mode.

**Example: updated `fcp` table**
```sql
-- Base DDL (both local and remote mode) — no FK yet
CREATE TABLE IF NOT EXISTS fcp (
    fcp_id          CHAR(4)      NOT NULL,
    compute_node_id VARCHAR(64)  NOT NULL DEFAULT '',
    assigner_id     VARCHAR(8)   NOT NULL DEFAULT '',
    connections     INT          NOT NULL DEFAULT 0,
    reserved        INT          NOT NULL DEFAULT 0,
    wwpn_npiv       VARCHAR(16)  NOT NULL DEFAULT '',
    wwpn_phy        VARCHAR(16)  NOT NULL DEFAULT '',
    chpid           CHAR(2)      NOT NULL DEFAULT '',
    pchid           CHAR(4)      NOT NULL DEFAULT '',
    state           VARCHAR(8)   NOT NULL DEFAULT '',
    owner           VARCHAR(8)   NOT NULL DEFAULT '',
    tmpl_id         VARCHAR(32)  NOT NULL DEFAULT '',
    PRIMARY KEY (fcp_id, compute_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Added by 0003 migration ONLY when mode=remote
ALTER TABLE fcp
    ADD CONSTRAINT fk_fcp_node
    FOREIGN KEY (compute_node_id) REFERENCES compute_nodes(id) ON DELETE CASCADE;
```

> **PK change**: The primary key expands from `(fcp_id)` to `(fcp_id, compute_node_id)` so two
> nodes can each have an FCP device with the same ID.

**Updated `switch` table**
```sql
-- Base DDL (no FK)
CREATE TABLE IF NOT EXISTS switch (
    userid          VARCHAR(8)   NOT NULL,
    interface       VARCHAR(4)   NOT NULL,
    compute_node_id VARCHAR(64)  NOT NULL DEFAULT '',
    switch          VARCHAR(8),
    port            VARCHAR(128),
    comments        VARCHAR(128),
    PRIMARY KEY (userid, interface, compute_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Added by 0003 migration ONLY when mode=remote
ALTER TABLE switch
    ADD CONSTRAINT fk_switch_node
    FOREIGN KEY (compute_node_id) REFERENCES compute_nodes(id) ON DELETE CASCADE;
```

**Updated `guests` table**
```sql
-- Base DDL (no FK)
CREATE TABLE IF NOT EXISTS guests (
    id              CHAR(36)     NOT NULL,
    userid          VARCHAR(8)   NOT NULL,
    compute_node_id VARCHAR(64)  NOT NULL DEFAULT '',
    metadata        VARCHAR(255),
    net_set         SMALLINT     NOT NULL DEFAULT 0,
    comments        TEXT,
    PRIMARY KEY (id),
    UNIQUE KEY uq_guests_userid_node (userid, compute_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Added by 0003 migration ONLY when mode=remote
ALTER TABLE guests
    ADD CONSTRAINT fk_guests_node
    FOREIGN KEY (compute_node_id) REFERENCES compute_nodes(id) ON DELETE CASCADE;
```

**Updated `image` table**
```sql
-- imagename alone is no longer sufficient as PK in remote mode when two nodes can have
-- a same-named local image. PK is expanded to (imagename, compute_node_id).
-- 'GLOBAL' sentinel value indicates a shared/global image not tied to any node.
CREATE TABLE IF NOT EXISTS image (
    imagename           VARCHAR(128) NOT NULL,
    compute_node_id     VARCHAR(64)  NOT NULL DEFAULT 'GLOBAL',
    imageosdistro       VARCHAR(16),
    md5sum              VARCHAR(512),
    disk_size_units     VARCHAR(512),
    image_size_in_bytes VARCHAR(512),
    type                VARCHAR(16),
    comments            VARCHAR(128),
    PRIMARY KEY (imagename, compute_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
```

### 5.3 SQLite → MariaDB/MySQL Compatibility Map

| SQLite construct                  | MariaDB/MySQL equivalent                             |
|-----------------------------------|------------------------------------------------------|
| `COLLATE NOCASE`                  | Column-level `COLLATE utf8mb4_general_ci` (case-insensitive) |
| `integer` for booleans            | `TINYINT(1)` or `BOOLEAN`                           |
| `sqlite3.Row` (dict-style access) | SQLAlchemy `Row` (same interface via `._mapping`)   |
| `conn.in_transaction`             | SQLAlchemy `connection.get_transaction()` / context mgr |
| `conn.executemany(...)`           | SQLAlchemy `conn.execute(stmt, list_of_dicts)`      |
| `IS NOT ''`                       | `<> ''` or `!= ''`                                  |
| `BEGIN` / `COMMIT` / `ROLLBACK`   | SQLAlchemy transaction context manager              |
| Positional `?` placeholders       | `%s` (PyMySQL) — abstracted by SQLAlchemy           |
| `isolation_level=None`            | `autocommit=True` (handled per context)             |

---

## 6. New Configuration Options

Add to `zvmsdk.conf` under the `[database]` section:

```ini
[database]
# --- Existing ---
dir = /var/lib/zvmsdk/databases/     # used only when backend=sqlite

# --- New ---

# backend: which database engine to use
# Values: sqlite (default, backward compatible), mariadb, mysql
backend = sqlite

# mode: local (each node has its own DB) or remote (shared centralized DB)
# Values: local, remote
mode = local

# SQLAlchemy connection URL — if set, overrides host/port/user/password/name
# Examples:
#   mysql+pymysql://zvmsdk:pass@db-host:3306/zvmsdk?charset=utf8mb4
#   mysql+pymysql://zvmsdk:pass@db-host:3306/zvmsdk?ssl_ca=/etc/zvmsdk/ca.pem
# connection =

# Individual connection parameters (used when 'connection' is not set)
host     = 127.0.0.1
port     = 3306
name     = zvmsdk
user     = zvmsdk
password =

# compute_node_id: unique identifier for this compute node.
#
# AUTO-DETECTION (no need to set this manually in most cases):
#   On z/VM guests: auto-detected as "<vmcp_userid>@<zvm_system>"
#                   using the existing utils.get_smt_userid() / get_zvm_name()
#                   e.g. "IAAS01EF@BOEM5401"
#   On non-z/VM:    falls back to CONF.network.my_ip (already required config)
#                   e.g. "10.0.0.5"
#
# Set this explicitly to override auto-detection, e.g. when:
#   - Running behind a NAT (my_ip fallback would not be unique)
#   - You want a stable human-readable name regardless of IP changes
#
# Resolution priority:
#   1. This config value (if set)
#   2. vmcp query userid  -> "<userid>@<zvm_system>"  (z/VM guests only)
#   3. CONF.network.my_ip (always available, already required)
#
# compute_node_id =

# Connection pool settings
pool_size         = 5       # number of persistent connections
pool_max_overflow = 10      # connections beyond pool_size allowed under load
pool_timeout      = 30      # seconds to wait for a connection from the pool
pool_recycle      = 3600    # seconds before a connection is recycled (avoid stale)

# Path to alembic.ini used for schema migrations.
# Defaults to the alembic.ini bundled with the installed package.
# alembic_config = /etc/zvmsdk/alembic.ini

# SSL/TLS for remote connections
# ssl_ca   =   # path to CA certificate (e.g. /etc/zvmsdk/ssl/ca-cert.pem)
# ssl_cert =   # path to client certificate
# ssl_key  =   # path to client private key
```

---

## 7. Code Architecture

### 7.1 Module Layout

```
zvmsdk/
├── database.py          # existing — operator classes, to be refactored
├── db/
│   ├── __init__.py
│   ├── api.py           # new: engine factory, get_engine(), get_session()
│   ├── models.py        # new: SQLAlchemy Table definitions (Core metadata)
│   └── migration.py     # new: Alembic helpers (run_migrations, check_head)
└── config.py            # existing — add new DB options

alembic/
├── alembic.ini
├── env.py
├── script.py.mako
└── versions/
    ├── 0001_initial_schema.py          # creates all tables for sqlite (backward compat)
    ├── 0002_mariadb_schema.py          # full MariaDB schema
    └── 0003_add_compute_node_id.py     # adds compute_node_id + compute_nodes table
```

### 7.2 Engine Factory (`zvmsdk/db/api.py`)

```python
import contextlib
import os
import threading

from sqlalchemy import create_engine, text, URL
from sqlalchemy.pool import QueuePool, StaticPool
from zvmsdk import config

CONF = config.CONF

_ENGINE = None
_ENGINE_LOCK = threading.Lock()   # guards double-init race on startup


def get_engine():
    global _ENGINE
    # Fast path — no lock needed once engine is built.
    if _ENGINE is not None:
        return _ENGINE
    # Slow path — only one thread creates the engine.
    with _ENGINE_LOCK:
        if _ENGINE is not None:        # re-check under lock
            return _ENGINE

        global _COMPUTE_NODE_ID
        _COMPUTE_NODE_ID = _resolve_compute_node_id()
        LOG.info("Feilong compute_node_id for this session: %s", _COMPUTE_NODE_ID)

        backend = getattr(CONF.database, 'backend', 'sqlite')
        mode    = getattr(CONF.database, 'mode',    'local')

        # Guard illegal combination: remote mode requires a networked backend.
        if mode == 'remote' and backend == 'sqlite':
            raise exception.SDKInternalError(
                msg="database.mode=remote requires backend=mariadb or backend=mysql, "
                    "not backend=sqlite")

        if backend == 'sqlite':
            db_path = os.path.join(CONF.database.dir, 'zvmsdk.db')
            _ENGINE = create_engine(
                f'sqlite:///{db_path}',
                connect_args={'check_same_thread': False},
                poolclass=StaticPool,   # single connection — matches current behavior
            )
        else:
            # mariadb or mysql
            url = getattr(CONF.database, 'connection', None) or _build_url()
            ssl_args = _build_ssl_args()
            _ENGINE = create_engine(
                url,
                poolclass=QueuePool,
                pool_size=CONF.database.pool_size,
                max_overflow=CONF.database.pool_max_overflow,
                pool_timeout=CONF.database.pool_timeout,
                pool_recycle=CONF.database.pool_recycle,
                pool_pre_ping=True,    # detects stale connections after network blips
                connect_args=ssl_args,
            )
    return _ENGINE


def _build_url():
    # Use URL.create() so passwords with special characters (@, :, /, ?) are
    # percent-encoded correctly and never appear in log output.
    return URL.create(
        drivername='mysql+pymysql',
        username=CONF.database.user,
        password=CONF.database.password,
        host=CONF.database.host,
        port=CONF.database.port,
        database=CONF.database.name,
        query={'charset': 'utf8mb4'},
    )


def _build_ssl_args():
    ssl_ca   = getattr(CONF.database, 'ssl_ca',   None)
    ssl_cert = getattr(CONF.database, 'ssl_cert', None)
    ssl_key  = getattr(CONF.database, 'ssl_key',  None)
    if not ssl_ca:
        return {}
    # Only include keys whose values are non-None; PyMySQL rejects None values
    # in the ssl dict and may silently disable TLS if they are present.
    ssl_dict = {'ca': ssl_ca}
    if ssl_cert:
        ssl_dict['cert'] = ssl_cert
    if ssl_key:
        ssl_dict['key'] = ssl_key
    return {'ssl': ssl_dict}


@contextlib.contextmanager
def get_connection():
    """Thread-safe context manager returning a SQLAlchemy connection.

    Uses engine.begin() (SQLAlchemy 2.x idiom) which:
      - auto-commits on successful block exit
      - auto-rolls back on any exception
    Do NOT call engine.connect() + conn.begin() — in SQLAlchemy 2.x the
    connection already has autobegin active, so a second begin() raises
    InvalidRequestError.
    """
    with get_engine().begin() as conn:
        yield conn
```

### 7.3 Table Definitions (`zvmsdk/db/models.py`)

```python
from sqlalchemy import (
    MetaData, Table, Column, String, Integer,
    SmallInteger, Text, DateTime, Boolean,
    PrimaryKeyConstraint, UniqueConstraint, ForeignKey,
    ForeignKeyConstraint, func
)

metadata = MetaData()

compute_nodes = Table('compute_nodes', metadata,
    Column('id',            String(64),  nullable=False),
    Column('hostname',      String(255), nullable=False),
    Column('ip_address',    String(45),  nullable=False),
    Column('zvm_host',      String(255)),
    Column('registered_at', DateTime,    server_default=func.now()),
    Column('last_seen',     DateTime,    server_default=func.now(), onupdate=func.now()),
    Column('status',        String(16),  nullable=False, server_default='active'),
    PrimaryKeyConstraint('id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

guests = Table('guests', metadata,
    Column('id',              String(36),  nullable=False),
    Column('userid',          String(8),   nullable=False),
    Column('compute_node_id', String(64),  nullable=False, server_default=''),
    Column('metadata',        String(255)),
    Column('net_set',         SmallInteger, nullable=False, server_default='0'),
    Column('comments',        Text),
    PrimaryKeyConstraint('id'),
    UniqueConstraint('userid', 'compute_node_id', name='uq_guests_userid_node'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

switch = Table('switch', metadata,
    Column('userid',          String(8),   nullable=False),
    Column('interface',       String(4),   nullable=False),
    Column('compute_node_id', String(64),  nullable=False, server_default=''),
    Column('switch',          String(8)),
    Column('port',            String(128)),
    Column('comments',        String(128)),
    PrimaryKeyConstraint('userid', 'interface', 'compute_node_id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

image = Table('image', metadata,
    Column('imagename',           String(128), nullable=False),
    Column('compute_node_id',     String(64),  nullable=False, server_default='GLOBAL'),
    Column('imageosdistro',       String(16)),
    Column('md5sum',              String(512)),
    Column('disk_size_units',     String(512)),
    Column('image_size_in_bytes', String(512)),
    Column('type',                String(16)),
    Column('comments',            String(128)),
    # PK is (imagename, compute_node_id) so two nodes can hold same-named local
    # images without colliding. 'GLOBAL' sentinel = shared/cross-node image.
    PrimaryKeyConstraint('imagename', 'compute_node_id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

fcp = Table('fcp', metadata,
    Column('fcp_id',          String(4),   nullable=False),
    Column('compute_node_id', String(64),  nullable=False, server_default=''),
    Column('assigner_id',     String(8),   nullable=False, server_default=''),
    Column('connections',     Integer,     nullable=False, server_default='0'),
    Column('reserved',        Integer,     nullable=False, server_default='0'),
    Column('wwpn_npiv',       String(16),  nullable=False, server_default=''),
    Column('wwpn_phy',        String(16),  nullable=False, server_default=''),
    Column('chpid',           String(2),   nullable=False, server_default=''),
    Column('pchid',           String(4),   nullable=False, server_default=''),
    Column('state',           String(8),   nullable=False, server_default=''),
    Column('owner',           String(8),   nullable=False, server_default=''),
    Column('tmpl_id',         String(32),  nullable=False, server_default=''),
    PrimaryKeyConstraint('fcp_id', 'compute_node_id'),
    # FK to compute_nodes is NOT declared here; it is added by the 0003 Alembic
    # migration only when mode=remote (see §5.2 FK strategy).
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

template = Table('template', metadata,
    Column('id',                  String(32),  nullable=False),
    Column('compute_node_id',     String(64),  nullable=False, server_default=''),
    Column('name',                String(128), nullable=False),
    Column('description',         String(255), nullable=False, server_default=''),
    Column('is_default',          Boolean,     nullable=False, server_default='0'),
    Column('min_fcp_paths_count', Integer,     nullable=False, server_default='-1'),
    PrimaryKeyConstraint('id', 'compute_node_id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

template_sp_mapping = Table('template_sp_mapping', metadata,
    Column('sp_name',         String(128), nullable=False),
    Column('tmpl_id',         String(32),  nullable=False),
    Column('compute_node_id', String(64),  nullable=False, server_default=''),
    PrimaryKeyConstraint('sp_name', 'compute_node_id'),
    # FK: each SP mapping must reference a real template on the same node.
    # Deleting a template cascades to remove its SP mappings.
    ForeignKeyConstraint(
        ['tmpl_id', 'compute_node_id'],
        ['template.id', 'template.compute_node_id'],
        ondelete='CASCADE',
        name='fk_sp_mapping_template',
    ),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

template_fcp_mapping = Table('template_fcp_mapping', metadata,
    Column('fcp_id',          String(4),  nullable=False),
    Column('tmpl_id',         String(32), nullable=False),
    Column('compute_node_id', String(64), nullable=False, server_default=''),
    Column('path',            Integer,    nullable=False),
    PrimaryKeyConstraint('fcp_id', 'tmpl_id', 'compute_node_id'),
    # FK to template: deleting a template removes its FCP path mappings.
    ForeignKeyConstraint(
        ['tmpl_id', 'compute_node_id'],
        ['template.id', 'template.compute_node_id'],
        ondelete='CASCADE',
        name='fk_fcp_mapping_template',
    ),
    # FK to fcp: ensures only real FCP devices are mapped.
    ForeignKeyConstraint(
        ['fcp_id', 'compute_node_id'],
        ['fcp.fcp_id', 'fcp.compute_node_id'],
        ondelete='CASCADE',
        name='fk_fcp_mapping_fcp',
    ),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)
```

### 7.4 Refactored Connection Managers in `database.py`

Replace the 5 separate `_NETWORK_CONN`, `_IMAGE_CONN`, etc. globals and
`threading.RLock()` instances with a single SQLAlchemy engine:

```python
# Old pattern (sqlite3) — kept for reference only, NOT for new code:
#
#   _DBLOCK_FCP.acquire()
#   try:
#       if not _FCP_CONN.in_transaction:   # sqlite3-specific
#           _FCP_CONN.execute("BEGIN")
#           skip_commit = False
#       else:
#           skip_commit = True             # nested re-entrant call
#       yield _FCP_CONN
#       if not skip_commit:
#           _FCP_CONN.execute("COMMIT")
#   except ...: _FCP_CONN.execute("ROLLBACK")
#   finally: _DBLOCK_FCP.release()
#
# SQLAlchemy's QueuePool is thread-safe; engine.begin() handles commit/rollback
# automatically; the nested-transaction (skip_commit) guard is no longer needed
# because callers should not share a connection across stack frames — each
# get_*_conn() call acquires its own connection from the pool.

# New pattern (SQLAlchemy):
@contextlib.contextmanager
def get_fcp_conn():
    from zvmsdk.db.api import get_connection
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        # Use SDKDatabaseException — not SDKGuestOperationError, which is
        # reserved for guest-lifecycle errors, not raw DB failures.
        raise exception.SDKDatabaseException(msg=msg)
```

The `threading.RLock()` per-DB is no longer needed: SQLAlchemy's `QueuePool` is thread-safe
and MariaDB/MySQL supports row-level locking natively.

### 7.5 `compute_node_id` — Resolution Strategy

#### Who sets it and when

`compute_node_id` is resolved **once at SDK startup**, inside `get_engine()` in `zvmsdk/db/api.py`,
before any DB operator is instantiated. No caller outside `db/api.py` needs to know how it was
derived — all operators simply call `get_compute_node_id()`.

```
SDK starts
  └─► load_config()
  └─► get_engine()          ← _resolve_compute_node_id() called here, result stored in module global
  └─► NetworkDbOperator()   ← uses get_compute_node_id() transparently
  └─► GuestDbOperator()
  └─► FCPDbOperator()
  └─► ...
```

#### Candidate sources and tradeoffs

| Priority | Source | Example value | Pros | Cons |
|----------|--------|---------------|------|------|
| 1 | `CONF.database.compute_node_id` (explicit) | `"my-node-A"` | Fully deterministic, operator-controlled | Extra admin burden on every install |
| 2 | `vmcp query userid` → `"USERID@ZVM_SYSTEM"` | `"IAAS01EF@BOEM5401"` | Semantically perfect for z/VM, stable, **already in `utils.py`** | Only works when feilong runs as a z/VM guest |
| 3 | `CONF.network.my_ip` (always-available fallback) | `"10.0.0.5"` | **Already a `required=True` config field** — zero extra admin work, unique per node | Less readable; IP can change (but so would `my_ip` in config anyway) |

`socket.gethostname()` is intentionally skipped: hostnames are not guaranteed unique across
deployments and can be changed without updating `zvmsdk.conf`, making them less reliable than
`my_ip` which the operator already consciously manages.

#### Why `CONF.network.my_ip` is the right last-resort default

`CONF.network.my_ip` is declared `required=True` in `config.py:317` — it is the one identifier
that is **always present** in every feilong deployment, is **unique per node** in any correctly
configured network, and requires **no additional admin action**. If an IP changes, the operator
already has to update `zvmsdk.conf`, at which point pinning `compute_node_id` explicitly is
straightforward.

#### Implementation

```python
# zvmsdk/db/api.py

_COMPUTE_NODE_ID = ''

def get_compute_node_id() -> str:
    return _COMPUTE_NODE_ID


def _resolve_compute_node_id() -> str:
    """
    Resolve this node's compute_node_id at startup. Called once from get_engine().

    Priority:
      1. CONF.database.compute_node_id  — explicit operator override
      2. vmcp query userid              — z/VM native: "USERID@ZVM_SYSTEM"
                                          uses existing utils.get_smt_userid() /
                                          utils.get_zvm_name() (utils.py:565)
      3. CONF.network.my_ip             — always available (required=True config field)
    """
    # Priority 1: explicit config
    explicit = getattr(CONF.database, 'compute_node_id', None)
    if explicit:
        LOG.info("compute_node_id set from config: %s", explicit)
        return explicit

    # Priority 2: vmcp query userid (z/VM guests only)
    # Output format: "IAAS01EF AT BOEM5401"
    # get_smt_userid() and get_zvm_name() both exec "sudo /sbin/vmcp query userid"
    # independently. Call it once here to avoid the double subprocess overhead.
    try:
        import subprocess
        out = subprocess.check_output(
            ["sudo", "/sbin/vmcp", "query", "userid"],
            close_fds=True, stderr=subprocess.STDOUT,
        )
        tokens = bytes.decode(out).split()   # ["IAAS01EF", "AT", "BOEM5401"]
        node_id = "%s@%s" % (tokens[0], tokens[-1])
        LOG.info("compute_node_id auto-detected via vmcp: %s", node_id)
        return node_id
    except Exception:
        # Not running on a z/VM guest — fall through silently
        pass

    # Priority 3: my_ip — always available since it is required=True in config
    node_id = CONF.network.my_ip
    LOG.info("compute_node_id auto-detected from my_ip: %s", node_id)
    return node_id


def get_engine():
    global _ENGINE, _COMPUTE_NODE_ID
    if _ENGINE is not None:
        return _ENGINE

    _COMPUTE_NODE_ID = _resolve_compute_node_id()
    LOG.info("Feilong compute_node_id for this session: %s", _COMPUTE_NODE_ID)

    # ... build engine (sqlite / mariadb) as described in section 7.2
```

#### Injection into DB operators

All DB operator methods that write node-scoped rows inject `compute_node_id` automatically.
No caller (API layer, vmops, networkops, etc.) ever needs to pass or know the node ID.

```python
# SQLAlchemy 2.x requires conn.execute() to receive a text() object with
# named :param placeholders — NOT a raw string with %s. Passing a bare string
# raises ObjectNotExecutableError at runtime.

from sqlalchemy import text

# GuestDbOperator.add_guest() — write path
def add_guest(self, userid, meta='', comments=''):
    guest_id = str(uuid.uuid4())
    node_id  = db_api.get_compute_node_id()
    with get_guest_conn() as conn:
        conn.execute(
            text(
                "INSERT INTO guests "
                "(id, userid, compute_node_id, metadata, net_set, comments) "
                "VALUES (:id, :userid, :node_id, :meta, :net_set, :comments)"
            ),
            {'id': guest_id, 'userid': userid, 'node_id': node_id,
             'meta': meta, 'net_set': 0, 'comments': comments}
        )

# GuestDbOperator.get_guest_by_userid() — read path (remote mode filters by node)
def get_guest_by_userid(self, userid):
    node_id = db_api.get_compute_node_id()
    with get_guest_conn() as conn:
        res = conn.execute(
            text("SELECT * FROM guests WHERE userid=:userid AND compute_node_id=:node_id"),
            {'userid': userid, 'node_id': node_id}
        )
```

In **local mode** (each node has its own DB), `compute_node_id` is stored in every row but
queries do **not** filter by it — since the database already belongs exclusively to that node,
the filter is redundant. This preserves backward-compatible query behavior while keeping the
schema consistent between modes.

---

## 8. Alembic Migration Strategy

### 8.1 Directory Structure

```
alembic/
├── alembic.ini               # points to CONF.database.connection
├── env.py                    # loads zvmsdk config to build DB URL
├── script.py.mako
└── versions/
    ├── 0001_initial_sqlite_baseline.py
    │   └── Creates all current tables (no compute_node_id) — baseline for existing installs
    ├── 0002_initial_mariadb.py
    │   └── Creates all tables in MariaDB-compatible DDL (utf8mb4, InnoDB)
    └── 0003_add_compute_node_support.py
        └── ALTER TABLE ... ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT ''
            CREATE TABLE compute_nodes (...)
            UPDATE ... SET compute_node_id = '<local-node-id>'  -- backfill
            ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT (expand PKs)
```

### 8.2 `alembic/env.py` skeleton

```python
from alembic import context
from zvmsdk import config as zvmconfig
from zvmsdk.db import models

zvmconfig.load_config()
CONF = zvmconfig.CONF

def get_url():
    backend = getattr(CONF.database, 'backend', 'sqlite')
    if backend == 'sqlite':
        return f"sqlite:///{CONF.database.dir}/zvmsdk.db"
    return (getattr(CONF.database, 'connection', None) or
            f"mysql+pymysql://{CONF.database.user}:{CONF.database.password}"
            f"@{CONF.database.host}:{CONF.database.port}/{CONF.database.name}")

def run_migrations_online():
    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=models.metadata,
        )
        with context.begin_transaction():
            context.run_migrations()
```

### 8.3 Startup Auto-Migration

On feilong startup, after config is loaded:

```python
# zvmsdk/db/migration.py
import importlib.resources
import os

def _get_alembic_ini_path():
    # Prefer an operator-supplied path via config, then fall back to the path
    # bundled inside the installed package so development installs and
    # non-standard deployments (/usr/local, virtualenvs) all work correctly.
    configured = getattr(CONF.database, 'alembic_config', None)
    if configured and os.path.isfile(configured):
        return configured
    # Package-relative path (works for editable installs and wheel installs alike)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg_dir, 'alembic', 'alembic.ini')


def ensure_schema_current():
    """Run any pending Alembic migrations on startup.

    Multi-node remote mode note: if several compute nodes restart simultaneously
    they will all call upgrade('head') concurrently against the shared DB.
    Alembic holds an advisory lock (via its version table) so only one runner
    executes migrations at a time; others wait and then find they are already at
    head. However, because MySQL/MariaDB DDL statements auto-commit and cannot
    be rolled back (unlike PostgreSQL), a migration that fails mid-way leaves
    the schema in a partially altered state. Mitigation:
      1. Always test migrations on a staging DB before rolling to production.
      2. Document a manual rollback procedure for each migration in its module
         docstring (the reverse ALTER TABLE / DROP statements to run by hand).
      3. Consider running migrations from a single designated node or an
         operator pre-upgrade step rather than from every node simultaneously.
    """
    from alembic import command
    from alembic.config import Config
    alembic_cfg = Config(_get_alembic_ini_path())
    command.upgrade(alembic_cfg, 'head')
```

Add the optional config key to `zvmsdk.conf`:

```ini
[database]
# Path to alembic.ini; defaults to the file bundled with the package.
# alembic_config = /etc/zvmsdk/alembic.ini
```

This allows zero-downtime schema updates — operators can upgrade the feilong package and the
next restart applies any pending migrations automatically.

---

## 9. Remote Database Setup

### 9.1 Management Node: Database and User Provisioning

Run once on the management node before deploying compute nodes:

```sql
-- Create the shared database
CREATE DATABASE IF NOT EXISTS zvmsdk
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

-- Create a shared service user (used by all compute nodes)
CREATE USER IF NOT EXISTS 'zvmsdk'@'%' IDENTIFIED BY '<strong-password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
    ON zvmsdk.* TO 'zvmsdk'@'%';

-- (Optional) Per-compute-node users for tighter access control
-- CREATE USER 'zvmsdk_nodeA'@'10.0.0.1' IDENTIFIED BY '<password-A>';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON zvmsdk.* TO 'zvmsdk_nodeA'@'10.0.0.1';

FLUSH PRIVILEGES;
```

### 9.2 Connectivity Verification on Startup

Before the SDK serves any requests, it should validate the remote DB connection:

```python
# zvmsdk/db/api.py
def verify_remote_connectivity():
    """Called at startup in remote mode. Raises if DB is unreachable."""
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
```

### 9.3 SSL/TLS for Remote Connections

All remote connections **should** use TLS to protect credentials and data in transit:

```ini
[database]
ssl_ca   = /etc/zvmsdk/ssl/ca-cert.pem
ssl_cert = /etc/zvmsdk/ssl/client-cert.pem
ssl_key  = /etc/zvmsdk/ssl/client-key.pem
```

On the MariaDB server:
```ini
# /etc/mysql/mariadb.conf.d/50-server.cnf
[mysqld]
ssl-ca   = /etc/mysql/ssl/ca-cert.pem
ssl-cert = /etc/mysql/ssl/server-cert.pem
ssl-key  = /etc/mysql/ssl/server-key.pem
require_secure_transport = ON
```

### 9.4 Firewall / Network Requirements

| Source           | Destination          | Port | Protocol |
|------------------|----------------------|------|----------|
| Compute node IP  | Management node IP   | 3306 | TCP      |

The port should be restricted to only the known compute node IP ranges, not open to the internet.

---

## 10. Data Migration (SQLite → MariaDB)

A migration utility script should be provided:

```
tools/migrate_sqlite_to_mariadb.py
```

**Steps the script performs:**

1. Locate all five existing SQLite files in `CONF.database.dir`:
   `sdk_network.sqlite`, `sdk_guest.sqlite`, `sdk_image.sqlite`,
   `sdk_fcp.sqlite`. (`sdk_volume.sqlite` is declared in constants but
   has no operator or table — skip it.)
2. Connect to each SQLite file individually (they are separate DBs, not one
   consolidated file). Open each with `sqlite3.connect()`.
3. Connect to the target MariaDB using the new `[database]` config.
4. Run Alembic migrations to ensure the MariaDB schema is at head.
5. For each source SQLite DB and each of its tables, read all rows and INSERT
   into the corresponding MariaDB table, injecting `compute_node_id` into every
   row.
6. Verify row counts per table match between source and destination.
7. Print a summary report.

> **SQLite consolidation note**: The existing deployment uses **5 separate SQLite
> files** (`sdk_network.sqlite`, etc.). The new SQLite path (`backend=sqlite`)
> uses a single consolidated `zvmsdk.db`. Users upgrading within SQLite mode
> (without switching to MariaDB) must still run this script with
> `--target-backend sqlite` to copy their data from the 5 old files into the
> new unified file before restarting feilong.

**Example:**
```bash
# Migrate from 5 SQLite files to MariaDB
python tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --compute-node-id compute-node-A \
    --config /etc/zvmsdk/zvmsdk.conf

# Consolidate 5 old SQLite files into the new single zvmsdk.db (SQLite → SQLite)
python tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --target-backend sqlite \
    --compute-node-id compute-node-A \
    --config /etc/zvmsdk/zvmsdk.conf
```

---

## 11. Backward Compatibility

- `backend = sqlite` remains the default. Existing deployments need no changes.
- When `backend = sqlite`, the new code behaves identically to the current implementation,
  using SQLAlchemy's SQLite dialect with a `StaticPool` (single connection, same as now).
- The `compute_node_id` column in SQLite mode is populated but never used to filter queries
  (since each node has its own DB file).
- The existing `CONF.database.dir` option continues to work for SQLite mode.

---

## 12. OpenStack Integration Considerations

### 12.1 OpenStack nova-compute + z/VM Driver (python-zvm-sdk)

The `python-zvm-sdk` OpenStack driver (os-vif, nova.virt.zvm) calls feilong's REST API.
From the driver's perspective, feilong is a black box. The DB migration is transparent to
nova-compute — no OpenStack configuration changes are needed.

### 12.2 DB Credential Management

In an OpenStack environment, secrets should be managed via:
- **oslo.config** (if feilong integrates with oslo) — use `oslo_config.cfg.StrOpt(secret=True)`
- **Barbican** (OpenStack Key Manager) for production secrets
- **Environment variables** as a fallback (read `ZVMSDK_DB_PASSWORD` if `password` is unset)

### 12.3 High Availability for the Remote DB

For production multi-node OpenStack deployments, the centralized MariaDB should be HA:

| HA Option               | Notes                                                       |
|-------------------------|-------------------------------------------------------------|
| MariaDB Galera Cluster  | Synchronous multi-master; native OpenStack deployment       |
| MariaDB Replication     | Async primary-replica; use ProxySQL for transparent failover|
| MySQL InnoDB Cluster    | Built-in HA with MySQL Router for connection routing        |

Feilong's SQLAlchemy engine should set `pool_pre_ping=True` to detect dead connections:

```python
_ENGINE = create_engine(url, pool_pre_ping=True, ...)
```

### 12.4 Compute Node Registration Flow

```
feilong starts
     │
     ├─► load_config()
     ├─► verify_remote_connectivity()     [remote mode only]
     ├─► ensure_schema_current()          [run Alembic migrations]
     └─► register_compute_node()
             │
             └─► UPSERT INTO compute_nodes
                 SET last_seen=NOW(), status='active'
                 WHERE id = CONF.database.compute_node_id
```

On clean shutdown, `status` is set to `'inactive'`. On a crash, a background health-check
process (or the next startup) detects stale `last_seen` timestamps.

---

## 13. Risks and Mitigations

| Risk                                        | Mitigation                                                     |
|---------------------------------------------|----------------------------------------------------------------|
| Case-sensitivity mismatch (COLLATE)         | Use `utf8mb4_general_ci` (case-insensitive, matches NOCASE)   |
| `IS NOT ''` works in SQLite, not idiomatic in MySQL | Replace with `<> ''` in all queries                   |
| `sqlite3.Row` dict-style access             | SQLAlchemy `Row` supports `row._mapping['key']` or via `mappings()` |
| `executemany` with tuple lists              | SQLAlchemy 2.x `execute(stmt, list_of_dicts)` — change bind format |
| PK conflicts on `compute_node_id` expansion | Alembic migration adds column with `DEFAULT ''` before PK change |
| Connection pool exhaustion under load       | Tune `pool_size` + `pool_max_overflow`; `pool_pre_ping=True` in `get_engine()` |
| Network latency in remote mode              | Connection pooling reuses connections; monitor with Prometheus |
| Secrets in `zvmsdk.conf` plaintext          | oslo.config secret=True; Barbican; env vars; file permissions  |
| DDL migration failure mid-upgrade           | MySQL/MariaDB DDL is **not** transactional — `ALTER TABLE` auto-commits and cannot be rolled back (unlike PostgreSQL). A migration that fails mid-way leaves a partially altered schema. Mitigation: test on staging first; document manual reverse-DDL steps in each migration's docstring; consider running migrations from a single node pre-upgrade rather than on every node startup. |
| FK violation in local mode                  | FK constraints to `compute_nodes` are added by the 0003 migration **only** when `mode=remote`. Base DDL has no FK so `DEFAULT ''` rows in local mode are always valid. |
| Password special characters breaking DB URL | Use `sqlalchemy.engine.URL.create()` (§7.2) — percent-encodes credentials and keeps the password out of log output. |
| Multi-node concurrent migration on startup  | Alembic advisory lock serialises runners; only one executes DDL. Combine with single-node pre-upgrade step for safety (see §8.3). |
| `image` PK collision (same name, two nodes) | PK changed to `(imagename, compute_node_id)`; global images use sentinel `'GLOBAL'` (see §5.2). |

---

## 14. New Python Dependencies

Add to `requirements.txt`:

```
SQLAlchemy>=2.0.0        # Apache-2.0 — core DB abstraction
alembic>=1.13.0          # MIT — schema migrations
PyMySQL>=1.1.0           # MIT — MariaDB/MySQL pure-Python driver
cryptography>=41.0.0     # Apache/BSD — required by PyMySQL SSL support
```

---

## 15. Implementation Phases

| Phase | Scope                                                                 | Risk   |
|-------|-----------------------------------------------------------------------|--------|
| 1     | Add SQLAlchemy engine factory; keep SQLite as default backend         | Low    |
| 2     | Add `zvmsdk/db/models.py`; create Alembic setup + initial migration   | Low    |
| 3     | Refactor `database.py` connection managers to use SQLAlchemy          | Medium |
| 4     | Add MariaDB/MySQL dialect support; test all operators against MariaDB  | Medium |
| 5     | Add `compute_node_id` column + `compute_nodes` table + Alembic migration | High |
| 6     | Implement `remote` mode: node registration, filtered queries          | High   |
| 7     | Write `migrate_sqlite_to_mariadb.py` data migration tool              | Low    |
| 8     | Integration test with OpenStack nova-compute + z/VM driver            | Medium |
