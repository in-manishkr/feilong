"""Initial SQLite baseline — current production schema without compute_node_id.

This migration establishes the alembic baseline that matches the schema
created by the original database.py code.  It is stamped (not run) on
existing SQLite installations that already have these tables; it is run
as-is on fresh SQLite installs.

Existing MariaDB installs get a separate baseline via 0002 (Phase 4).

Revision ID: 0001
Revises: (none)
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # switch — network port / vswitch assignments
    # ------------------------------------------------------------------
    op.create_table(
        'switch',
        sa.Column('userid',    sa.String(8),   nullable=False),
        sa.Column('interface', sa.String(4),   nullable=False),
        sa.Column('switch',    sa.String(8)),
        sa.Column('port',      sa.String(128)),
        sa.Column('comments',  sa.String(128)),
        sa.PrimaryKeyConstraint('userid', 'interface'),
    )

    # ------------------------------------------------------------------
    # guests — managed z/VM guest VMs
    # ------------------------------------------------------------------
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
    )

    # ------------------------------------------------------------------
    # image — captured z/VM images
    # ------------------------------------------------------------------
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
    )

    # ------------------------------------------------------------------
    # fcp — FCP (Fibre Channel Protocol) device inventory
    # COLLATE NOCASE mirrors the original schema so that FCP IDs like
    # '1a01' and '1A01' are treated as equivalent.
    # ------------------------------------------------------------------
    op.create_table(
        'fcp',
        sa.Column('fcp_id',      sa.String(4,  collation='NOCASE'), nullable=False),
        sa.Column('assigner_id', sa.String(8,  collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('connections', sa.Integer,    nullable=False,
                  server_default='0'),
        sa.Column('reserved',    sa.Integer,    nullable=False,
                  server_default='0'),
        sa.Column('wwpn_npiv',   sa.String(16, collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('wwpn_phy',    sa.String(16, collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('chpid',       sa.String(2,  collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('pchid',       sa.String(4,  collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('state',       sa.String(8,  collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('owner',       sa.String(8,  collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('tmpl_id',     sa.String(32, collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.PrimaryKeyConstraint('fcp_id'),
    )

    # ------------------------------------------------------------------
    # template — FCP multipath templates
    # ------------------------------------------------------------------
    op.create_table(
        'template',
        sa.Column('id',                  sa.String(32,  collation='NOCASE'), nullable=False),
        sa.Column('name',                sa.String(128, collation='NOCASE'), nullable=False),
        sa.Column('description',         sa.String(255, collation='NOCASE'), nullable=False,
                  server_default=''),
        sa.Column('is_default',          sa.Integer,     nullable=False,
                  server_default='0'),
        sa.Column('min_fcp_paths_count', sa.Integer,     nullable=False,
                  server_default='-1'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------
    # template_sp_mapping — storage-provider → template association
    # No explicit FK in original schema (SQLite didn't enforce them).
    # ------------------------------------------------------------------
    op.create_table(
        'template_sp_mapping',
        sa.Column('sp_name', sa.String(128, collation='NOCASE'), nullable=False),
        sa.Column('tmpl_id', sa.String(32,  collation='NOCASE'), nullable=False),
        sa.PrimaryKeyConstraint('sp_name'),
    )

    # ------------------------------------------------------------------
    # template_fcp_mapping — FCP device → template + path association
    # ------------------------------------------------------------------
    op.create_table(
        'template_fcp_mapping',
        sa.Column('fcp_id',  sa.String(4,  collation='NOCASE'), nullable=False),
        sa.Column('tmpl_id', sa.String(32, collation='NOCASE'), nullable=False),
        sa.Column('path',    sa.Integer,    nullable=False),
        sa.PrimaryKeyConstraint('fcp_id', 'tmpl_id'),
    )


def downgrade() -> None:
    # Drop in reverse dependency order (leaf → root).
    op.drop_table('template_fcp_mapping')
    op.drop_table('template_sp_mapping')
    op.drop_table('template')
    op.drop_table('fcp')
    op.drop_table('image')
    op.drop_table('guests')
    op.drop_table('switch')
