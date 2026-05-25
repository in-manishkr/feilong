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
Create database schema for Feilong on remote database.

This script creates all necessary database tables on a remote MySQL/MariaDB
database. It reads configuration from /etc/zvmsdk/zvmsdk.conf or environment
variables.

Usage:
    python scripts/create_schema.py

Environment Variables (optional):
    ZVMSDK_DB_BACKEND - Database backend (mysql, mariadb)
    ZVMSDK_DB_HOST - Database host
    ZVMSDK_DB_PORT - Database port
    ZVMSDK_DB_NAME - Database name
    ZVMSDK_DB_USER - Database user
    ZVMSDK_DB_PASSWORD - Database password
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zvmsdk import config
from zvmsdk.db import engine, models


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


def create_all_tables():
    """Create all database tables."""
    print_header("Creating Database Schema")
    
    # Get all database types
    db_types = ['network', 'image', 'guest', 'fcp']
    
    total_tables = 0
    
    for db_type in db_types:
        print(f"\n{db_type.upper()} Database:")
        print("-" * 40)
        
        try:
            # Get engine
            eng = engine.get_engine(db_type)
            
            # Get tables for this database type
            tables = models.get_tables_by_database_type(db_type)
            
            if not tables:
                print_info(f"No tables defined for {db_type}")
                continue
            
            # Create tables
            for table in tables:
                try:
                    table.create(eng, checkfirst=True)
                    print_success(f"Created table: {table.name}")
                    total_tables += 1
                except Exception as e:
                    print_error(f"Failed to create table {table.name}: {e}")
                    raise
            
        except Exception as e:
            print_error(f"Failed to process {db_type} database: {e}")
            raise
    
    print_header("Schema Creation Complete")
    print_success(f"Created {total_tables} tables across {len(db_types)} databases")
    
    return True


def verify_configuration():
    """Verify database configuration."""
    print_header("Verifying Configuration")
    
    backend = config.CONF.database.backend
    print_info(f"Database backend: {backend}")
    
    if backend == 'sqlite':
        print_info(f"SQLite directory: {config.CONF.database.dir}")
    else:
        print_info(f"Database host: {config.CONF.database.host}")
        print_info(f"Database port: {config.CONF.database.port}")
        print_info(f"Database name: {config.CONF.database.name}")
        print_info(f"Database user: {config.CONF.database.user}")
        
        # Test connection
        try:
            eng = engine.get_engine('network')
            with eng.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("SELECT 1"))
            print_success("Database connection successful")
        except Exception as e:
            print_error(f"Database connection failed: {e}")
            return False
    
    return True


def main():
    """Main function."""
    try:
        print_header("Feilong Database Schema Creator")
        
        # Initialize configuration
        config.CONF = config.ConfigOpts()
        
        # Verify configuration
        if not verify_configuration():
            print_error("Configuration verification failed")
            return 1
        
        # Create tables
        if not create_all_tables():
            print_error("Schema creation failed")
            return 1
        
        print("\n" + "=" * 60)
        print_success("Database schema created successfully!")
        print("=" * 60)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return 1
    except Exception as e:
        print_error(f"Schema creation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
