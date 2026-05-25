# Database Abstraction Layer - Implementation Guide

## Overview

This guide provides step-by-step instructions for implementing and using the new database abstraction layer in the Feilong project.

## What Has Been Implemented

### 1. Core Infrastructure ✅

- **Configuration Schema** (`zvmsdk/config.py`)
  - Added 10 new database configuration options
  - Support for SQLite, MySQL, MariaDB, PostgreSQL
  - Connection pooling configuration
  - Backward compatible with existing SQLite setup

- **Database Engine Manager** (`zvmsdk/db/engine.py`)
  - SQLAlchemy engine creation and management
  - Connection pooling for remote databases
  - Database-specific optimizations
  - Support for multiple database instances

- **Table Models** (`zvmsdk/db/models.py`)
  - All tables defined using SQLAlchemy Core
  - Database-agnostic schema definitions
  - Support for migrations via Alembic

- **Repository Base Class** (`zvmsdk/db/repositories/base.py`)
  - Common CRUD operations
  - Transaction management
  - Connection handling
  - Error handling

- **Repository Implementations**
  - `NetworkRepository` - Fully implemented ✅
  - `ImageRepository` - Stub created (TODO)
  - `GuestRepository` - Stub created (TODO)
  - `FCPRepository` - Stub created (TODO)

- **Alembic Migration Support** ✅
  - Configuration files created
  - Migration environment setup
  - Version control ready

### 2. Dependencies Added

```
SQLAlchemy>=1.4.0,<2.0.0
alembic>=1.7.0
PyMySQL>=1.0.0
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Database

Edit `/etc/zvmsdk/zvmsdk.conf`:

#### For SQLite (Default - No Changes Required)

```ini
[database]
backend = sqlite
dir = /var/lib/zvmsdk/databases/
```

#### For MySQL/MariaDB

```ini
[database]
backend = mysql
host = localhost
port = 3306
name = zvmsdk
user = zvmsdk
password = your_secure_password
pool_size = 10
pool_recycle = 3600
max_overflow = 20
```

#### For PostgreSQL (Future)

```ini
[database]
backend = postgresql
host = localhost
port = 5432
name = zvmsdk
user = zvmsdk
password = your_secure_password
pool_size = 10
pool_recycle = 3600
max_overflow = 20
```

### 3. Create Database (MySQL/MariaDB only)

```sql
CREATE DATABASE zvmsdk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'zvmsdk'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON zvmsdk.* TO 'zvmsdk'@'localhost';
FLUSH PRIVILEGES;
```

### 4. Initialize Tables

The tables will be created automatically on first use. Alternatively, you can create them manually:

```python
from zvmsdk.db import engine, models

# Create all tables
for db_type in ['network', 'image', 'guest', 'fcp']:
    eng = engine.get_engine(db_type)
    models.create_all_tables(eng, db_type)
```

## Usage Examples

### Using NetworkRepository

```python
from zvmsdk.db.repositories import NetworkRepository

# Initialize repository
network_repo = NetworkRepository()

# Add a switch record
network_repo.switch_add_record(
    userid='TESTVM01',
    interface='1000',
    port='port123',
    switch='VSWITCH1',
    comments='Test VM network'
)

# Query records
records = network_repo.switch_select_record_for_userid('TESTVM01')
print(records)

# Update switch
network_repo.switch_update_record_with_switch(
    userid='TESTVM01',
    interface='1000',
    switch='VSWITCH2'
)

# Delete record
network_repo.switch_delete_record_for_userid('TESTVM01')
```

### Direct Database Operations

```python
from zvmsdk.db import engine
from zvmsdk.db.models import switch_table
from sqlalchemy import select

# Get engine
eng = engine.get_engine('network')

# Execute query
with eng.connect() as conn:
    query = select(switch_table).where(switch_table.c.userid == 'TESTVM01')
    result = conn.execute(query)
    for row in result:
        print(dict(row._mapping))
```

### Using Transactions

```python
from zvmsdk.db.repositories import NetworkRepository

network_repo = NetworkRepository()

# Use transaction for multiple operations
with network_repo.transaction() as conn:
    # All operations in this block are part of one transaction
    network_repo.switch_add_record(
        userid='VM1', interface='1000', connection=conn
    )
    network_repo.switch_add_record(
        userid='VM2', interface='1000', connection=conn
    )
    # Automatically commits if no exception, rolls back on error
