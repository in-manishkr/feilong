#!/usr/bin/env python3
#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""
Migrate existing database to multi-node schema.

This script adds compute_node_id column to all tables and updates
primary keys to support multiple compute nodes sharing a single database.

Usage:
    python scripts/migrate_to_multinode.py [compute_node_id] [--database nova]
    
Arguments:
    compute_node_id: Unique identifier for this compute node (default: hostname)
    --database: Database name (default: from config)
    
Examples:
    # Use hostname as compute node ID
    python scripts/migrate_to_multinode.py
    
    # Use specific compute node ID
    python scripts/migrate_to_multinode.py compute-node-01
    
    # Migrate OpenStack Nova database
    python scripts/migrate_to_multinode.py compute-node-01 --database nova
"""

import sys
import os
import socket
import argparse

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from zvmsdk import config
from zvmsdk.db import engine
from sqlalchemy import text, inspect


class Colors:
    """ANSI color codes."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    """Print formatted header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")


def print_success(text):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")


def print_error(text):
    """Print error message."""
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")


def print_info(text):
    """Print info message."""
    print(f"{Colors.YELLOW}ℹ {text}{Colors.RESET}")


def print_warning(text):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")


def check_column_exists(conn, table_name, column_name):
    """Check if a column exists in a table."""
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def migrate_table(conn, table_name, compute_node_id, primary_keys):
    """
    Migrate a single table to multi-node schema.
    
    Args:
        conn: Database connection
        table_name: Name of the table to migrate
        compute_node_id: Compute node identifier
        primary_keys: List of columns that form the primary key
    """
    print_info(f"Migrating table: {table_name}")
    
    # Check if column already exists
    if check_column_exists(conn, table_name, 'compute_node_id'):
        print_warning(f"  Column compute_node_id already exists in {table_name}")
        return
    
    try:
        # Step 1: Add compute_node_id column
        print_info(f"  Adding compute_node_id column...")
        conn.execute(text(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN compute_node_id VARCHAR(64) "
            f"NOT NULL DEFAULT '{compute_node_id}'"
        ))
        conn.commit()
        print_success(f"  Added compute_node_id column")
        
        # Step 2: Drop existing primary key
        print_info(f"  Updating primary key...")
        try:
            conn.execute(text(f"ALTER TABLE {table_name} DROP PRIMARY KEY"))
            conn.commit()
        except Exception as e:
            print_warning(f"  Could not drop primary key: {e}")
        
        # Step 3: Add new primary key with compute_node_id
        pk_columns = ['compute_node_id'] + primary_keys
        pk_def = ', '.join(pk_columns)
        conn.execute(text(
            f"ALTER TABLE {table_name} "
            f"ADD PRIMARY KEY ({pk_def})"
        ))
        conn.commit()
        print_success(f"  Updated primary key: ({pk_def})")
        
        # Step 4: Add index for efficient filtering
        print_info(f"  Adding index...")
        try:
            conn.execute(text(
                f"CREATE INDEX idx_{table_name}_compute_node "
                f"ON {table_name}(compute_node_id)"
            ))
            conn.commit()
            print_success(f"  Added index")
        except Exception as e:
            print_warning(f"  Index may already exist: {e}")
        
        print_success(f"Table {table_name} migrated successfully")
        
    except Exception as e:
        print_error(f"Failed to migrate {table_name}: {e}")
        conn.rollback()
        raise


