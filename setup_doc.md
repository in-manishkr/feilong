# Feilong Database Setup Guide

This guide covers all four supported database configurations for feilong (zvmsdk):

| Mode | Backend | When to use |
|------|---------|-------------|
| **SQLite local** (default) | SQLite | Development, single-node, zero extra setup |
| **SQLite → consolidated SQLite** | SQLite | Upgrading from old per-table files to new single `zvmsdk.db` |
| **MariaDB local** | MariaDB/MySQL | Better performance on a single host |
| **MariaDB remote** | MariaDB/MySQL | Multi-node deployments sharing one centralized DB |

---

## Prerequisites

### Python dependencies

```bash
pip install SQLAlchemy>=2.0.0 alembic>=1.13.0 PyMySQL>=1.1.0 cryptography>=41.0.0
```

Or install from the project:

```bash
pip install -r requirements.txt
```

### Verify the feilong package is importable

```bash
python3 -c "from zvmsdk.db import api, migration; print('OK')"
```

---

## Option 1 — SQLite Local (Default)

No extra software needed. This is the default mode and is backward-compatible with all existing feilong deployments.

### Configuration (`zvmsdk.conf`)

```ini
[database]
backend = sqlite
mode    = local
dir     = /var/lib/zvmsdk/databases/

# compute_node_id is optional in local mode; auto-detected if not set
# compute_node_id = my-node-A
```

### Initialize the schema

```bash
python3 -c "
from zvmsdk import config
config.CONF['database']['dir'] = '/var/lib/zvmsdk/databases/'
from zvmsdk.db import migration
migration.ensure_schema_current()
print('Schema ready:', '/var/lib/zvmsdk/databases/zvmsdk.db')
"
```

### Quick smoke test

```bash
python3 tools/test_db_api.py
```

The script defaults to SQLite in `/tmp/zvmsdk_test/` when no environment variables are set.

---

## Option 2 — Migrate Old SQLite Files to Consolidated SQLite

Feilong previously stored data in five separate SQLite files. The new code uses a single `zvmsdk.db`. Run this once when upgrading.

### Source files (old layout)

```
/var/lib/zvmsdk/databases/
├── sdk_network.sqlite
├── sdk_guest.sqlite
├── sdk_image.sqlite
└── sdk_fcp.sqlite
```

### Step 1 — Dry run (verify row counts, no writes)

```bash
python3 tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --target-backend sqlite \
    --compute-node-id "$(hostname)" \
    --config /etc/zvmsdk/zvmsdk.conf \
    --dry-run
```

### Step 2 — Migrate

```bash
python3 tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --target-backend sqlite \
    --compute-node-id "$(hostname)" \
    --config /etc/zvmsdk/zvmsdk.conf
```

Expected output (per table):

```
[OK]       switch        : source=12, target=12
[OK]       guests        : source=47, target=47
[OK]       image         : source=5,  target=5
[OK]       fcp           : source=32, target=32
```

### Step 3 — Restart feilong

No config change needed — `backend = sqlite` is already the default.

---

## Option 3 — MariaDB Local

One MariaDB instance on the same host as feilong. Each feilong node has its own database. Behavior is identical to SQLite but with better concurrency and tooling.

### Step 1 — Install MariaDB

```bash
# Debian/Ubuntu
apt-get install -y mariadb-server

# RHEL/CentOS
dnf install -y mariadb-server
systemctl enable --now mariadb
```

### Step 2 — Create database and user

```bash
mysql -u root -p <<'EOF'
CREATE DATABASE IF NOT EXISTS zvmsdk
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

CREATE USER IF NOT EXISTS 'zvmsdk'@'localhost' IDENTIFIED BY 'change-me';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
    ON zvmsdk.* TO 'zvmsdk'@'localhost';

FLUSH PRIVILEGES;
EOF
```

### Step 3 — Configure feilong (`zvmsdk.conf`)

