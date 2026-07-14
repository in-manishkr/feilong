..
 Copyright Contributors to the Feilong Project.
 SPDX-License-Identifier: CC-BY-4.0

======================================
Database TLS/SSL Configuration
======================================

This guide explains how to configure TLS encryption between feilong and
MariaDB/MySQL.  Encrypting the database connection is strongly recommended
in remote mode where traffic crosses a network.

Overview
--------

Feilong connects to MariaDB via PyMySQL.  TLS support is enabled by setting
one or more of the ``ssl_ca``, ``ssl_cert``, and ``ssl_key`` options in the
``[database]`` section of ``zvmsdk.conf``.

The ``ssl_ca`` option is the minimum required to verify the server certificate.
``ssl_cert`` and ``ssl_key`` are only needed for mutual TLS (mTLS) where the
client must also present a certificate.

Generating Certificates
------------------------

For production, use certificates issued by your PKI or a public CA.  For
development, generate a self-signed CA and server/client certs::

    # Create CA
    openssl genrsa -out ca-key.pem 4096
    openssl req -new -x509 -days 3650 -key ca-key.pem \
        -out ca-cert.pem -subj "/CN=feilong-db-ca"

    # MariaDB server certificate
    openssl genrsa -out server-key.pem 2048
    openssl req -new -key server-key.pem -out server-req.pem \
        -subj "/CN=mariadb-server"
    openssl x509 -req -days 3650 -CA ca-cert.pem -CAkey ca-key.pem \
        -CAcreateserial -in server-req.pem -out server-cert.pem

    # Client certificate for mutual TLS (optional)
    openssl genrsa -out client-key.pem 2048
    openssl req -new -key client-key.pem -out client-req.pem \
        -subj "/CN=feilong-client"
    openssl x509 -req -days 3650 -CA ca-cert.pem -CAkey ca-key.pem \
        -CAcreateserial -in client-req.pem -out client-cert.pem

Copy ``ca-cert.pem`` and (if using mTLS) ``client-cert.pem`` + ``client-key.pem``
to each feilong host, e.g. under ``/etc/zvmsdk/ssl/``.

Configuring MariaDB for TLS
-----------------------------

Add to ``/etc/mysql/mariadb.conf.d/50-server.cnf``::

    [mysqld]
    ssl-ca   = /etc/mysql/ssl/ca-cert.pem
    ssl-cert = /etc/mysql/ssl/server-cert.pem
    ssl-key  = /etc/mysql/ssl/server-key.pem

    # Optionally require TLS for all connections:
    # require_secure_transport = ON

Restart MariaDB::

    systemctl restart mariadb

Verify TLS is active::

    mysql -u zvmsdk -p -e "SHOW STATUS LIKE 'Ssl_cipher';"
    # Should show a non-empty cipher, e.g. TLS_AES_256_GCM_SHA384

Configuring feilong for TLS
-----------------------------

Server-Only TLS (CA Verification)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The client verifies the server certificate.  Add to ``zvmsdk.conf``::

    [database]
    backend   = mariadb
    host      = db-host.example.com
    port      = 3306
    name      = zvmsdk
    user      = zvmsdk
    ssl_ca    = /etc/zvmsdk/ssl/ca-cert.pem

Mutual TLS (Client + Server Certificates)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Both sides present certificates.  Add to ``zvmsdk.conf``::

    [database]
    backend   = mariadb
    host      = db-host.example.com
    port      = 3306
    name      = zvmsdk
    user      = zvmsdk
    ssl_ca    = /etc/zvmsdk/ssl/ca-cert.pem
    ssl_cert  = /etc/zvmsdk/ssl/client-cert.pem
    ssl_key   = /etc/zvmsdk/ssl/client-key.pem

Certificate Permissions
~~~~~~~~~~~~~~~~~~~~~~~~

Ensure the feilong service account can read the certificate files::

    chmod 640 /etc/zvmsdk/ssl/client-key.pem
    chown root:zvmsdk /etc/zvmsdk/ssl/client-key.pem

Verifying the TLS Connection
------------------------------

After restarting feilong, verify that the connection is encrypted::

    python3 -c "
    from zvmsdk.db.api import get_engine
    from sqlalchemy import text
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(\"SHOW STATUS LIKE 'Ssl_cipher'\")).fetchone()
        print('Cipher:', row[1] if row else 'NOT ENCRYPTED')
    "

The output should show a TLS cipher string (e.g. ``TLS_AES_256_GCM_SHA384``).
An empty value indicates the connection is not encrypted.

Environment Variable for Password
----------------------------------

When using TLS, avoid also storing the database password in the config file.
Use the ``ZVMSDK_DB_PASSWORD`` environment variable instead::

    export ZVMSDK_DB_PASSWORD="strong-password-here"
    systemctl restart feilong

The environment variable takes priority over ``password =`` in ``zvmsdk.conf``
when both are set to non-empty values (config file wins if both are non-empty;
env var is the fallback when config password is empty).

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Error
     - Resolution
   * - ``SSL connection error: SSL_CTX_set_default_verify_paths``
     - Check that ``ssl_ca`` path is readable by the feilong process.
   * - ``Access denied … SSL required``
     - Set ``ssl_ca`` in ``zvmsdk.conf`` or ensure the DB user doesn't require TLS.
   * - ``SDKInternalError: Cannot connect to remote database``
     - Run ``verify_remote_connectivity()`` manually to see the underlying error.
   * - ``SSL_ERROR_WANT_READ`` / handshake timeout
     - Verify MariaDB ``ssl-cert`` and ``ssl-key`` are readable by the ``mysql`` user.
