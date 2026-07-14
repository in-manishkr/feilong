"""Add compute_node_id to all node-scoped tables and create compute_nodes registry.

Extends the schema so that each row in switch, guests, fcp, template,
template_sp_mapping, template_fcp_mapping, and image can be traced back to the
compute node that owns it.  Also creates the compute_nodes registry table.

For existing single-node deployments every row is backfilled with the current
node's ID (resolved by the same priority logic used by zvmsdk.db.api).

Manual rollback if upgrade() fails mid-way:
  -- If compute_node_id was added but PK not yet expanded:
  ALTER TABLE <table> DROP COLUMN compute_node_id;
  -- If compute_nodes was created but data tables not yet altered:
  DROP TABLE compute_nodes;
  -- Restore alembic stamp: alembic stamp 0002

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MYSQL_ARGS = dict(
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)


def _get_node_id() -> str:
    """Resolve the compute_node_id using the same priority logic as db.api."""
    try:
        from zvmsdk.db.api import _resolve_compute_node_id
        return _resolve_compute_node_id() or ''
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# SQLite helpers — recreate each table with compute_node_id in schema
# ---------------------------------------------------------------------------

def _recreate_sqlite(bind, node_id: str) -> None:
    """Recreate all 7 data tables for SQLite, adding compute_node_id."""

    # switch: PK (userid, interface) → (userid, interface, compute_node_id)
    bind.execute(sa.text("""
        CREATE TABLE switch_new (
            userid          TEXT(8)   NOT NULL,
            interface       TEXT(4)   NOT NULL,
            compute_node_id TEXT(64)  NOT NULL DEFAULT '',
            switch          TEXT(8),
            port            TEXT(128),
            comments        TEXT(128),
            PRIMARY KEY (userid, interface, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO switch_new"
                " SELECT userid, interface, :nid, switch, port, comments"
                " FROM switch"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE switch"))
    bind.execute(sa.text("ALTER TABLE switch_new RENAME TO switch"))

    # guests: PK (id), UNIQUE (userid) → UNIQUE (userid, compute_node_id)
    bind.execute(sa.text("""
        CREATE TABLE guests_new (
            id              TEXT(36)  NOT NULL,
            userid          TEXT(8)   NOT NULL,
            compute_node_id TEXT(64)  NOT NULL DEFAULT '',
            metadata        TEXT(255),
            net_set         INTEGER   NOT NULL DEFAULT 0,
            comments        TEXT,
            PRIMARY KEY (id),
            UNIQUE (userid, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO guests_new"
                " SELECT id, userid, :nid, metadata, net_set, comments"
                " FROM guests"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE guests"))
    bind.execute(sa.text("ALTER TABLE guests_new RENAME TO guests"))

    # image: PK (imagename) → (imagename, compute_node_id), default 'GLOBAL'
    bind.execute(sa.text("""
        CREATE TABLE image_new (
            imagename           TEXT(128) NOT NULL,
            compute_node_id     TEXT(64)  NOT NULL DEFAULT 'GLOBAL',
            imageosdistro       TEXT(16),
            md5sum              TEXT(512),
            disk_size_units     TEXT(512),
            image_size_in_bytes TEXT(512),
            type                TEXT(16),
            comments            TEXT(128),
            PRIMARY KEY (imagename, compute_node_id)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO image_new"
        " SELECT imagename, 'GLOBAL', imageosdistro, md5sum,"
        "        disk_size_units, image_size_in_bytes, type, comments"
        " FROM image"
    ))
    bind.execute(sa.text("DROP TABLE image"))
    bind.execute(sa.text("ALTER TABLE image_new RENAME TO image"))

    # fcp: PK (fcp_id) → (fcp_id, compute_node_id)
    # Preserve COLLATE NOCASE on string columns from original schema.
    bind.execute(sa.text("""
        CREATE TABLE fcp_new (
            fcp_id          TEXT(4)  COLLATE NOCASE NOT NULL,
            compute_node_id TEXT(64)                NOT NULL DEFAULT '',
            assigner_id     TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            connections     INTEGER                 NOT NULL DEFAULT 0,
            reserved        INTEGER                 NOT NULL DEFAULT 0,
            wwpn_npiv       TEXT(16) COLLATE NOCASE NOT NULL DEFAULT '',
            wwpn_phy        TEXT(16) COLLATE NOCASE NOT NULL DEFAULT '',
            chpid           TEXT(2)  COLLATE NOCASE NOT NULL DEFAULT '',
            pchid           TEXT(4)  COLLATE NOCASE NOT NULL DEFAULT '',
            state           TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            owner           TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            tmpl_id         TEXT(32) COLLATE NOCASE NOT NULL DEFAULT '',
            PRIMARY KEY (fcp_id, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO fcp_new"
                " SELECT fcp_id, :nid, assigner_id, connections, reserved,"
                "        wwpn_npiv, wwpn_phy, chpid, pchid, state, owner, tmpl_id"
                " FROM fcp"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE fcp"))
    bind.execute(sa.text("ALTER TABLE fcp_new RENAME TO fcp"))

    # template: PK (id) → (id, compute_node_id)
    bind.execute(sa.text("""
        CREATE TABLE template_new (
            id                  TEXT(32)  COLLATE NOCASE NOT NULL,
            compute_node_id     TEXT(64)                 NOT NULL DEFAULT '',
            name                TEXT(128) COLLATE NOCASE NOT NULL,
            description         TEXT(255) COLLATE NOCASE NOT NULL DEFAULT '',
            is_default          INTEGER                  NOT NULL DEFAULT 0,
            min_fcp_paths_count INTEGER                  NOT NULL DEFAULT -1,
            PRIMARY KEY (id, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO template_new"
                " SELECT id, :nid, name, description, is_default, min_fcp_paths_count"
                " FROM template"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE template"))
    bind.execute(sa.text("ALTER TABLE template_new RENAME TO template"))

    # template_sp_mapping: PK (sp_name) → (sp_name, compute_node_id)
    bind.execute(sa.text("""
        CREATE TABLE template_sp_mapping_new (
            sp_name         TEXT(128) COLLATE NOCASE NOT NULL,
            tmpl_id         TEXT(32)  COLLATE NOCASE NOT NULL,
            compute_node_id TEXT(64)                 NOT NULL DEFAULT '',
            PRIMARY KEY (sp_name, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO template_sp_mapping_new"
                " SELECT sp_name, tmpl_id, :nid"
                " FROM template_sp_mapping"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE template_sp_mapping"))
    bind.execute(sa.text(
        "ALTER TABLE template_sp_mapping_new RENAME TO template_sp_mapping"
    ))

    # template_fcp_mapping: PK (fcp_id, tmpl_id) → (fcp_id, tmpl_id, compute_node_id)
    bind.execute(sa.text("""
        CREATE TABLE template_fcp_mapping_new (
            fcp_id          TEXT(4)  COLLATE NOCASE NOT NULL,
            tmpl_id         TEXT(32) COLLATE NOCASE NOT NULL,
            compute_node_id TEXT(64)                NOT NULL DEFAULT '',
            path            INTEGER                 NOT NULL,
            PRIMARY KEY (fcp_id, tmpl_id, compute_node_id)
        )
    """))
    bind.execute(
        sa.text("INSERT INTO template_fcp_mapping_new"
                " SELECT fcp_id, tmpl_id, :nid, path"
                " FROM template_fcp_mapping"),
        {'nid': node_id},
    )
    bind.execute(sa.text("DROP TABLE template_fcp_mapping"))
    bind.execute(sa.text(
        "ALTER TABLE template_fcp_mapping_new RENAME TO template_fcp_mapping"
    ))


def _downgrade_sqlite(bind) -> None:
    """Recreate all 7 data tables for SQLite, removing compute_node_id."""

    bind.execute(sa.text("""
        CREATE TABLE switch_old (
            userid    TEXT(8)   NOT NULL,
            interface TEXT(4)   NOT NULL,
            switch    TEXT(8),
            port      TEXT(128),
            comments  TEXT(128),
            PRIMARY KEY (userid, interface)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO switch_old SELECT userid, interface, switch, port, comments FROM switch"
    ))
    bind.execute(sa.text("DROP TABLE switch"))
    bind.execute(sa.text("ALTER TABLE switch_old RENAME TO switch"))

    bind.execute(sa.text("""
        CREATE TABLE guests_old (
            id       TEXT(36)  NOT NULL,
            userid   TEXT(8)   NOT NULL,
            metadata TEXT(255),
            net_set  INTEGER   NOT NULL DEFAULT 0,
            comments TEXT,
            PRIMARY KEY (id),
            UNIQUE (userid)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO guests_old SELECT id, userid, metadata, net_set, comments FROM guests"
    ))
    bind.execute(sa.text("DROP TABLE guests"))
    bind.execute(sa.text("ALTER TABLE guests_old RENAME TO guests"))

    bind.execute(sa.text("""
        CREATE TABLE image_old (
            imagename           TEXT(128) NOT NULL,
            imageosdistro       TEXT(16),
            md5sum              TEXT(512),
            disk_size_units     TEXT(512),
            image_size_in_bytes TEXT(512),
            type                TEXT(16),
            comments            TEXT(128),
            PRIMARY KEY (imagename)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO image_old"
        " SELECT imagename, imageosdistro, md5sum,"
        "        disk_size_units, image_size_in_bytes, type, comments"
        " FROM image"
    ))
    bind.execute(sa.text("DROP TABLE image"))
    bind.execute(sa.text("ALTER TABLE image_old RENAME TO image"))

    bind.execute(sa.text("""
        CREATE TABLE fcp_old (
            fcp_id      TEXT(4)  COLLATE NOCASE NOT NULL,
            assigner_id TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            connections INTEGER                 NOT NULL DEFAULT 0,
            reserved    INTEGER                 NOT NULL DEFAULT 0,
            wwpn_npiv   TEXT(16) COLLATE NOCASE NOT NULL DEFAULT '',
            wwpn_phy    TEXT(16) COLLATE NOCASE NOT NULL DEFAULT '',
            chpid       TEXT(2)  COLLATE NOCASE NOT NULL DEFAULT '',
            pchid       TEXT(4)  COLLATE NOCASE NOT NULL DEFAULT '',
            state       TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            owner       TEXT(8)  COLLATE NOCASE NOT NULL DEFAULT '',
            tmpl_id     TEXT(32) COLLATE NOCASE NOT NULL DEFAULT '',
            PRIMARY KEY (fcp_id)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO fcp_old"
        " SELECT fcp_id, assigner_id, connections, reserved,"
        "        wwpn_npiv, wwpn_phy, chpid, pchid, state, owner, tmpl_id"
        " FROM fcp"
    ))
    bind.execute(sa.text("DROP TABLE fcp"))
    bind.execute(sa.text("ALTER TABLE fcp_old RENAME TO fcp"))

    bind.execute(sa.text("""
        CREATE TABLE template_old (
            id                  TEXT(32)  COLLATE NOCASE NOT NULL,
            name                TEXT(128) COLLATE NOCASE NOT NULL,
            description         TEXT(255) COLLATE NOCASE NOT NULL DEFAULT '',
            is_default          INTEGER                  NOT NULL DEFAULT 0,
            min_fcp_paths_count INTEGER                  NOT NULL DEFAULT -1,
            PRIMARY KEY (id)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO template_old"
        " SELECT id, name, description, is_default, min_fcp_paths_count FROM template"
    ))
    bind.execute(sa.text("DROP TABLE template"))
    bind.execute(sa.text("ALTER TABLE template_old RENAME TO template"))

    bind.execute(sa.text("""
        CREATE TABLE template_sp_mapping_old (
            sp_name TEXT(128) COLLATE NOCASE NOT NULL,
            tmpl_id TEXT(32)  COLLATE NOCASE NOT NULL,
            PRIMARY KEY (sp_name)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO template_sp_mapping_old SELECT sp_name, tmpl_id FROM template_sp_mapping"
    ))
    bind.execute(sa.text("DROP TABLE template_sp_mapping"))
    bind.execute(sa.text(
        "ALTER TABLE template_sp_mapping_old RENAME TO template_sp_mapping"
    ))

    bind.execute(sa.text("""
        CREATE TABLE template_fcp_mapping_old (
            fcp_id  TEXT(4)  COLLATE NOCASE NOT NULL,
            tmpl_id TEXT(32) COLLATE NOCASE NOT NULL,
            path    INTEGER                 NOT NULL,
            PRIMARY KEY (fcp_id, tmpl_id)
        )
    """))
    bind.execute(sa.text(
        "INSERT INTO template_fcp_mapping_old"
        " SELECT fcp_id, tmpl_id, path FROM template_fcp_mapping"
    ))
    bind.execute(sa.text("DROP TABLE template_fcp_mapping"))
    bind.execute(sa.text(
        "ALTER TABLE template_fcp_mapping_old RENAME TO template_fcp_mapping"
    ))


# ---------------------------------------------------------------------------
# MariaDB/MySQL helpers — ALTER TABLE in place
# ---------------------------------------------------------------------------

def _upgrade_mariadb(bind, node_id: str) -> None:
    """Add compute_node_id to all data tables for MariaDB/MySQL."""

    # switch
    op.add_column('switch',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE switch SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text(
        "ALTER TABLE switch DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (userid, interface, compute_node_id)"
    ))

    # guests — PK stays (id), but unique constraint changes
    op.add_column('guests',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE guests SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text("ALTER TABLE guests DROP INDEX uq_guests_userid"))
    bind.execute(sa.text(
        "ALTER TABLE guests"
        " ADD UNIQUE KEY uq_guests_userid_node (userid, compute_node_id)"
    ))

    # image — default 'GLOBAL', no explicit backfill needed
    op.add_column('image',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default='GLOBAL'))
    bind.execute(sa.text(
        "ALTER TABLE image DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (imagename, compute_node_id)"
    ))

    # fcp
    op.add_column('fcp',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE fcp SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text(
        "ALTER TABLE fcp DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (fcp_id, compute_node_id)"
    ))

    # template
    op.add_column('template',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE template SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text(
        "ALTER TABLE template DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (id, compute_node_id)"
    ))

    # template_sp_mapping
    op.add_column('template_sp_mapping',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE template_sp_mapping SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text(
        "ALTER TABLE template_sp_mapping DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (sp_name, compute_node_id)"
    ))

    # template_fcp_mapping
    op.add_column('template_fcp_mapping',
        sa.Column('compute_node_id', sa.String(64), nullable=False,
                  server_default=''))
    bind.execute(
        sa.text("UPDATE template_fcp_mapping SET compute_node_id = :nid"),
        {'nid': node_id},
    )
    bind.execute(sa.text(
        "ALTER TABLE template_fcp_mapping DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (fcp_id, tmpl_id, compute_node_id)"
    ))


def _downgrade_mariadb(bind) -> None:
    """Remove compute_node_id from all data tables for MariaDB/MySQL."""

    bind.execute(sa.text(
        "ALTER TABLE template_fcp_mapping DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (fcp_id, tmpl_id)"
    ))
    op.drop_column('template_fcp_mapping', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE template_sp_mapping DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (sp_name)"
    ))
    op.drop_column('template_sp_mapping', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE template DROP PRIMARY KEY, ADD PRIMARY KEY (id)"
    ))
    op.drop_column('template', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE fcp DROP PRIMARY KEY, ADD PRIMARY KEY (fcp_id)"
    ))
    op.drop_column('fcp', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE image DROP PRIMARY KEY, ADD PRIMARY KEY (imagename)"
    ))
    op.drop_column('image', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE guests DROP INDEX uq_guests_userid_node"
    ))
    bind.execute(sa.text(
        "ALTER TABLE guests ADD UNIQUE KEY uq_guests_userid (userid)"
    ))
    op.drop_column('guests', 'compute_node_id')

    bind.execute(sa.text(
        "ALTER TABLE switch DROP PRIMARY KEY,"
        " ADD PRIMARY KEY (userid, interface)"
    ))
    op.drop_column('switch', 'compute_node_id')


# ---------------------------------------------------------------------------
# Public upgrade / downgrade entry points
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    node_id = _get_node_id()

    # Step 1: Create compute_nodes registry (both backends).
    mysql_kw = _MYSQL_ARGS if dialect in ('mysql', 'mariadb') else {}
    op.create_table(
        'compute_nodes',
        sa.Column('id',            sa.String(64),  nullable=False),
        sa.Column('hostname',      sa.String(255), nullable=False),
        sa.Column('ip_address',    sa.String(45),  nullable=False),
        sa.Column('zvm_host',      sa.String(255)),
        sa.Column('registered_at', sa.DateTime,    server_default=sa.func.now()),
        sa.Column('last_seen',     sa.DateTime,    server_default=sa.func.now()),
        sa.Column('status',        sa.String(16),  nullable=False,
                  server_default='active'),
        sa.PrimaryKeyConstraint('id'),
        **mysql_kw,
    )

    # Step 2: Extend data tables with compute_node_id.
    if dialect in ('mysql', 'mariadb'):
        _upgrade_mariadb(bind, node_id)
    else:
        _recreate_sqlite(bind, node_id)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect in ('mysql', 'mariadb'):
        _downgrade_mariadb(bind)
    else:
        _downgrade_sqlite(bind)

    op.drop_table('compute_nodes')