```ini
[database]
backend  = mariadb
mode     = local
host     = 127.0.0.1
port     = 3306
name     = zvmsdk
user     = zvmsdk
# password = change-me          # or use the env var (recommended):
# export ZVMSDK_DB_PASSWORD=change-me

compute_node_id = my-node-A     # optional — auto-detected if omitted

# Connection pool
pool_size         = 5
pool_max_overflow = 10
pool_timeout      = 30
pool_recycle      = 3600
```

### Step 4 — Set the password via environment variable (recommended)

```bash
export ZVMSDK_DB_PASSWORD='change-me'
```

### Step 5 — Initialize the schema

```bash
python3 -c "
import os
os.environ.setdefault('ZVMSDK_DB_PASSWORD', 'change-me')
from zvmsdk import config
config.CONF['database']['backend'] = 'mariadb'
config.CONF['database']['host']    = '127.0.0.1'
config.CONF['database']['user']    = 'zvmsdk'
config.CONF['database']['name']    = 'zvmsdk'
from zvmsdk.db import migration
migration.ensure_schema_current()
print('MariaDB schema ready')
"
```

### Step 6 — Migrate existing SQLite data (if upgrading)

```bash
export ZVMSDK_DB_PASSWORD='change-me'
python3 tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --target-backend mariadb \
    --compute-node-id "$(hostname)" \
    --config /etc/zvmsdk/zvmsdk.conf
```

### Step 7 — Verify

```bash
export ZVMSDK_DB_PASSWORD='change-me'
ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:change-me@127.0.0.1:3306/zvmsdk" \
    python3 tools/test_db_api.py
```

### Step 8 — Restart feilong

```bash
systemctl restart feilong
```

---

## Option 4 — MariaDB Remote (Multi-Node)

All feilong compute nodes connect to one centralized MariaDB on the management node. Each node's rows are scoped by `compute_node_id`.

```
Management Node (MariaDB)
        │
   ┌────┴────────────────┐
   │                     │
Compute A             Compute B
feilong               feilong
node_id=A             node_id=B
```

### Step 1 — Provision the central MariaDB (management node only)

```bash
mysql -u root -p <<'EOF'
CREATE DATABASE IF NOT EXISTS zvmsdk
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

-- Shared user (all compute nodes use this)
CREATE USER IF NOT EXISTS 'zvmsdk'@'%' IDENTIFIED BY 'strong-password-here';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
    ON zvmsdk.* TO 'zvmsdk'@'%';

-- Optional: per-node users for tighter control
-- CREATE USER 'zvmsdk_nodeA'@'10.0.0.1' IDENTIFIED BY 'pw-A';
-- GRANT ALL ON zvmsdk.* TO 'zvmsdk_nodeA'@'10.0.0.1';

FLUSH PRIVILEGES;
EOF
```

### Step 2 — Open the firewall

On the management node, allow TCP 3306 from compute node IPs only:

```bash
# Example using ufw
ufw allow from 10.0.0.0/24 to any port 3306

# Example using firewalld
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/24" port port="3306" protocol="tcp" accept'
firewall-cmd --reload
```

### Step 3 — Configure each compute node (`zvmsdk.conf`)

Each node gets a **unique** `compute_node_id`:

**Compute Node A** (`/etc/zvmsdk/zvmsdk.conf`):

```ini
[database]
backend          = mariadb
mode             = remote
host             = <management-node-ip>
port             = 3306
name             = zvmsdk
user             = zvmsdk
compute_node_id  = node-A        # MUST be unique per node

pool_size         = 5
pool_max_overflow = 10
pool_timeout      = 30
pool_recycle      = 3600
```

**Compute Node B** (`/etc/zvmsdk/zvmsdk.conf`):

```ini
[database]
backend          = mariadb
mode             = remote
host             = <management-node-ip>
port             = 3306
name             = zvmsdk
user             = zvmsdk
compute_node_id  = node-B        # different from node-A
```

### Step 4 — Set the password on each compute node

```bash
export ZVMSDK_DB_PASSWORD='strong-password-here'
# Add to /etc/environment or systemd service file for persistence
```

