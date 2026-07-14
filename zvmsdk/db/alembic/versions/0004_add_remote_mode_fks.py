"""Add FK constraints from data tables to compute_nodes for remote mode.

This migration is a no-op when database.mode != 'remote'. In local mode it
records the revision without touching schema, so it can be safely applied at
any time without breaking single-node deployments.

Manual rollback (remote mode only):
  ALTER TABLE fcp DROP FOREIGN KEY fk_fcp_node;
  ALTER TABLE switch DROP FOREIGN KEY fk_switch_node;
  ALTER TABLE guests DROP FOREIGN KEY fk_guests_node;
  ALTER TABLE template DROP FOREIGN KEY fk_template_node;
  ALTER TABLE template_sp_mapping DROP FOREIGN KEY fk_tmpl_sp_node;
  ALTER TABLE template_fcp_mapping DROP FOREIGN KEY fk_tmpl_fcp_node;
  Then stamp back: alembic stamp 0003

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_remote_mode() -> bool:
    try:
        from zvmsdk import config
        return getattr(config.CONF.database, 'mode', 'local') == 'remote'
    except Exception:
        return False


def upgrade() -> None:
    if not _is_remote_mode():
        return

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ('mysql', 'mariadb'):
        # SQLite does not enforce FK constraints in the same way; skip.
        return

    op.create_foreign_key(
        'fk_fcp_node', 'fcp', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(
        'fk_switch_node', 'switch', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(
        'fk_guests_node', 'guests', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(
        'fk_template_node', 'template', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(
        'fk_tmpl_sp_node', 'template_sp_mapping', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(
        'fk_tmpl_fcp_node', 'template_fcp_mapping', 'compute_nodes',
        ['compute_node_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    if not _is_remote_mode():
        return

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ('mysql', 'mariadb'):
        return

    op.drop_constraint('fk_tmpl_fcp_node', 'template_fcp_mapping',
                       type_='foreignkey')
    op.drop_constraint('fk_tmpl_sp_node', 'template_sp_mapping',
                       type_='foreignkey')
    op.drop_constraint('fk_template_node', 'template', type_='foreignkey')
    op.drop_constraint('fk_guests_node', 'guests', type_='foreignkey')
    op.drop_constraint('fk_switch_node', 'switch', type_='foreignkey')
    op.drop_constraint('fk_fcp_node', 'fcp', type_='foreignkey')
