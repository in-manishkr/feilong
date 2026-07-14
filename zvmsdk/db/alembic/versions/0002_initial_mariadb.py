"""Initial MariaDB/MySQL baseline — 7 tables, no compute_node_id.

Creates all data tables for a fresh MariaDB/MySQL installation using
InnoDB engine, utf8mb4 charset, and utf8mb4_general_ci collation.
This migration is a no-op for SQLite (tables already exist from 0001).

For a fresh MariaDB install, migration.py stamps revision 0001 before
calling upgrade('head'), which causes this migration to run and create
all tables.

Rollback: run downgrade() — drops all 7 tables.
          Back up before running in production.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MYSQL_ARGS = dict(
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in ('mysql', 'mariadb'):
        return  # SQLite already has these tables from 0001

    op.create_table(
        'switch',
        sa.Column('userid',    sa.String(8),   nullable=False),
        sa.Column('interface', sa.String(4),   nullable=False),
        sa.Column('switch',    sa.String(8)),
        sa.Column('port',      sa.String(128)),
        sa.Column('comments',  sa.String(128)),
        sa.PrimaryKeyConstraint('userid', 'interface'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'guests',
        sa.Column('id',       sa.String(36),   nullable=False),
        sa.Column('userid',   sa.String(8),    nullable=False),
        sa.Column('metadata', sa.String(255)),
        sa.Column('net_set',  sa.SmallInteger, nullable=False,
                  server_default='0'),
        sa.Column('comments', sa.Text),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('userid', name='uq_guests_userid'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'image',
        sa.Column('imagename',           sa.String(128), nullable=False),
        sa.Column('imageosdistro',       sa.String(16)),
        sa.Column('md5sum',              sa.String(512)),
        sa.Column('disk_size_units',     sa.String(512)),
        sa.Column('image_size_in_bytes', sa.String(512)),
        sa.Column('type',                sa.String(16)),
        sa.Column('comments',            sa.String(128)),
        sa.PrimaryKeyConstraint('imagename'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'fcp',
        sa.Column('fcp_id',      sa.String(4),  nullable=False),
        sa.Column('assigner_id', sa.String(8),  nullable=False,
                  server_default=''),
        sa.Column('connections', sa.Integer,    nullable=False,
                  server_default='0'),
        sa.Column('reserved',    sa.Integer,    nullable=False,
                  server_default='0'),
        sa.Column('wwpn_npiv',   sa.String(16), nullable=False,
                  server_default=''),
        sa.Column('wwpn_phy',    sa.String(16), nullable=False,
                  server_default=''),
        sa.Column('chpid',       sa.String(2),  nullable=False,
                  server_default=''),
        sa.Column('pchid',       sa.String(4),  nullable=False,
                  server_default=''),
        sa.Column('state',       sa.String(8),  nullable=False,
                  server_default=''),
        sa.Column('owner',       sa.String(8),  nullable=False,
                  server_default=''),
        sa.Column('tmpl_id',     sa.String(32), nullable=False,
                  server_default=''),
        sa.PrimaryKeyConstraint('fcp_id'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'template',
        sa.Column('id',                  sa.String(32),  nullable=False),
        sa.Column('name',                sa.String(128), nullable=False),
        sa.Column('description',         sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('is_default',          sa.Integer,     nullable=False,
                  server_default='0'),
        sa.Column('min_fcp_paths_count', sa.Integer,     nullable=False,
                  server_default='-1'),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'template_sp_mapping',
        sa.Column('sp_name', sa.String(128), nullable=False),
        sa.Column('tmpl_id', sa.String(32),  nullable=False),
        sa.PrimaryKeyConstraint('sp_name'),
        **_MYSQL_ARGS,
    )
    op.create_table(
        'template_fcp_mapping',
        sa.Column('fcp_id',  sa.String(4),  nullable=False),
        sa.Column('tmpl_id', sa.String(32), nullable=False),
        sa.Column('path',    sa.Integer,    nullable=False),
        sa.PrimaryKeyConstraint('fcp_id', 'tmpl_id'),
        **_MYSQL_ARGS,
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in ('mysql', 'mariadb'):
        return  # SQLite tables are managed by 0001 downgrade
    # Drop in reverse dependency order (leaf → root).
    op.drop_table('template_fcp_mapping')
    op.drop_table('template_sp_mapping')
    op.drop_table('template')
    op.drop_table('fcp')
    op.drop_table('image')
    op.drop_table('guests')
    op.drop_table('switch')