### Step 5 — Initialize schema (run once, on any one compute node)

```bash
python3 -c "
from zvmsdk import config
config.CONF['database']['backend']         = 'mariadb'
config.CONF['database']['mode']            = 'remote'
config.CONF['database']['host']            = '<management-node-ip>'
config.CONF['database']['user']            = 'zvmsdk'
config.CONF['database']['name']            = 'zvmsdk'
config.CONF['database']['compute_node_id'] = 'node-A'
from zvmsdk.db import migration
migration.ensure_schema_current()
print('Remote schema ready (including FK constraints)')
"
```

### Step 6 — Migrate existing SQLite data (per-node, if upgrading)

Run on **each** compute node while it still has local SQLite data:

```bash
export ZVMSDK_DB_PASSWORD='strong-password-here'
python3 tools/migrate_sqlite_to_mariadb.py \
    --sqlite-dir /var/lib/zvmsdk/databases/ \
    --target-backend mariadb \
    --compute-node-id node-A \
    --config /etc/zvmsdk/zvmsdk.conf
```

### Step 7 — Rolling restart

```bash
# On each compute node, one at a time
systemctl restart feilong
```

On startup each node automatically:
1. Runs `ensure_schema_current()` — applies any pending Alembic migrations
2. Calls `verify_remote_connectivity()` — confirms DB is reachable
3. Calls `register_compute_node()` — UPSERTs its row in `compute_nodes`
4. Calls `check_stale_nodes()` — marks timed-out nodes inactive

### Step 8 — Verify

```bash
export ZVMSDK_DB_PASSWORD='strong-password-here'
ZVMSDK_TEST_DB_URL="mysql+pymysql://zvmsdk:strong-password-here@<management-node-ip>:3306/zvmsdk" \
ZVMSDK_TEST_NODE_ID="node-A" \
    python3 tools/test_db_api.py
```

---

## TLS/SSL (optional but strongly recommended for remote mode)

### Generate self-signed certificates (development only)

```bash
# CA
openssl genrsa -out ca-key.pem 4096
openssl req -new -x509 -days 3650 -key ca-key.pem \
    -out ca-cert.pem -subj "/CN=feilong-db-ca"

# Server certificate (runs on MariaDB host)
openssl genrsa -out server-key.pem 2048
openssl req -new -key server-key.pem -out server-req.pem -subj "/CN=mariadb-server"
openssl x509 -req -days 3650 -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -in server-req.pem -out server-cert.pem

# Client certificate (for mutual TLS — optional)
openssl genrsa -out client-key.pem 2048
openssl req -new -key client-key.pem -out client-req.pem -subj "/CN=feilong-client"
openssl x509 -req -days 3650 -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -in client-req.pem -out client-cert.pem
```

### Configure MariaDB for TLS (`/etc/mysql/mariadb.conf.d/50-server.cnf`)

```ini
[mysqld]
ssl-ca   = /etc/mysql/ssl/ca-cert.pem
ssl-cert = /etc/mysql/ssl/server-cert.pem
ssl-key  = /etc/mysql/ssl/server-key.pem
# require_secure_transport = ON   # uncomment to enforce TLS for all connections
```

```bash
systemctl restart mariadb
```

### Configure feilong for TLS (`zvmsdk.conf`)

```ini
[database]
ssl_ca   = /etc/zvmsdk/ssl/ca-cert.pem
# ssl_cert = /etc/zvmsdk/ssl/client-cert.pem   # for mutual TLS
# ssl_key  = /etc/zvmsdk/ssl/client-key.pem    # for mutual TLS
```

### Verify TLS is active

```bash
python3 -c "
from zvmsdk.db.api import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as conn:
    row = conn.execute(text(\"SHOW STATUS LIKE 'Ssl_cipher'\")).fetchone()
    cipher = row[1] if row else ''
    print('TLS cipher:', cipher or 'NOT ENCRYPTED')
    assert cipher, 'ERROR: connection is not encrypted!'
"
```

