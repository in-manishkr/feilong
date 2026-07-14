#!/usr/bin/env python3
#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0
"""
Migrate existing per-table SQLite data files to a MariaDB (or consolidated
SQLite) database.

Rollback: this script does not delete source SQLite files. To revert, drop the
target database and restore from backup. The source SQLite files are never
modified.

Typical usage:
  python3 tools/migrate_sqlite_to_mariadb.py \\
      --sqlite-dir /var/lib/zvmsdk/databases/ \\
      --config /etc/zvmsdk/zvmsdk.conf \\
      --compute-node-id IAAS01EF@BOEM5401

Dry-run (no writes):
  python3 tools/migrate_sqlite_to_mariadb.py \\
      --sqlite-dir /var/lib/zvmsdk/databases/ \\
      --config /etc/zvmsdk/zvmsdk.conf \\
      --dry-run
"""

import argparse
import configparser
import logging
import os
import sqlite3
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
LOG = logging.getLogger(__name__)

# Module-level SDK imports — importing these modules is safe before config is
# applied because CONF is lazy (defaults only; get_engine() is never called on
# import).  Having them at module level lets tests patch them without needing
# to reach inside main().
from zvmsdk import config as zvm_config          # noqa: E402
from zvmsdk.db import api as db_api              # noqa: E402
from zvmsdk.db import migration as db_migration  # noqa: E402

# ---------------------------------------------------------------------------
# Table migration configuration
# Each entry maps a source SQLite filename to a list of table descriptors.
# 'src_cols': columns as they exist in the OLD (pre-migration-0003) SQLite.
# 'tgt_cols': columns in the NEW target schema (with compute_node_id inserted).
# 'use_global': if True, compute_node_id is always 'GLOBAL' (images only).
# ---------------------------------------------------------------------------
SOURCE_MAP = [
    ('sdk_network.sqlite', [
        {
            'table': 'switch',
            'src_cols': ('userid', 'interface', 'switch', 'port', 'comments'),
            'tgt_cols': ('userid', 'interface', 'compute_node_id',
                         'switch', 'port', 'comments'),
            'use_global': False,
        }
    ]),
    ('sdk_guest.sqlite', [
        {
            'table': 'guests',
            'src_cols': ('id', 'userid', 'metadata', 'net_set', 'comments'),
            'tgt_cols': ('id', 'userid', 'compute_node_id',
                         'metadata', 'net_set', 'comments'),
            'use_global': False,
        }
    ]),
    ('sdk_image.sqlite', [
        {
            'table': 'image',
            'src_cols': ('imagename', 'imageosdistro', 'md5sum',
                         'disk_size_units', 'image_size_in_bytes',
                         'type', 'comments'),
            'tgt_cols': ('imagename', 'compute_node_id', 'imageosdistro',
                         'md5sum', 'disk_size_units', 'image_size_in_bytes',
                         'type', 'comments'),
            'use_global': True,  # images are globally shared across nodes
        }
    ]),
    ('sdk_fcp.sqlite', [
        {
            'table': 'fcp',
            'src_cols': ('fcp_id', 'assigner_id', 'connections', 'reserved',
                         'wwpn_npiv', 'wwpn_phy', 'chpid', 'pchid',
                         'state', 'owner', 'tmpl_id'),
            'tgt_cols': ('fcp_id', 'compute_node_id', 'assigner_id',
                         'connections', 'reserved', 'wwpn_npiv', 'wwpn_phy',
                         'chpid', 'pchid', 'state', 'owner', 'tmpl_id'),
            'use_global': False,
        },
        {
            'table': 'template',
            'src_cols': ('id', 'name', 'description',
                         'is_default', 'min_fcp_paths_count'),
            'tgt_cols': ('id', 'compute_node_id', 'name', 'description',
                         'is_default', 'min_fcp_paths_count'),
            'use_global': False,
        },
        {
            'table': 'template_sp_mapping',
            'src_cols': ('sp_name', 'tmpl_id'),
            'tgt_cols': ('sp_name', 'tmpl_id', 'compute_node_id'),
            'use_global': False,
        },
        {
            'table': 'template_fcp_mapping',
            'src_cols': ('fcp_id', 'tmpl_id', 'path'),
            'tgt_cols': ('fcp_id', 'tmpl_id', 'compute_node_id', 'path'),
            'use_global': False,
        },
    ]),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='Migrate feilong SQLite data to MariaDB or consolidated SQLite.')
    p.add_argument('--sqlite-dir', required=True,
                   help='Directory containing the source *.sqlite files.')
    p.add_argument('--config',
                   help='Path to zvmsdk.conf for target DB settings.')
    p.add_argument('--compute-node-id',
                   help='Node ID to tag migrated rows with. Defaults to the '
                        'value resolved by zvmsdk.db.api at runtime.')
    p.add_argument('--target-backend', default='mariadb',
                   choices=['sqlite', 'mariadb', 'mysql'],
                   help='Target database backend (default: mariadb).')
    p.add_argument('--dry-run', action='store_true',
                   help='Print row counts without writing to the target.')
    p.add_argument('--batch-size', type=int, default=500,
                   help='Rows per INSERT batch (default: 500).')
    return p.parse_args(argv)


