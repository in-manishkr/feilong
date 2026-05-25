# Database Layer Testing Guide

## Overview

This guide explains how to test the new database abstraction layer to verify it's working correctly.

## Quick Test (Recommended)

### 1. Run the Automated Test Script

The easiest way to test is using the provided test script:

```bash
# Test with SQLite (default, no setup required)
python scripts/test_database_layer.py

# Test with MySQL
python scripts/test_database_layer.py mysql

# Test with MariaDB
python scripts/test_database_layer.py mariadb
```

**Expected Output:**
```
Starting Database Layer Tests
Backend: SQLITE

============================================================
          Setting up SQLITE test configuration
============================================================

ℹ Using temporary directory: /tmp/zvmsdk_test_xxxxx
✓ Configuration setup complete

============================================================
              Testing Engine Creation
============================================================

✓ Created engine for network database
✓ Created engine for image database
✓ Created engine for guest database
✓ Created engine for fcp database

============================================================
           Testing Database Connection
============================================================

✓ Connection successful for network database
✓ Connection successful for image database
✓ Connection successful for guest database
✓ Connection successful for fcp database

... (more tests) ...

============================================================
                    Test Summary
============================================================

✓ Engine Creation
✓ Database Connection
✓ Table Creation
✓ NetworkRepository CRUD
✓ Transaction Rollback
✓ Bulk Operations

Results: 6/6 tests passed

✓ All tests passed!
```

## Manual Testing

### Test 1: Basic Import and Configuration

```python
# Test that modules can be imported
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db import engine, models
from zvmsdk.db.repositories import NetworkRepository

print("✓ All imports successful")

# Load configuration
config.load_config()
print(f"✓ Configuration loaded")
print(f"  Backend: {config.CONF.database.backend}")
print(f"  Directory: {config.CONF.database.dir}")
EOF
```

**Expected Output:**
```
✓ All imports successful
✓ Configuration loaded
  Backend: sqlite
  Directory: /var/lib/zvmsdk/databases/
```

### Test 2: Engine Creation

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db import engine

config.load_config()