---

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `ZVMSDK_DB_PASSWORD` | Database password (preferred over config file) | `export ZVMSDK_DB_PASSWORD='secret'` |
| `ZVMSDK_TEST_DB_URL` | Full SQLAlchemy URL for the test script / MariaDB integration tests | `mysql+pymysql://zvmsdk:secret@127.0.0.1:3306/zvmsdk` |
| `ZVMSDK_TEST_NODE_ID` | `compute_node_id` to use in the test script | `node-A` |
| `ZVMSDK_TEST_DB_SSL_URL` | SSL-enabled URL for SSL smoke tests | same format as above |
| `ZVMSDK_TEST_DB_SSL_CA` | Path to CA cert for SSL smoke tests | `/etc/zvmsdk/ssl/ca-cert.pem` |

---

## Pool Status Monitoring

Inspect live connection pool statistics at any time:

```python
from zvmsdk.db.api import get_pool_status
import json
print(json.dumps(get_pool_status(), indent=2))
```

SQLite output:

```json
{
  "backend": "sqlite",
  "lifetime_checked_out": 42,
  "lifetime_checked_in": 42,
  "lifetime_invalidated": 0
}
```

MariaDB/QueuePool output:

```json
{
  "backend": "mariadb",
  "pool_size": 5,
  "checked_out": 1,
  "overflow": 0,
  "lifetime_checked_out": 128,
  "lifetime_checked_in": 127,
  "lifetime_invalidated": 0
}
```

---

## Rollback

The migration script **never modifies source SQLite files**. To revert to SQLite:

1. Stop feilong.
2. Set `backend = sqlite` in `zvmsdk.conf`.
3. Restart feilong.

To revert a MariaDB schema to a previous Alembic revision:

```bash
# Show current revision
python3 -m alembic -c zvmsdk/db/alembic/alembic.ini current

# Downgrade one step
python3 -m alembic -c zvmsdk/db/alembic/alembic.ini downgrade -1

# Downgrade to base (drops everything)
python3 -m alembic -c zvmsdk/db/alembic/alembic.ini downgrade base
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'PyMySQL'` | PyMySQL not installed | `pip install PyMySQL>=1.1.0` |
| `Access denied for user 'zvmsdk'@'...'` | Wrong password or user | Check `ZVMSDK_DB_PASSWORD` and `GRANT` statement |
| `Can't connect to MySQL server on '...'` | Wrong host/port or firewall | Verify `host`, `port`, firewall rule allows TCP 3306 |
| `SDKInternalError: database.mode=remote requires backend=mariadb` | `mode=remote` with `backend=sqlite` | Change to `backend=mariadb` or `mode=local` |
| `alembic.util.exc.CommandError: Can't locate revision` | Alembic version table out of sync | Run `alembic stamp head` on the target DB |
| `SSL connection error: SSL_CTX_set_default_verify_paths` | `ssl_ca` path not readable | `chmod 644 /etc/zvmsdk/ssl/ca-cert.pem` |
| `OperationalError: database is locked` (SQLite) | Concurrent writes to StaticPool | Expected with SQLite; switch to MariaDB for multi-thread production use |
| Pool exhaustion (`TimeoutError`) | Too many concurrent requests | Increase `pool_size` and `pool_max_overflow` in config |

---

## Alembic Migration Chain

```
0001_initial_sqlite_baseline
    └─► 0002_initial_mariadb
            └─► 0003_add_compute_node_support
                    └─► 0004_add_remote_mode_fks
```

| Migration | What it does |
|-----------|-------------|
| 0001 | Creates all 7 data tables for SQLite (no `compute_node_id`) |
| 0002 | Creates all 7 tables for MariaDB (InnoDB, utf8mb4) — no-op for SQLite |
| 0003 | Adds `compute_node_id` to all tables; creates `compute_nodes` registry |
| 0004 | Adds FK constraints from data tables to `compute_nodes` (`mode=remote` only) |
