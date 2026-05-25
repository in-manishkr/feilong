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
Test database connection without requiring mysql client.

This script tests connectivity to a remote MySQL/MariaDB database using
Python's pymysql library. It's useful for verifying database configuration
before running migrations.

Usage:
    python scripts/test_db_connection.py
    
    # Or with explicit parameters:
    python scripts/test_db_connection.py --host 172.26.4.78 --user root --password HelloWorld --database nova
"""

import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def test_pymysql_import():
    """Test if pymysql is installed."""
    print_header("Checking Dependencies")
    
    try:
        import pymysql
        print_success(f"PyMySQL installed (version {pymysql.__version__})")
        return True
    except ImportError:
        print_error("PyMySQL not installed")
        print_info("Install with: pip install pymysql")
        return False


def test_connection_with_pymysql(host, port, user, password, database):
    """Test database connection using pymysql."""
    print_header("Testing Database Connection")
    
    print_info(f"Host: {host}")
    print_info(f"Port: {port}")
    print_info(f"Database: {database}")
    print_info(f"User: {user}")
    print_info(f"Password: {'*' * len(password)}")
    
    try:
        import pymysql
        
        # Attempt connection
        print_info("Connecting...")
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=10
        )
        
        print_success("Connection established!")
        
        # Test query
        print_info("Testing query execution...")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 as test")
            result = cursor.fetchone()
            if result and result[0] == 1:
                print_success("Query execution successful")
            else:
                print_error("Query returned unexpected result")
                return False
        
        # Get server info
        print_info("Fetching server information...")
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            print_success(f"Server version: {version}")
            
            cursor.execute("SELECT DATABASE()")
            db = cursor.fetchone()[0]
            print_success(f"Current database: {db}")
            
            cursor.execute("SELECT USER()")
            current_user = cursor.fetchone()[0]
            print_success(f"Connected as: {current_user}")
        
        # Check privileges
        print_info("Checking privileges...")
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            grants = cursor.fetchall()
            print_success(f"User has {len(grants)} grant(s)")
            for grant in grants:
                print_info(f"  {grant[0]}")
        
        # List tables
        print_info("Listing tables in database...")
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            if tables:
                print_success(f"Found {len(tables)} table(s)")
                # Show first 10 tables
                for i, table in enumerate(tables[:10]):
                    print_info(f"  {table[0]}")
                if len(tables) > 10:
                    print_info(f"  ... and {len(tables) - 10} more")
            else:
                print_info("No tables found (database is empty)")
        
        connection.close()
        print_success("Connection closed successfully")
        
        return True
        
    except Exception as e:
        print_error(f"Connection failed: {e}")
        
        # Provide helpful error messages
        error_str = str(e).lower()
        if 'access denied' in error_str:
            print_info("Possible causes:")
            print_info("  - Incorrect username or password")
            print_info("  - User doesn't have remote access permissions")
            print_info("  - User doesn't have access to the specified database")
        elif 'unknown database' in error_str:
            print_info("Possible causes:")
            print_info("  - Database doesn't exist")
            print_info("  - Database name is misspelled")
        elif 'can\'t connect' in error_str or 'connection refused' in error_str:
            print_info("Possible causes:")
            print_info("  - Database server is not running")
            print_info("  - Firewall blocking port 3306")
            print_info("  - Incorrect host or port")
            print_info("  - Database not configured for remote connections")
        elif 'timeout' in error_str:
            print_info("Possible causes:")
            print_info("  - Network connectivity issues")
            print_info("  - Firewall blocking connection")
            print_info("  - Database server not responding")
        
        return False


def test_connection_from_config():
    """Test connection using configuration file."""
    print_header("Testing Connection from Configuration")
    
    try:
        from zvmsdk import config
        
        # Initialize configuration
        config.CONF = config.ConfigOpts()
        
        backend = config.CONF.database.backend
        
        if backend == 'sqlite':
            print_error("Configuration is set to SQLite")
            print_info("Update /etc/zvmsdk/zvmsdk.conf to use mysql or mariadb")
            return False
        
        print_info(f"Backend: {backend}")
        
        # Get connection parameters
        host = config.CONF.database.host
        port = config.CONF.database.port
        user = config.CONF.database.user
        password = config.CONF.database.password
        database = config.CONF.database.name
        
        return test_connection_with_pymysql(host, port, user, password, database)
        
    except Exception as e:
        print_error(f"Failed to read configuration: {e}")
        return False


def test_network_connectivity(host, port):
    """Test basic network connectivity."""
    print_header("Testing Network Connectivity")
    
    print_info(f"Testing connection to {host}:{port}")
    
    try:
        import socket
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print_success(f"Port {port} is open on {host}")
            return True
        else:
            print_error(f"Port {port} is closed or filtered on {host}")
            print_info("Possible causes:")
            print_info("  - Firewall blocking the port")
            print_info("  - Database server not running")
            print_info("  - Incorrect host or port")
            return False
            
    except socket.gaierror:
        print_error(f"Could not resolve hostname: {host}")
        return False
    except Exception as e:
        print_error(f"Network test failed: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Test database connection'
    )
    parser.add_argument('--host', help='Database host')
    parser.add_argument('--port', type=int, default=3306, help='Database port')
    parser.add_argument('--user', help='Database user')
    parser.add_argument('--password', help='Database password')
    parser.add_argument('--database', help='Database name')
    parser.add_argument('--use-config', action='store_true',
                       help='Use configuration from /etc/zvmsdk/zvmsdk.conf')
    
    args = parser.parse_args()
    
    try:
        print_header("Database Connection Test Tool")
        
        # Check if pymysql is installed
        if not test_pymysql_import():
            return 1
        
        # Determine connection parameters
        if args.use_config or not args.host:
            # Use configuration file
            if not test_connection_from_config():
                return 1
        else:
            # Use command line parameters
            if not all([args.host, args.user, args.password, args.database]):
                print_error("Missing required parameters")
                print_info("Usage: python test_db_connection.py --host HOST --user USER --password PASSWORD --database DATABASE")
                print_info("   Or: python test_db_connection.py --use-config")
                return 1
            
            # Test network connectivity first
            if not test_network_connectivity(args.host, args.port):
                print_info("Network connectivity test failed, but continuing with database test...")
            
            # Test database connection
            if not test_connection_with_pymysql(
                args.host, args.port, args.user, args.password, args.database
            ):
                return 1
        
        print_header("Connection Test Complete")
        print_success("All tests passed!")
        print_info("You can now proceed with schema creation and data migration")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return 1
    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