def _apply_config_file(config_path):
    """Read a zvmsdk.conf file and overlay the [database] section onto CONF."""
    cf = configparser.ConfigParser()
    cf.read(config_path)
    if cf.has_section('database'):
        for key, val in cf.items('database'):
            try:
                setattr(zvm_config.CONF.database, key, val)
            except Exception:
                pass
    if cf.has_section('network'):
        for key, val in cf.items('network'):
            try:
                setattr(zvm_config.CONF.network, key, val)
            except Exception:
                pass
    LOG.info("Loaded config from %s", config_path)


def _count_source_table(src_path, table):
    """Return the row count of *table* in the source SQLite file."""
    con = sqlite3.connect(src_path)
    try:
        cur = con.execute("SELECT COUNT(*) FROM %s" % table)
        return cur.fetchone()[0]
    finally:
        con.close()


def _read_source_rows(src_path, table, src_cols):
    """Return all rows from *table* as a list of plain dicts."""
    con = sqlite3.connect(src_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute("SELECT %s FROM %s" % (', '.join(src_cols), table))
        return [dict(row) for row in cur.fetchall()]
    finally:
        con.close()


def _inject_node_id(rows, node_id):
    """Add compute_node_id to every row dict in-place. Returns the list."""
    for row in rows:
        row['compute_node_id'] = node_id
    return rows


def _build_insert_sql(table, tgt_cols, backend):
    """Return an idempotent INSERT statement for the given backend."""
    col_str = ', '.join(tgt_cols)
    param_str = ', '.join(':' + c for c in tgt_cols)
    if backend in ('mariadb', 'mysql'):
        prefix = 'INSERT IGNORE'
    else:
        prefix = 'INSERT OR IGNORE'
    return "%s INTO %s (%s) VALUES (%s)" % (prefix, table, col_str, param_str)


def _chunk(lst, size):
    """Yield successive chunks of *size* from *lst*."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _count_target_table(conn, table, node_id, use_global):
    """Return how many rows in the target belong to this node."""
    from sqlalchemy import text
    effective_id = 'GLOBAL' if use_global else node_id
    result = conn.execute(
        text("SELECT COUNT(*) FROM %s WHERE compute_node_id=:nid" % table),
        {'nid': effective_id})
    return result.fetchone()[0]


def _migrate_table(tgt_conn, src_path, tbl_cfg, node_id, batch_size,
                   backend, dry_run):
    """Migrate one table from source to target. Returns (src_count, tgt_count)."""
    from sqlalchemy import text

    table = tbl_cfg['table']
    src_cols = tbl_cfg['src_cols']
    tgt_cols = tbl_cfg['tgt_cols']
    use_global = tbl_cfg['use_global']
    effective_id = 'GLOBAL' if use_global else node_id

    src_count = _count_source_table(src_path, table)
    LOG.info("[%s] source row count: %d", table, src_count)

    if dry_run or src_count == 0:
        return src_count, src_count

    rows = _read_source_rows(src_path, table, src_cols)
    _inject_node_id(rows, effective_id)

    insert_sql = _build_insert_sql(table, tgt_cols, backend)
    inserted = 0
    for batch in _chunk(rows, batch_size):
        tgt_conn.execute(text(insert_sql), batch)
        inserted += len(batch)
        LOG.debug("[%s] inserted batch of %d rows", table, len(batch))

    LOG.info("[%s] wrote %d rows", table, inserted)
    tgt_count = _count_target_table(tgt_conn, table, node_id, use_global)
    return src_count, tgt_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = _parse_args(argv)

    # ------------------------------------------------------------------
    # Apply config file before importing SDK so CONF is ready.
    # ------------------------------------------------------------------
    if args.config:
        if not os.path.exists(args.config):
            LOG.error("Config file not found: %s", args.config)
            sys.exit(1)
        _apply_config_file(args.config)

    # Override backend in CONF so get_engine() picks the right driver.
    zvm_config.CONF.database.backend = args.target_backend

    # Override compute_node_id via CONF so _resolve_compute_node_id() uses it.
    if args.compute_node_id:
        zvm_config.CONF.database.compute_node_id = args.compute_node_id

    if args.dry_run:
        LOG.info("DRY RUN — no data will be written to the target.")

    # ------------------------------------------------------------------
    # Prepare target database.
    # ------------------------------------------------------------------
    if not args.dry_run:
        LOG.info("Ensuring target schema is up to date …")
        db_migration.ensure_schema_current()
        LOG.info("Registering compute node in target …")
        db_api.register_compute_node()

    node_id = db_api.get_compute_node_id()
    LOG.info("Using compute_node_id: %s", node_id)

    backend = args.target_backend
    batch_size = args.batch_size
    sqlite_dir = args.sqlite_dir

    # ------------------------------------------------------------------
    # Migrate each source file / table.
    # ------------------------------------------------------------------
    results = []  # (table, src_count, tgt_count)
    exit_code = 0

    for src_filename, table_list in SOURCE_MAP:
        src_path = os.path.join(sqlite_dir, src_filename)

        if not os.path.exists(src_path):
            LOG.warning("Source file not found, skipping: %s", src_path)
            continue

        LOG.info("Processing source file: %s", src_path)

        for tbl_cfg in table_list:
            table = tbl_cfg['table']
            try:
                if args.dry_run:
                    src_count = _count_source_table(src_path, table)
                    LOG.info("[%s] (dry-run) source row count: %d",
                             table, src_count)
                    results.append((table, src_count, src_count))
                else:
                    with db_api.get_connection() as conn:
                        src_count, tgt_count = _migrate_table(
                            conn, src_path, tbl_cfg, node_id,
                            batch_size, backend, dry_run=False)
                    results.append((table, src_count, tgt_count))
            except Exception as exc:
                LOG.error("[%s] migration failed: %s", table, exc)
                results.append((table, -1, -1))

    # ------------------------------------------------------------------
    # Print summary report.
    # ------------------------------------------------------------------
    print()
    print("Migration Summary")
    print("=" * 60)
    print("%-30s %8s %8s  %s" % ("Table", "Source", "Target", "Status"))
    print("-" * 60)
    for table, src, tgt in results:
        if src == -1:
            status = "ERROR"
            exit_code = 1
        elif src == tgt:
            status = "OK"
        else:
            status = "MISMATCH"
            exit_code = 1
        print("%-30s %8s %8s  %s" % (table, src, tgt, status))
    print()

    if exit_code == 0:
        if args.dry_run:
            print("Dry run complete. No data was written.")
        else:
            print("All tables migrated successfully.")
    else:
        print("Migration completed with errors. See log for details.")

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
