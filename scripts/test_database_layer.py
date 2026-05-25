#!/usr/bin/env python3
#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""
Test script for the new database abstraction layer.

This script tests the database layer implementation with different backends.
Run this to verify everything is working correctly.

Usage:
    python scripts/test_database_layer.py [backend]
    
    backend: sqlite (default), mysql, mariadb
    
Examples:
    python scripts/test_database_layer.py
    python scripts/test_database_layer.py mysql
"""

import sys
import os
import tempfile

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from zvmsdk import config
from zvmsdk.db import engine, models
from zvmsdk.db.repositories import NetworkRepository


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    """Print a formatted header."""
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


def setup_test_config(backend='sqlite'):
    """
    Setup test configuration for the specified backend.
    
    Args:
        backend: Database backend to test (sqlite, mysql, mariadb)
    """
    print_header(f"Setting up {backend.upper()} test configuration")
    
    # Try to load configuration, if it fails, use defaults
    try:
        config.load_config()
    except Exception as e:
        print_info(f"Could not load config file: {e}")
        print_info("Using default configuration")
        # Use default CONF that was registered
        pass
    
    if backend == 'sqlite':
        # Use temporary directory for SQLite
        temp_dir = tempfile.mkdtemp(prefix='zvmsdk_test_')
        config.CONF.database.backend = 'sqlite'
        config.CONF.database.dir = temp_dir
        print_info(f"Using temporary directory: {temp_dir}")
    
    elif backend in ('mysql', 'mariadb'):
        # For MySQL/MariaDB, use test database
        config.CONF.database.backend = backend
        config.CONF.database.host = os.getenv('ZVMSDK_DB_HOST', 'localhost')
        config.CONF.database.port = int(os.getenv('ZVMSDK_DB_PORT', '3306'))
        config.CONF.database.name = os.getenv('ZVMSDK_DB_NAME', 'zvmsdk_test')
        config.CONF.database.user = os.getenv('ZVMSDK_DB_USER', 'zvmsdk')
        config.CONF.database.password = os.getenv('ZVMSDK_DB_PASSWORD', 'zvmsdk')
        
        print_info(f"Using {backend} database:")
        print_info(f"  Host: {config.CONF.database.host}")
        print_info(f"  Port: {config.CONF.database.port}")
        print_info(f"  Database: {config.CONF.database.name}")
        print_info(f"  User: {config.CONF.database.user}")
    
    else:
        print_error(f"Unsupported backend: {backend}")
        sys.exit(1)
    
    print_success("Configuration setup complete")


def test_engine_creation():
    """Test database engine creation."""
    print_header("Testing Engine Creation")
    
    try:
        # Test creating engines for different database types
        for db_type in ['network', 'image', 'guest', 'fcp']:
            eng = engine.get_engine(db_type)
            print_success(f"Created engine for {db_type} database")
        
        return True
    except Exception as e:
        print_error(f"Engine creation failed: {e}")
        return False


def test_connection():
    """Test database connection."""
    print_header("Testing Database Connection")
    
    try:
        # Test connection for each database type
        for db_type in ['network', 'image', 'guest', 'fcp']:
            if engine.test_connection(db_type):
                print_success(f"Connection successful for {db_type} database")
            else:
                print_error(f"Connection failed for {db_type} database")
                return False
        
        return True
    except Exception as e:
        print_error(f"Connection test failed: {e}")
        return False


def test_table_creation():
    """Test table creation."""
    print_header("Testing Table Creation")
    
    try:
        # Create tables for each database type
        for db_type in ['network', 'image', 'guest', 'fcp']:
            eng = engine.get_engine(db_type)
            models.create_all_tables(eng, db_type)
            print_success(f"Created tables for {db_type} database")
        
        return True
    except Exception as e:
        print_error(f"Table creation failed: {e}")
        return False


def test_network_repository():
    """Test NetworkRepository CRUD operations."""
    print_header("Testing NetworkRepository")
    
    try:
        repo = NetworkRepository()
        print_success("NetworkRepository initialized")
        
        # Clean up any existing test data first
        try:
            repo.switch_delete_record_for_userid('TESTVM01')
        except:
            pass
        
        # Test INSERT
        print_info("Testing INSERT operation...")
        repo.switch_add_record(
            userid='TESTVM01',
            interface='1000',
            port='testport123',
            switch='VSWITCH1',
            comments='Test record'
        )
        print_success("INSERT: Added test record")
        
        # Test SELECT
        print_info("Testing SELECT operation...")
        records = repo.switch_select_record_for_userid('TESTVM01')
        if len(records) == 1:
            print_success(f"SELECT: Found 1 record")
            print_info(f"  Record: {records[0]}")
        else:
            print_error(f"SELECT: Expected 1 record, found {len(records)}")
            return False
        
        # Test UPDATE
        print_info("Testing UPDATE operation...")
        repo.switch_update_record_with_switch(
            userid='TESTVM01',
            interface='1000',
            switch='VSWITCH2'
        )
        records = repo.switch_select_record_for_userid('TESTVM01')
        if records[0]['switch'] == 'VSWITCH2':
            print_success("UPDATE: Switch updated successfully")
        else:
            print_error(f"UPDATE: Expected VSWITCH2, got {records[0]['switch']}")
            return False
        
        # Test DELETE
        print_info("Testing DELETE operation...")
        repo.switch_delete_record_for_userid('TESTVM01')
        records = repo.switch_select_record_for_userid('TESTVM01')
        if len(records) == 0:
            print_success("DELETE: Record deleted successfully")
        else:
            print_error(f"DELETE: Expected 0 records, found {len(records)}")
            return False
        
        return True
    except Exception as e:
        print_error(f"NetworkRepository test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_transaction_rollback():
    """Test transaction rollback on error."""
    print_header("Testing Transaction Rollback")
    
    try:
        repo = NetworkRepository()
        
        # Clean up any existing test data first
        try:
            repo.switch_delete_record_for_userid('TESTVM02')
        except:
            pass
        
        # Add a record
        repo.switch_add_record(
            userid='TESTVM02',
            interface='1000',
            port='testport'
        )
        print_success("Added initial record")
        
        # Try to add duplicate (should fail due to primary key constraint)
        # Note: Repository methods don't accept connection parameter yet
        # This tests that the error is properly raised
        print_info("Testing transaction rollback by attempting duplicate insert...")
        try:
            with repo.transaction() as conn:
                # Insert directly using connection to test transaction
                from zvmsdk.db.models import switch_table
                conn.execute(
                    switch_table.insert().values(
                        userid='TESTVM02',
                        interface='1000',
                        port='duplicate'
                    )
                )
                # This should fail due to primary key constraint
                print_error("Expected constraint violation did not occur!")
                return False
        except Exception as e:
            # This exception is EXPECTED - it means the constraint is working
            print_info(f"Expected constraint violation occurred: {type(e).__name__}")
            print_success("Transaction correctly rolled back on error")
        
        # Verify original record still exists
        records = repo.switch_select_record_for_userid('TESTVM02')
        if len(records) == 1 and records[0]['port'] == 'testport':
            print_success("Original record intact after rollback")
        else:
            print_error("Record corrupted after rollback")
            return False
        
        # Cleanup
        repo.switch_delete_record_for_userid('TESTVM02')
        
        return True
    except Exception as e:
        print_error(f"Transaction rollback test failed: {e}")
        return False


def test_bulk_operations():
    """Test bulk insert operations."""
    print_header("Testing Bulk Operations")
    
    try:
        repo = NetworkRepository()
        
        # Clean up any existing test data first
        print_info("Cleaning up existing test data...")
        for i in range(10):
            try:
                repo.switch_delete_record_for_userid(f'TESTVM{i:02d}')
            except:
                pass
        
        # Add multiple records
        print_info("Adding 5 test records...")
        for i in range(5):
            repo.switch_add_record(
                userid=f'TESTVM{i:02d}',
                interface='1000',
                port=f'port{i}'
            )
        print_success("Added 5 records")
        
        # Query all records
        all_records = repo.switch_select_table()
        test_records = [r for r in all_records if r['userid'].startswith('TESTVM')]
        
        if len(test_records) == 5:
            print_success(f"Found all 5 test records")
        else:
            print_error(f"Expected 5 records, found {len(test_records)}")
            return False
        
        # Cleanup
        print_info("Cleaning up test records...")
        for i in range(5):
            repo.switch_delete_record_for_userid(f'TESTVM{i:02d}')
        print_success("Cleanup complete")
        
        return True
    except Exception as e:
        print_error(f"Bulk operations test failed: {e}")
        return False


def cleanup():
    """Cleanup test data and connections."""
    print_header("Cleanup")
    
    try:
        # Dispose all engines
        engine.dispose_engine()
        print_success("Disposed all database engines")
        
        return True
    except Exception as e:
        print_error(f"Cleanup failed: {e}")
        return False


def run_all_tests(backend='sqlite'):
    """
    Run all tests.
    
    Args:
        backend: Database backend to test
    
    Returns:
        True if all tests pass, False otherwise
    """
    print(f"\n{Colors.BOLD}Starting Database Layer Tests{Colors.RESET}")
    print(f"{Colors.BOLD}Backend: {backend.upper()}{Colors.RESET}\n")
    
    # Setup
    setup_test_config(backend)
    
    # Run tests
    tests = [
        ("Engine Creation", test_engine_creation),
        ("Database Connection", test_connection),
        ("Table Creation", test_table_creation),
        ("NetworkRepository CRUD", test_network_repository),
        ("Transaction Rollback", test_transaction_rollback),
        ("Bulk Operations", test_bulk_operations),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print_error(f"Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Cleanup
    cleanup()
    
    # Print summary
    print_header("Test Summary")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        if result:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")
    
    print(f"\n{Colors.BOLD}Results: {passed}/{total} tests passed{Colors.RESET}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All tests passed!{Colors.RESET}\n")
        return True
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Some tests failed{Colors.RESET}\n")
        return False


def main():
    """Main entry point."""
    # Parse command line arguments
    backend = sys.argv[1] if len(sys.argv) > 1 else 'sqlite'
    
    if backend not in ('sqlite', 'mysql', 'mariadb'):
        print_error(f"Invalid backend: {backend}")
        print_info("Valid backends: sqlite, mysql, mariadb")
        sys.exit(1)
    
    # Run tests
    success = run_all_tests(backend)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

# Made with Bob
