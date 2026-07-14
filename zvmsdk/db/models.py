#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

from sqlalchemy import (
    MetaData, Table, Column,
    String, Integer, SmallInteger, Text, DateTime, Boolean,
    PrimaryKeyConstraint, UniqueConstraint,
    ForeignKeyConstraint, func,
)

metadata = MetaData()

# ---------------------------------------------------------------------------
# compute_nodes — registry of all feilong compute nodes (new table, Phase 5)
# ---------------------------------------------------------------------------
compute_nodes = Table('compute_nodes', metadata,
    Column('id',            String(64),  nullable=False),
    Column('hostname',      String(255), nullable=False),
    Column('ip_address',    String(45),  nullable=False),
    Column('zvm_host',      String(255)),
    Column('registered_at', DateTime,    server_default=func.now()),
    Column('last_seen',     DateTime,    server_default=func.now(),
                                         onupdate=func.now()),
    Column('status',        String(16),  nullable=False,
                                         server_default='active'),
    PrimaryKeyConstraint('id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

# ---------------------------------------------------------------------------
# guests
# ---------------------------------------------------------------------------
guests = Table('guests', metadata,
    Column('id',              String(36),   nullable=False),
    Column('userid',          String(8),    nullable=False),
    Column('compute_node_id', String(64),   nullable=False, server_default=''),
    Column('metadata',        String(255)),
    Column('net_set',         SmallInteger, nullable=False, server_default='0'),
    Column('comments',        Text),
    PrimaryKeyConstraint('id'),
    UniqueConstraint('userid', 'compute_node_id', name='uq_guests_userid_node'),
    # FK to compute_nodes is NOT declared here; added by migration 0004 in
    # remote mode only (see proposed_architecture.md §5.2 FK strategy).
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

# ---------------------------------------------------------------------------
# switch (network)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# image
# PK is (imagename, compute_node_id) so two nodes can hold same-named local
# images without colliding. 'GLOBAL' sentinel = shared/cross-node image.
# ---------------------------------------------------------------------------
image = Table('image', metadata,
    Column('imagename',           String(128), nullable=False),
    Column('compute_node_id',     String(64),  nullable=False,
                                               server_default='GLOBAL'),
    Column('imageosdistro',       String(16)),
    Column('md5sum',              String(512)),
    Column('disk_size_units',     String(512)),
    Column('image_size_in_bytes', String(512)),
    Column('type',                String(16)),
    Column('comments',            String(128)),
    PrimaryKeyConstraint('imagename', 'compute_node_id'),
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

# ---------------------------------------------------------------------------
# fcp
# ---------------------------------------------------------------------------
fcp = Table('fcp', metadata,
    Column('fcp_id',          String(4),  nullable=False),
    Column('compute_node_id', String(64), nullable=False, server_default=''),
    Column('assigner_id',     String(8),  nullable=False, server_default=''),
    Column('connections',     Integer,    nullable=False, server_default='0'),
    Column('reserved',        Integer,    nullable=False, server_default='0'),
    Column('wwpn_npiv',       String(16), nullable=False, server_default=''),
    Column('wwpn_phy',        String(16), nullable=False, server_default=''),
    Column('chpid',           String(2),  nullable=False, server_default=''),
    Column('pchid',           String(4),  nullable=False, server_default=''),
    Column('state',           String(8),  nullable=False, server_default=''),
    Column('owner',           String(8),  nullable=False, server_default=''),
    Column('tmpl_id',         String(32), nullable=False, server_default=''),
    PrimaryKeyConstraint('fcp_id', 'compute_node_id'),
    # FK to compute_nodes added by migration 0004 in remote mode only.
    mysql_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_general_ci',
)

# ---------------------------------------------------------------------------
# template (FCP Multipath Template)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# template_sp_mapping  (storage-provider → template)
# FK ensures each SP mapping references a real template on the same node.
# Deleting a template cascades to remove its SP mappings.
# ---------------------------------------------------------------------------
template_sp_mapping = Table('template_sp_mapping', metadata,
    Column('sp_name',         String(128), nullable=False),
    Column('tmpl_id',         String(32),  nullable=False),
    Column('compute_node_id', String(64),  nullable=False, server_default=''),
    PrimaryKeyConstraint('sp_name', 'compute_node_id'),
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

# ---------------------------------------------------------------------------
# template_fcp_mapping  (template → FCP devices per path)
# Two FKs: to template (cascade on template delete) and to fcp (cascade on
# FCP device delete).
# ---------------------------------------------------------------------------
template_fcp_mapping = Table('template_fcp_mapping', metadata,
    Column('fcp_id',          String(4),  nullable=False),
    Column('tmpl_id',         String(32), nullable=False),
    Column('compute_node_id', String(64), nullable=False, server_default=''),
    Column('path',            Integer,    nullable=False),
    PrimaryKeyConstraint('fcp_id', 'tmpl_id', 'compute_node_id'),
    ForeignKeyConstraint(
        ['tmpl_id', 'compute_node_id'],
        ['template.id', 'template.compute_node_id'],
        ondelete='CASCADE',
        name='fk_fcp_mapping_template',
    ),
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
