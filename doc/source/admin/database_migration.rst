..
 Copyright Contributors to the Feilong Project.
 SPDX-License-Identifier: CC-BY-4.0

======================================
Database Migration Guide
======================================

This guide describes how to migrate an existing single-node feilong deployment
from per-table SQLite files to a consolidated database (either a single
consolidated SQLite or a shared MariaDB/MySQL instance).

Overview
--------

Feilong originally stored each data domain in a separate SQLite file:

* ``sdk_network.sqlite`` — switch/VLAN records
* ``sdk_guest.sqlite`` — guest VM metadata
* ``sdk_image.sqlite`` — image registry
* ``sdk_fcp.sqlite`` — FCP devices and templates

Starting with Phase 1 of the ``byodb`` project, all data is managed through a
single SQLAlchemy engine backed by either a consolidated SQLite file
(``zvmsdk.db``) or a centralized MariaDB/MySQL instance.  A ``compute_node_id``
column is added to every table so multiple feilong nodes can share one database
in **remote mode**.

Step-by-Step: SQLite → Consolidated SQLite
-------------------------------------------

Use this path if you want the simplest upgrade without installing MariaDB.

1. **Install the updated package** ::

     pip install --upgrade feilong

2. **Upgrade the schema** ::

     # This creates zvmsdk.db with the new schema under database.dir
     python3 -c "from zvmsdk.db import migration; migration.ensure_schema_current()"

3. **Migrate existing data** ::

     python3 tools/migrate_sqlite_to_mariadb.py \
         --sqlite-dir /var/lib/zvmsdk/databases/ \
         --target-backend sqlite \
         --compute-node-id $(hostname)

   Use ``--dry-run`` first to preview row counts without writing.

4. **Verify** ::

     python3 tools/migrate_sqlite_to_mariadb.py \
         --sqlite-dir /var/lib/zvmsdk/databases/ \
         --target-backend sqlite \
         --compute-node-id $(hostname) \
         --dry-run

5. **Restart feilong** — no config change needed; ``backend=sqlite`` is the default.

Step-by-Step: SQLite → MariaDB (Local Mode)
--------------------------------------------

Use this path for improved performance on a single host with MariaDB installed.

Prerequisites
~~~~~~~~~~~~~

* MariaDB 10.5+ or MySQL 8.0+ installed and running.
* A database and user created for feilong::

    CREATE DATABASE zvmsdk CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
    CREATE USER 'zvmsdk'@'localhost' IDENTIFIED BY 'strong-password-here';
    GRANT ALL PRIVILEGES ON zvmsdk.* TO 'zvmsdk'@'localhost';
    FLUSH PRIVILEGES;

Migration Steps
~~~~~~~~~~~~~~~

1. **Install the updated package** ::

     pip install --upgrade feilong

2. **Upgrade the schema** on the MariaDB target::

     # Export credentials so they are not stored in config files
     export ZVMSDK_DB_PASSWORD="strong-password-here"

     # Temporarily point to MariaDB to create tables
     python3 -c "
     from zvmsdk import config
     config.CONF['database']['backend'] = 'mariadb'
     config.CONF['database']['host'] = '127.0.0.1'
     config.CONF['database']['user'] = 'zvmsdk'
     config.CONF['database']['name'] = 'zvmsdk'
     from zvmsdk.db import migration
     migration.ensure_schema_current()
     "

3. **Migrate data** ::

     export ZVMSDK_DB_PASSWORD="strong-password-here"
     python3 tools/migrate_sqlite_to_mariadb.py \
         --sqlite-dir /var/lib/zvmsdk/databases/ \
         --target-backend mariadb \
         --compute-node-id $(hostname) \
         --config /etc/zvmsdk/zvmsdk.conf

4. **Update ``zvmsdk.conf``** ::

     [database]
     backend = mariadb
     host = 127.0.0.1
     port = 3306
     name = zvmsdk
     user = zvmsdk
     # Use the environment variable instead:
     # password = strong-password-here
     mode = local
     compute_node_id = <unique-node-id>

   .. tip::
      Set the password via the environment variable ``ZVMSDK_DB_PASSWORD``
      rather than in the config file to avoid credentials in plaintext.

5. **Restart feilong** ::

     systemctl restart feilong

6. **Verify connectivity** ::

     python3 -c "from zvmsdk.db.api import verify_remote_connectivity; verify_remote_connectivity()"

Step-by-Step: Multi-Node Remote Mode
--------------------------------------

Use this path when two or more feilong instances share one centralized MariaDB.

1. **On the management/database host**: provision MariaDB, create database and
   user as above but allow connections from all compute nodes::

     CREATE USER 'zvmsdk'@'%' IDENTIFIED BY 'strong-password-here';
     GRANT ALL PRIVILEGES ON zvmsdk.* TO 'zvmsdk'@'%';

2. **On one designated compute node**: migrate data (steps 1–3 above) with
   ``--target-backend mariadb`` and the management host's IP as ``host``.

3. **On each compute node**: update ``zvmsdk.conf`` to point at the central
   MariaDB and set ``mode = remote``::

     [database]
     backend = mariadb
     host = <management-host-ip>
     port = 3306
     name = zvmsdk
     user = zvmsdk
     mode = remote
     compute_node_id = <unique-per-node-id>

4. **Rolling restart** of feilong on all compute nodes.  The startup sequence
   automatically calls:

   * ``ensure_schema_current()`` — applies any pending Alembic migrations
   * ``verify_remote_connectivity()`` — confirms the DB is reachable
   * ``register_compute_node()`` — UPSERTs this node into ``compute_nodes``
   * ``check_stale_nodes()`` — marks timed-out nodes inactive

Rollback
--------

The migration tool never modifies the original SQLite files.  To revert:

1. Stop feilong.
2. Drop the target database (``DROP DATABASE zvmsdk;``) or remove the
   consolidated ``zvmsdk.db`` file.
3. Set ``backend = sqlite`` (or restore a backup) in ``zvmsdk.conf``.
4. Restart feilong.

Connection Pool Monitoring
---------------------------

Call ``zvmsdk.db.api.get_pool_status()`` to retrieve live pool statistics::

    from zvmsdk.db.api import get_pool_status
    print(get_pool_status())
    # {'backend': 'mariadb', 'pool_size': 5, 'checked_out': 1,
    #  'overflow': 0, 'lifetime_checked_out': 42, 'lifetime_invalidated': 0}

These counters can be exported to Prometheus via a custom metrics endpoint.