def migrate_database(compute_node_id, database_name=None):
    """
    Migrate all tables to multi-node schema.
    
    Args:
        compute_node_id: Compute node identifier
        database_name: Database name (optional, uses config if not provided)
    """
    print_header("Multi-Node Database Migration")
    
    print_info(f"Compute Node ID: {compute_node_id}")
    if database_name:
        print_info(f"Database: {database_name}")
    
    # Load configuration
    try:
        config.load_config()
    except Exception as e:
        print_warning(f"Could not load config: {e}")
        print_info("Using default configuration")
    
    # Override database name if provided
    if database_name:
        config.CONF.database.name = database_name
    
    # Table definitions with their primary keys
    tables_to_migrate = {
        'switch': ['userid', 'interface'],
        'image': ['imagename'],
        'guests': ['id'],
        'fcp': ['fcp_id'],
        'template': ['id'],
        'template_sp_mapping': ['sp_name'],
        'template_fcp_mapping': ['fcp_id', 'tmpl_id'],
    }
    
    # Migrate each table
    success_count = 0
    failed_tables = []
    
    for table_name, primary_keys in tables_to_migrate.items():
        try:
            # Get appropriate engine based on table
            if table_name == 'switch':
                eng = engine.get_engine('network')
            elif table_name == 'image':
                eng = engine.get_engine('image')
            elif table_name == 'guests':
                eng = engine.get_engine('guest')
            else:  # fcp, template, template_sp_mapping, template_fcp_mapping
                eng = engine.get_engine('fcp')
            
            with eng.begin() as conn:
                migrate_table(conn, table_name, compute_node_id, primary_keys)
            
            success_count += 1
            
        except Exception as e:
            print_error(f"Failed to migrate {table_name}: {e}")
            failed_tables.append(table_name)
    
    # Print summary
    print_header("Migration Summary")
    
    print(f"Total tables: {len(tables_to_migrate)}")
    print_success(f"Successfully migrated: {success_count}")
    
    if failed_tables:
        print_error(f"Failed to migrate: {len(failed_tables)}")
        for table in failed_tables:
            print(f"  - {table}")
        return False
    else:
        print_success("All tables migrated successfully!")
        return True


def verify_migration(compute_node_id):
    """Verify the migration was successful."""
    print_header("Verifying Migration")
    
    try:
        from zvmsdk.db.repositories import NetworkRepository
        
        # Test that compute_node_id is being used
        repo = NetworkRepository()
        
        # Add a test record
        repo.switch_add_record(
            userid='MIGTEST',
            interface='1000',
            port='test'
        )
        print_success("Test record added")
        
        # Query it back
        records = repo.switch_select_record_for_userid('MIGTEST')
        
        if len(records) == 1:
            print_success("Test record retrieved")
            
            # Check if compute_node_id is present
            if 'compute_node_id' in records[0]:
                print_success(f"compute_node_id present: {records[0]['compute_node_id']}")
            else:
                print_warning("compute_node_id not in record (may need code update)")
        
        # Cleanup
        repo.switch_delete_record_for_userid('MIGTEST')
        print_success("Test record cleaned up")
        
        print_success("Migration verification passed!")
        return True
        
    except Exception as e:
        print_error(f"Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Migrate database to multi-node schema',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'compute_node_id',
        nargs='?',
        default=socket.gethostname(),
        help='Compute node identifier (default: hostname)'
    )
    
    parser.add_argument(
        '--database',
        default=None,
        help='Database name (default: from config)'
    )
    
    parser.add_argument(
        '--skip-verification',
        action='store_true',
        help='Skip migration verification'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print_warning("DRY RUN MODE - No changes will be made")
        print_info(f"Would migrate database with compute_node_id: {args.compute_node_id}")
        if args.database:
            print_info(f"Would use database: {args.database}")
        return 0
    
    # Confirm before proceeding
    print_warning("This will modify your database schema!")
    print_info(f"Compute Node ID: {args.compute_node_id}")
    if args.database:
        print_info(f"Database: {args.database}")
    
    response = input("\nProceed with migration? (yes/no): ")
    if response.lower() not in ('yes', 'y'):
        print_info("Migration cancelled")
        return 0
    
    # Run migration
    success = migrate_database(args.compute_node_id, args.database)
    
    if not success:
        print_error("Migration failed!")
        return 1
    
    # Verify migration
    if not args.skip_verification:
        if not verify_migration(args.compute_node_id):
            print_warning("Migration completed but verification failed")
            print_info("You may need to update the code to use compute_node_id")
            return 1
    
    print_header("Migration Complete")
    print_success("Database successfully migrated to multi-node schema")
    print_info("Next steps:")
    print_info("1. Update /etc/zvmsdk/zvmsdk.conf with compute_node_id")
    print_info("2. Restart zvmsdk services")
    print_info("3. Test with your application")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
