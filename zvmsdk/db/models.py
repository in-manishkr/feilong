#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

# Copyright 2017-2024 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Database table definitions using SQLAlchemy Core.

This module defines all database tables using SQLAlchemy Core (not ORM).
This approach provides:
- Database backend independence
- Migration support via Alembic
- Type safety and validation
- Backward compatibility with raw SQL queries
"""

from sqlalchemy import (
    MetaData, Table, Column,
    String, Integer, SmallInteger, Text, Boolean,
    PrimaryKeyConstraint, UniqueConstraint, Index
)

# Naming convention for constraints (required for Alembic)
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Global metadata object
metadata = MetaData(naming_convention=naming_convention)


# ============================================================================
# Network Database Tables
# ============================================================================

switch_table = Table(
    'switch',
    metadata,
    Column('userid', String(8), nullable=False, index=True,
           comment='z/VM user ID'),
    Column('interface', String(4), nullable=False,
           comment='Network interface device number'),
    Column('switch', String(8), nullable=True,
           comment='Virtual switch name'),
    Column('port', String(128), nullable=True,
           comment='Network port identifier'),
    Column('comments', String(128), nullable=True,
           comment='Additional comments'),
    PrimaryKeyConstraint('userid', 'interface', name='pk_switch'),
    comment='Network switch configuration for virtual machines'
)


# ============================================================================
# Image Database Tables
# ============================================================================

image_table = Table(
    'image',
    metadata,
    Column('imagename', String(128), primary_key=True,
           comment='Unique image name'),
    Column('imageosdistro', String(16), nullable=True,
           comment='Operating system distribution'),
    Column('md5sum', String(512), nullable=True,
           comment='MD5 checksum of the image'),
    Column('disk_size_units', String(512), nullable=True,
           comment='Disk size with units'),
    Column('image_size_in_bytes', String(512), nullable=True,
           comment='Image size in bytes'),
    Column('type', String(16), nullable=True,
           comment='Image type'),
    Column('comments', String(128), nullable=True,
           comment='Additional comments'),
    comment='Image metadata and properties'
)


# ============================================================================
# Guest Database Tables
# ============================================================================

guests_table = Table(
    'guests',
    metadata,
    Column('id', String(36), primary_key=True,
           comment='Unique guest UUID'),
    Column('userid', String(8), nullable=False, unique=True, index=True,
           comment='z/VM user ID'),
    Column('metadata', String(255), nullable=True,
           comment='Guest metadata in JSON format'),
    Column('net_set', SmallInteger, nullable=False, default=0,
           comment='Network configuration status: 0=not configured, 1=configured'),
    Column('comments', Text, nullable=True,
           comment='Additional comments'),
    comment='Virtual machine guest information'
)


# ============================================================================
# FCP Database Tables
# ============================================================================

fcp_table = Table(
    'fcp',
    metadata,
    Column('fcp_id', String(4), primary_key=True,
           comment='FCP device ID (4-character hex)'),
    Column('assigner_id', String(8), nullable=False, default='', index=True,
           comment='VM user ID that this FCP is assigned to'),
    Column('connections', Integer, nullable=False, default=0,
           comment='Number of active connections using this FCP'),
    Column('reserved', Integer, nullable=False, default=0,
           comment='Reserved status: 0=not reserved, 1=reserved'),
    Column('wwpn_npiv', String(16), nullable=False, default='',
           comment='NPIV World Wide Port Name'),
    Column('wwpn_phy', String(16), nullable=False, default='',
           comment='Physical World Wide Port Name'),
    Column('chpid', String(2), nullable=False, default='',
           comment='Channel path ID'),
    Column('pchid', String(4), nullable=False, default='', index=True,
           comment='Physical channel ID'),
    Column('state', String(8), nullable=False, default='',
           comment='FCP device state'),
    Column('owner', String(8), nullable=False, default='',
           comment='VM user ID that owns this FCP device'),
    Column('tmpl_id', String(32), nullable=False, default='', index=True,
           comment='Template ID this FCP was allocated from'),
    comment='FCP (Fibre Channel Protocol) device information'
)

# Index for common query patterns
Index('ix_fcp_assigner_tmpl', fcp_table.c.assigner_id, fcp_table.c.tmpl_id)


template_table = Table(
    'template',
    metadata,
    Column('id', String(32), primary_key=True,
           comment='Unique template ID'),
    Column('name', String(128), nullable=False, unique=True,
           comment='Template name'),
    Column('description', String(255), nullable=False, default='',
           comment='Template description'),
    Column('is_default', Integer, nullable=False, default=0,
           comment='Default template flag: 0=no, 1=yes'),
    Column('min_fcp_paths_count', Integer, nullable=False, default=-1,
           comment='Minimum FCP path count: -1=same as template path count'),
    comment='FCP multipath templates'
)


template_sp_mapping_table = Table(
    'template_sp_mapping',
    metadata,
    Column('sp_name', String(128), primary_key=True,
           comment='Storage provider name'),
    Column('tmpl_id', String(32), nullable=False, index=True,
           comment='Template ID'),
    comment='Mapping between storage providers and FCP templates'
)


template_fcp_mapping_table = Table(
    'template_fcp_mapping',
    metadata,
    Column('fcp_id', String(4), nullable=False,
           comment='FCP device ID'),
    Column('tmpl_id', String(32), nullable=False, index=True,
           comment='Template ID'),
    Column('path', Integer, nullable=False,
           comment='Path number (0, 1, 2, ...)'),
    PrimaryKeyConstraint('fcp_id', 'tmpl_id', name='pk_template_fcp_mapping'),
    comment='Mapping between FCP devices and templates with path information'
)

# Index for path queries
Index('ix_template_fcp_mapping_tmpl_path', 
      template_fcp_mapping_table.c.tmpl_id, 
      template_fcp_mapping_table.c.path)


# ============================================================================
# Helper Functions
# ============================================================================

def get_tables_by_database_type(db_type: str) -> list:
    """
    Get list of tables for a specific database type.
    
    Args:
        db_type: Database type ('network', 'image', 'guest', 'fcp')
    
    Returns:
        List of Table objects for the specified database type
    """
    table_mapping = {
        'network': [switch_table],
        'image': [image_table],
        'guest': [guests_table],
        'fcp': [fcp_table, template_table, template_sp_mapping_table, 
                template_fcp_mapping_table],
    }
    
    return table_mapping.get(db_type, [])


def create_all_tables(engine, db_type: str = None):
    """
    Create all tables in the database.
    
    Args:
        engine: SQLAlchemy engine instance
        db_type: Specific database type, or None to create all tables
    """
    if db_type:
        tables = get_tables_by_database_type(db_type)
        for table in tables:
            table.create(engine, checkfirst=True)
    else:
        metadata.create_all(engine, checkfirst=True)


def drop_all_tables(engine, db_type: str = None):
    """
    Drop all tables from the database.
    
    WARNING: This will delete all data!
    
    Args:
        engine: SQLAlchemy engine instance
        db_type: Specific database type, or None to drop all tables
    """
    if db_type:
        tables = get_tables_by_database_type(db_type)
        for table in reversed(tables):  # Reverse order for foreign keys
            table.drop(engine, checkfirst=True)
    else:
        metadata.drop_all(engine, checkfirst=True)


# ============================================================================
# Table Registry
# ============================================================================

# Export all tables for easy access
__all__ = [
    'metadata',
    'switch_table',
    'image_table',
    'guests_table',
    'fcp_table',
    'template_table',
    'template_sp_mapping_table',
    'template_fcp_mapping_table',
    'get_tables_by_database_type',
    'create_all_tables',
    'drop_all_tables',
]

# Made with Bob