```

## Migration from SQLite to MySQL/MariaDB

### Step 1: Backup Existing Data

```bash
# Backup SQLite databases
cp -r /var/lib/zvmsdk/databases /var/lib/zvmsdk/databases.backup
```

### Step 2: Export Data

Create a migration script (`scripts/migrate_database.py`):

```python
#!/usr/bin/env python3
"""
Database migration tool for zvmsdk.

Migrates data from SQLite to MySQL/MariaDB/PostgreSQL.
"""

import sqlite3
import sys
from zvmsdk import config
from zvmsdk.db import engine, models
from zvmsdk.db.repositories import (
    NetworkRepository, ImageRepository, 
    GuestRepository, FCPRepository
)

def migrate_network_data(sqlite_path, target_repo):
    """Migrate network database."""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Read all switch records
    cursor.execute("SELECT * FROM switch")
    records = [dict(row) for row in cursor.fetchall()]
    
    # Insert into target database
    for record in records:
        target_repo.switch_add_record(
            userid=record['userid'],
            interface=record['interface'],
            port=record['port'],
            switch=record['switch'],
            comments=record['comments']
        )
    
    conn.close()
    print(f"Migrated {len(records)} network records")

def migrate_all(source_dir, target_backend):
    """Migrate all databases."""
    # Update configuration to use target backend
    config.CONF.database.backend = target_backend
    
    # Migrate each database
    migrate_network_data(
        f"{source_dir}/sdk_network.sqlite",
        NetworkRepository()
    )
    # Add similar functions for image, guest, fcp
    
    print("Migration completed successfully!")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: migrate_database.py <source_dir> <target_backend>")
        print("Example: migrate_database.py /var/lib/zvmsdk/databases mysql")
        sys.exit(1)
    
    migrate_all(sys.argv[1], sys.argv[2])
```

### Step 3: Run Migration

```bash
python scripts/migrate_database.py /var/lib/zvmsdk/databases mysql
```

### Step 4: Verify Migration

```python
from zvmsdk.db.repositories import NetworkRepository

repo = NetworkRepository()
records = repo.switch_select_table()
print(f"Total records: {len(records)}")
```

### Step 5: Update Configuration

Update `/etc/zvmsdk/zvmsdk.conf` to use the new backend permanently.

## Database Migrations with Alembic

### Create a New Migration

```bash
cd /path/to/feilong
alembic -c zvmsdk/db/migrations/alembic.ini revision -m "description of changes"
```

### Apply Migrations

```bash
# Upgrade to latest
alembic -c zvmsdk/db/migrations/alembic.ini upgrade head

# Downgrade one version
alembic -c zvmsdk/db/migrations/alembic.ini downgrade -1

# Show current version
alembic -c zvmsdk/db/migrations/alembic.ini current

# Show migration history
alembic -c zvmsdk/db/migrations/alembic.ini history
```

## Completing the Implementation

### TODO: Implement Remaining Repositories

The following repositories need to be fully implemented following the pattern in `NetworkRepository`:

#### 1. ImageRepository (`zvmsdk/db/repositories/image.py`)

Methods to implement:
- `image_add_record()`
- `image_query_record()`
- `image_delete_record()`

Reference: `zvmsdk/database.py` lines 2310-2383

#### 2. GuestRepository (`zvmsdk/db/repositories/guest.py`)

Methods to implement:
- `add_guest()`
- `add_guest_registered()`
- `delete_guest_by_id()`
- `delete_guest_by_userid()`
- `get_guest_by_id()`
- `get_guest_by_userid()`
- `get_guest_list()`
- `get_metadata_by_userid()`
- `update_guest_by_id()`
- `update_guest_by_userid()`

Reference: `zvmsdk/database.py` lines 2385-2644

#### 3. FCPRepository (`zvmsdk/db/repositories/fcp.py`)

This is the most complex repository with ~60 methods. Key methods include:
- FCP device management
- Template management
- Storage provider mapping
- Connection tracking
- Bulk operations

Reference: `zvmsdk/database.py` lines 301-2307

### Implementation Pattern

For each method in the old `DbOperator` classes:

1. **Identify the operation type**: SELECT, INSERT, UPDATE, DELETE
2. **Use the base repository methods**: `select_all()`, `insert_record()`, etc.
3. **Build WHERE clauses** using SQLAlchemy expressions
4. **Handle transactions** when needed
5. **Maintain backward compatibility** - same method signatures
6. **Add logging** for debugging

Example:

```python
def image_add_record(self, imagename, imageosdistro, md5sum,
                     disk_size_units, image_size_in_bytes,
                     type, comments=None):
    """Add image record to database."""
    values = {
        'imagename': imagename,
        'imageosdistro': imageosdistro,
        'md5sum': md5sum,
        'disk_size_units': disk_size_units,
        'image_size_in_bytes': image_size_in_bytes,
        'type': type,
        'comments': comments
    }
    self.insert_record(image_table, values)
    LOG.debug(f"Added image record: {imagename}")
