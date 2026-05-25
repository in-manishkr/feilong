#!/usr/bin/env python3
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
Migrate data from SQLite to remote database.

This script migrates existing data from SQLite databases to a remote
MySQL/MariaDB database. It preserves all data and relationships.

Usage:
    python scripts/migrate_data.py [--sqlite-dir /path/to/sqlite]

Arguments:
    --sqlite-dir    Path to SQLite database directory
                    (default: /var/lib/zvmsdk)
"""

import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zvmsdk import config
from zvmsdk.db import engine, models
from sqlalchemy import create_engine, select


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_success(text):
    """Print success message."""
    print(f"✓ {text}")


def print_error(text):
    """Print error message."""
    print(f"✗ {text}")


def print_info(text):
    """Print info message."""
    print(f"ℹ {text}")


def migrate_database(db_type, sqlite_path):
    """
    Migrate data from SQLite to remote database.
    
    Args:
        db_type: Database type (network, image, guest, fcp)
        sqlite_path: Path to SQLite database file
    
    Returns:
        Number of rows migrated
    """
    print(f"\n{db_type.upper()} Database:")
    print("-" * 40)
    
    # Check if SQLite file exists
    if not os.path.exists(sqlite_path):
        print_info(f"SQLite file not found: {sqlite_path}")
        print_info("Skipping migration (no data to migrate)")
        return 0
    
    # Create SQLite engine
    sqlite_engine = create_engine(f'sqlite:///{sqlite_path}')
    
    # Get remote engine
    remote_engine = engine.get_engine(db_type)
    
    # Get tables
    tables = models.get_tables_by_database_type(db_type)
    
    total_rows = 0
    
    for table in tables:
        print(f"\nTable: {table.name}")
        
        try:
            # Read from SQLite
            with sqlite_engine.connect() as sqlite_conn:
                result = sqlite_conn.execute(select(table))
                rows = result.fetchall()
                
                if not rows:
                    print_info("  No data to migrate")
                    continue
                
                print_info(f"  Found {len(rows)} rows")
                
                # Write to remote database
                with remote_engine.connect() as remote_conn:
                    # Convert rows to dictionaries
                    data = [dict(row._mapping) for row in rows]
                    
                    # Insert data
                    remote_conn.execute(table.insert(), data)
                    remote_conn.commit()
                    
                    print_success(f"  Migrated {len(rows)} rows")
                    total_rows += len(rows)
                    
        except Exception as e:
            print_error(f"  Failed to migrate table {table.name}: {e}")
            raise
    
    return total_rows


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description='Migrate data from SQLite to remote database'
    )
    parser.add_argument(
        '--sqlite-dir',
        default='/var/lib/zvmsdk',
        help='Path to SQLite database directory (default: /var/lib/zvmsdk)'
    )
    
    args = parser.parse_args()
    
    try:
        print_header("Feilong Database Migration Tool")
        
        # Initialize configuration
        config.CONF = config.ConfigOpts()
        
        # Verify remote database configuration
        backend = config.CONF.database.backend
        if backend == 'sqlite':
            print_error("Target database is SQLite - migration not needed")
            print_info("Configure a remote database (mysql/mariadb) first")
            return 1
        
        print_info(f"Target database: {backend}")
        print_info(f"SQLite source directory: {args.sqlite_dir}")
        
        # Database mappings
        migrations = [
            ('network', os.path.join(args.sqlite_dir, 'network.db')),
            ('image', os.path.join(args.sqlite_dir, 'image.db')),
            ('guest', os.path.join(args.sqlite_dir, 'guests.db')),
            ('fcp', os.path.join(args.sqlite_dir, 'fcp.db')),
        ]
        
        print_header("Starting Data Migration")
        
        total_rows = 0
        migrated_dbs = 0
        
        for db_type, sqlite_path in migrations:
            try:
                rows = migrate_database(db_type, sqlite_path)
                if rows > 0:
                    total_rows += rows
                    migrated_dbs += 1
            except Exception as e:
                print_error(f"Failed to migrate {db_type}: {e}")
                import traceback
                traceback.print_exc()
                return 1
        
        print_header("Migration Complete")
        print_success(f"Migrated {total_rows} rows from {migrated_dbs} databases")
        
        print("\n" + "=" * 60)
        print("Next Steps:")
        print("1. Verify data in remote database")
        print("2. Test application with remote database")
        print("3. Backup SQLite files")
        print("4. Update configuration to use remote database")
        print("=" * 60)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return 1
    except Exception as e:
        print_error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