# Create engine
eng = engine.get_engine('network')
print(f"✓ Engine created: {eng}")
print(f"  Dialect: {eng.dialect.name}")
print(f"  Driver: {eng.driver}")
EOF
```

**Expected Output:**
```
✓ Engine created: Engine(sqlite:////var/lib/zvmsdk/databases/sdk_network.sqlite)
  Dialect: sqlite
  Driver: pysqlite
```

### Test 3: Connection Test

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db import engine

config.load_config()

# Test connection
if engine.test_connection('network'):
    print("✓ Database connection successful")
else:
    print("✗ Database connection failed")
EOF
```

**Expected Output:**
```
✓ Database connection successful
```

### Test 4: Table Creation

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db import engine, models

config.load_config()

# Create tables
eng = engine.get_engine('network')
models.create_all_tables(eng, 'network')
print("✓ Tables created successfully")

# Verify tables exist
from sqlalchemy import inspect
inspector = inspect(eng)
tables = inspector.get_table_names()
print(f"  Tables: {tables}")
EOF
```

**Expected Output:**
```
✓ Tables created successfully
  Tables: ['switch']
```

### Test 5: NetworkRepository CRUD Operations

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db.repositories import NetworkRepository

config.load_config()

# Initialize repository
repo = NetworkRepository()
print("✓ NetworkRepository initialized")

# INSERT
repo.switch_add_record(
    userid='TESTVM01',
    interface='1000',
    port='testport',
    switch='VSWITCH1'
)
print("✓ INSERT: Record added")

# SELECT
records = repo.switch_select_record_for_userid('TESTVM01')
print(f"✓ SELECT: Found {len(records)} record(s)")
print(f"  Data: {records[0]}")

# UPDATE
repo.switch_update_record_with_switch(
    userid='TESTVM01',
    interface='1000',
    switch='VSWITCH2'
)
records = repo.switch_select_record_for_userid('TESTVM01')
print(f"✓ UPDATE: Switch changed to {records[0]['switch']}")

# DELETE
repo.switch_delete_record_for_userid('TESTVM01')
records = repo.switch_select_record_for_userid('TESTVM01')
print(f"✓ DELETE: {len(records)} records remaining")
EOF
```

**Expected Output:**
```
✓ NetworkRepository initialized
✓ INSERT: Record added
✓ SELECT: Found 1 record(s)
  Data: {'userid': 'TESTVM01', 'interface': '1000', 'switch': 'VSWITCH1', 'port': 'testport', 'comments': None}
✓ UPDATE: Switch changed to VSWITCH2
✓ DELETE: 0 records remaining
```

## Testing with MySQL/MariaDB

### Prerequisites

1. **Install MySQL/MariaDB**:
```bash
# Ubuntu/Debian
sudo apt-get install mysql-server

# RHEL/CentOS
sudo yum install mariadb-server
```

2. **Create Test Database**:
```sql
CREATE DATABASE zvmsdk_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'zvmsdk'@'localhost' IDENTIFIED BY 'test_password';
GRANT ALL PRIVILEGES ON zvmsdk_test.* TO 'zvmsdk'@'localhost';
FLUSH PRIVILEGES;
```

3. **Set Environment Variables**:
```bash
export ZVMSDK_DB_HOST=localhost
export ZVMSDK_DB_PORT=3306
export ZVMSDK_DB_NAME=zvmsdk_test
export ZVMSDK_DB_USER=zvmsdk
export ZVMSDK_DB_PASSWORD=test_password
```

4. **Update Configuration** (or use environment variables):
```ini
# /etc/zvmsdk/zvmsdk.conf
[database]
backend = mysql
host = localhost
port = 3306
name = zvmsdk_test
user = zvmsdk
password = test_password
```

5. **Run Tests**:
```bash
python scripts/test_database_layer.py mysql
```

## Testing Different Scenarios

### Test Scenario 1: Backward Compatibility (SQLite)

Verify existing SQLite databases still work:

```bash
# If you have existing SQLite databases
ls -la /var/lib/zvmsdk/databases/

# Run test
python scripts/test_database_layer.py sqlite

# Verify existing data is intact
python3 << 'EOF'
from zvmsdk.db.repositories import NetworkRepository
repo = NetworkRepository()
records = repo.switch_select_table()
print(f"Total records: {len(records)}")
EOF
```

### Test Scenario 2: Connection Pooling (MySQL)

Test connection pool behavior:

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db import engine
import time

config.load_config()
config.CONF.database.backend = 'mysql'
config.CONF.database.pool_size = 5

# Create multiple connections
connections = []
for i in range(5):
    eng = engine.get_engine('network')
    conn = eng.connect()
    connections.append(conn)
    print(f"✓ Connection {i+1} created")

# Close connections
for i, conn in enumerate(connections):
    conn.close()
    print(f"✓ Connection {i+1} closed")

print("✓ Connection pooling test passed")
EOF
```

### Test Scenario 3: Transaction Rollback

Test that transactions roll back on error:

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db.repositories import NetworkRepository

config.load_config()
repo = NetworkRepository()

# Add initial record
repo.switch_add_record(userid='TEST01', interface='1000', port='port1')
print("✓ Initial record added")

# Try to add duplicate (should fail)
try:
    with repo.transaction() as conn:
        # This will fail due to primary key constraint
        repo.switch_add_record(userid='TEST01', interface='1000', port='port2')
except Exception as e:
    print(f"✓ Transaction rolled back: {type(e).__name__}")

# Verify original record is intact
records = repo.switch_select_record_for_userid('TEST01')
if records[0]['port'] == 'port1':
    print("✓ Original record intact after rollback")

# Cleanup
repo.switch_delete_record_for_userid('TEST01')
EOF
```

### Test Scenario 4: Performance Test

Basic performance comparison:

```python
python3 << 'EOF'
from zvmsdk import config
from zvmsdk.db.repositories import NetworkRepository
import time

config.load_config()
repo = NetworkRepository()

# Test INSERT performance
start = time.time()
for i in range(100):
    repo.switch_add_record(
        userid=f'PERF{i:03d}',
        interface='1000',
        port=f'port{i}'
    )
insert_time = time.time() - start
print(f"✓ INSERT: 100 records in {insert_time:.3f}s ({100/insert_time:.1f} ops/sec)")

# Test SELECT performance
start = time.time()
for i in range(100):
    records = repo.switch_select_record_for_userid(f'PERF{i:03d}')
select_time = time.time() - start
print(f"✓ SELECT: 100 queries in {select_time:.3f}s ({100/select_time:.1f} ops/sec)")

# Cleanup
start = time.time()
for i in range(100):
    repo.switch_delete_record_for_userid(f'PERF{i:03d}')
delete_time = time.time() - start
print(f"✓ DELETE: 100 records in {delete_time:.3f}s ({100/delete_time:.1f} ops/sec)")
EOF
```

## Troubleshooting

### Issue: Import Errors

**Problem:**
```
ImportError: No module named 'sqlalchemy'
```

**Solution:**
```bash
pip install -r requirements.txt
```

### Issue: Connection Failed

**Problem:**
```
✗ Database connection failed
```

**Solution for SQLite:**
```bash
# Check directory permissions
ls -la /var/lib/zvmsdk/databases/
sudo chmod 755 /var/lib/zvmsdk/databases/
```

**Solution for MySQL:**
```bash
# Test MySQL connection
mysql -u zvmsdk -p -h localhost zvmsdk_test

# Check MySQL is running
sudo systemctl status mysql
```

### Issue: Table Already Exists

**Problem:**
```
sqlalchemy.exc.OperationalError: table already exists
```

**Solution:**
This is normal - tables are created with `checkfirst=True`, so this shouldn't cause issues. If it does:

```python
# Drop and recreate tables
from zvmsdk.db import engine, models
eng = engine.get_engine('network')
models.drop_all_tables(eng, 'network')
models.create_all_tables(eng, 'network')
```

### Issue: Permission Denied

**Problem:**
```
PermissionError: [Errno 13] Permission denied: '/var/lib/zvmsdk/databases/'
```

**Solution:**
```bash
sudo mkdir -p /var/lib/zvmsdk/databases/
sudo chown $USER:$USER /var/lib/zvmsdk/databases/
sudo chmod 755 /var/lib/zvmsdk/databases/
```

## Continuous Testing

### Set Up Automated Tests

Create a test script that runs regularly:

```bash
#!/bin/bash
# test_db_daily.sh

echo "Running daily database tests..."

# Test SQLite
python scripts/test_database_layer.py sqlite
SQLITE_RESULT=$?

# Test MySQL (if configured)
if [ -n "$ZVMSDK_DB_PASSWORD" ]; then
    python scripts/test_database_layer.py mysql
    MYSQL_RESULT=$?
else
    MYSQL_RESULT=0
fi

# Report results
if [ $SQLITE_RESULT -eq 0 ] && [ $MYSQL_RESULT -eq 0 ]; then
    echo "✓ All tests passed"
    exit 0
else
    echo "✗ Some tests failed"
    exit 1
fi
```

### Add to Cron

```bash
# Run tests daily at 2 AM
0 2 * * * /path/to/test_db_daily.sh >> /var/log/zvmsdk/db_tests.log 2>&1
```

## Test Checklist

Before deploying to production, verify:

- [ ] All imports work without errors
- [ ] Configuration loads correctly
- [ ] Database engines can be created
- [ ] Connections succeed
- [ ] Tables are created successfully
- [ ] CRUD operations work (INSERT, SELECT, UPDATE, DELETE)
- [ ] Transactions roll back on errors
- [ ] Bulk operations work
- [ ] Connection pooling works (for MySQL/MariaDB)
- [ ] Performance is acceptable
- [ ] Existing SQLite data is accessible
- [ ] Migration from SQLite to MySQL works (if applicable)

## Next Steps

After successful testing:

1. **Complete remaining repositories** (Image, Guest, FCP)
2. **Add unit tests** to the test suite
3. **Performance tuning** based on test results
4. **Deploy to staging** environment
5. **Monitor** in production

## Support

If tests fail or you encounter issues:

1. Check the logs in `/var/log/zvmsdk/`
2. Review configuration in `/etc/zvmsdk/zvmsdk.conf`
3. Consult the implementation guide: `docs/database_implementation_guide.md`
4. Check database permissions and connectivity
5. Verify all dependencies are installed

## Summary

The test script (`scripts/test_database_layer.py`) provides comprehensive automated testing. For most users, simply running:

```bash
python scripts/test_database_layer.py
```

is sufficient to verify the database layer is working correctly.