```

## Testing

### Unit Tests

Create tests in `zvmsdk/tests/unit/test_db_repositories.py`:

```python
import unittest
from zvmsdk.db.repositories import NetworkRepository

class TestNetworkRepository(unittest.TestCase):
    def setUp(self):
        self.repo = NetworkRepository()
    
    def test_switch_add_and_query(self):
        # Add record
        self.repo.switch_add_record(
            userid='TEST01',
            interface='1000',
            port='testport'
        )
        
        # Query record
        records = self.repo.switch_select_record_for_userid('TEST01')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['userid'], 'TEST01')
        
        # Cleanup
        self.repo.switch_delete_record_for_userid('TEST01')
```

### Integration Tests

Test with different database backends:

```bash
# Test with SQLite
export ZVMSDK_DB_BACKEND=sqlite
python -m pytest zvmsdk/tests/

# Test with MySQL
export ZVMSDK_DB_BACKEND=mysql
export ZVMSDK_DB_HOST=localhost
export ZVMSDK_DB_NAME=zvmsdk_test
python -m pytest zvmsdk/tests/
```

## Performance Considerations

### Connection Pooling

For MySQL/MariaDB, adjust pool settings based on workload:

```ini
[database]
pool_size = 20          # Increase for high concurrency
max_overflow = 40       # Allow burst capacity
pool_recycle = 1800     # Recycle connections every 30 min
```

### Query Optimization

1. **Use indexes** - Already defined in models.py
2. **Batch operations** - Use `bulk_insert()` for multiple records
3. **Connection reuse** - Pass `connection` parameter for multiple operations
4. **Transaction batching** - Group related operations in transactions

### Monitoring

Add metrics collection:

```python
import time
from zvmsdk import log

def timed_operation(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        log.LOG.info(f"{func.__name__} took {duration:.3f}s")
        return result
    return wrapper
```

## Troubleshooting

### Connection Issues

```python
# Test database connection
from zvmsdk.db import engine

if engine.test_connection('network'):
    print("Connection successful")
else:
    print("Connection failed - check configuration")
```

### Migration Issues

```bash
# Check Alembic status
alembic -c zvmsdk/db/migrations/alembic.ini current

# Stamp database with current version (if needed)
alembic -c zvmsdk/db/migrations/alembic.ini stamp head
```

### Performance Issues

```ini
# Enable SQL logging for debugging
[database]
echo = true
```

## Best Practices

1. **Always use repositories** - Don't bypass the abstraction layer
2. **Use transactions** - For multi-step operations
3. **Handle exceptions** - Repositories raise `SDKDatabaseException`
4. **Test migrations** - On a copy of production data first
5. **Monitor performance** - Track query times and connection pool usage
6. **Backup regularly** - Before major changes or migrations
7. **Use connection pooling** - For remote databases
8. **Keep schemas in sync** - Use Alembic for schema changes

## Next Steps

1. Complete implementation of Image, Guest, and FCP repositories
2. Update existing code to use new repositories
3. Add comprehensive test coverage
4. Performance testing and optimization
5. Documentation updates
6. Production deployment planning

## Support

For issues or questions:
- Check the design document: `docs/database_abstraction_layer_design.md`
- Review existing implementation: `zvmsdk/db/repositories/network.py`
- Consult SQLAlchemy documentation: https://docs.sqlalchemy.org/
- Alembic documentation: https://alembic.sqlalchemy.org/