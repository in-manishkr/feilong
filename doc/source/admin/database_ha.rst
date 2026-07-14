..
 Copyright Contributors to the Feilong Project.
 SPDX-License-Identifier: CC-BY-4.0

======================================
Database High-Availability Guide
======================================

This guide covers high-availability database topologies for feilong in
**remote mode** (``mode = remote`` in ``zvmsdk.conf``).

Overview
--------

In remote mode, all feilong compute nodes share a single MariaDB/MySQL database.
To make the database itself highly available, two common approaches are:

* **Galera Cluster** — synchronous multi-master replication (MariaDB native)
* **ProxySQL** — transparent query routing and connection pooling in front of
  any replication topology

Galera Cluster
--------------

Galera provides synchronous active-active replication across 3+ nodes.  Any
write succeeds only when all live nodes have committed it, so there is no data
loss on node failure.

Setting Up a 3-Node Galera Cluster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install MariaDB with Galera support on three hosts (``db1``, ``db2``, ``db3``)::

    # On each database host (Debian/Ubuntu example)
    apt-get install -y mariadb-server galera-4 mariadb-backup

Configure ``/etc/mysql/mariadb.conf.d/60-galera.cnf`` on each node::

    [mysqld]
    binlog_format = ROW
    default-storage-engine = innodb
    innodb_autoinc_lock_mode = 2
    bind-address = 0.0.0.0

    # Galera Provider
    wsrep_on = ON
    wsrep_provider = /usr/lib/galera/libgalera_smm.so

    # Cluster name (must match on all nodes)
    wsrep_cluster_name = "zvmsdk_galera"

    # Peer list — all cluster members
    wsrep_cluster_address = "gcomm://db1,db2,db3"

    # This node's own address
    wsrep_node_address = "<this-node-ip>"
    wsrep_node_name = "<this-node-hostname>"

    wsrep_sst_method = mariabackup

Bootstrap the cluster (run only on ``db1``, once)::

    galera_new_cluster

Start the remaining nodes::

    systemctl start mariadb    # on db2 and db3

Point feilong at the cluster VIP (managed by Pacemaker/Keepalived) or list
all nodes as a comma-separated ``host`` value in ``zvmsdk.conf``::

    [database]
    backend = mariadb
    host = db1   # or use a VIP / load-balancer address
    port = 3306
    name = zvmsdk
    user = zvmsdk
    mode = remote

Galera and ``pool_pre_ping``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The feilong engine is created with ``pool_pre_ping=True``, which issues a
``SELECT 1`` before returning a connection from the pool.  This transparently
recovers from stale connections caused by a Galera primary node failover without
requiring application restart.

ProxySQL
--------

ProxySQL sits in front of any replication topology (primary/replica,
Galera, Group Replication) and provides:

* Read/write splitting — writes to primary, reads from replicas
* Connection multiplexing — reduces DB connection count from many feilong nodes
* Automatic failover via health checks

Basic ProxySQL Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install ProxySQL on a dedicated host or each compute node::

    # Download and install from https://github.com/sysown/proxysql/releases

Add the MariaDB backends in ProxySQL admin::

    -- In ProxySQL admin (mysql -h 127.0.0.1 -P 6032 -u admin -padmin)
    INSERT INTO mysql_servers (hostgroup_id, hostname, port) VALUES
        (0, 'db1', 3306),  -- hostgroup 0 = writers
        (1, 'db2', 3306),  -- hostgroup 1 = readers
        (1, 'db3', 3306);

    INSERT INTO mysql_users (username, password, default_hostgroup) VALUES
        ('zvmsdk', 'strong-password-here', 0);

    LOAD MYSQL SERVERS TO RUNTIME; SAVE MYSQL SERVERS TO DISK;
    LOAD MYSQL USERS TO RUNTIME;   SAVE MYSQL USERS TO DISK;

Point feilong at ProxySQL::

    [database]
    backend = mariadb
    host = 127.0.0.1   # ProxySQL listens locally
    port = 6033         # ProxySQL MySQL port (not 3306)
    name = zvmsdk
    user = zvmsdk
    mode = remote

Connection Pool Sizing
-----------------------

Tune the connection pool based on your topology:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Scenario
     - Recommended ``pool_size``
     - Notes
   * - Single MariaDB, 1 feilong node
     - 5
     - Default; most local deployments
   * - Galera 3-node, 3 feilong nodes
     - 5–10 per feilong node
     - Monitor ``checked_out`` via ``get_pool_status()``
   * - ProxySQL front-end, 10+ feilong nodes
     - 3–5 per feilong node
     - ProxySQL multiplexes; keep total ≤ MariaDB max_connections

Configure in ``zvmsdk.conf``::

    [database]
    pool_size = 5
    pool_max_overflow = 10
    pool_timeout = 30
    pool_recycle = 3600

Stale Node Detection
---------------------

When a feilong node crashes without calling ``deregister_compute_node()``,
its entry in ``compute_nodes`` stays ``active``.  The startup health-check
cleans this up automatically::

    from zvmsdk.db.api import check_stale_nodes
    check_stale_nodes(threshold_seconds=300)

You can also trigger this from a cron job or monitoring script::

    python3 -c "
    from zvmsdk.db.api import check_stale_nodes
    check_stale_nodes(300)
    "

FK Cascade on Node Removal
---------------------------

In remote mode (``mode = remote``) the schema includes foreign-key constraints
from every data table to ``compute_nodes`` with ``ON DELETE CASCADE``.  If an
operator manually removes a node entry from ``compute_nodes``, all associated
guests, FCP records, and switch records are automatically deleted.

.. warning::
   This is intentional but irreversible.  Back up before manual node deletion.
