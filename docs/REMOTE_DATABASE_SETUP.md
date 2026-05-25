# Remote Database Setup and Migration Guide

This guide explains how to configure Feilong to use a remote MySQL/MariaDB database and migrate existing SQLite data.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Database Preparation](#database-preparation)
3. [Configuration](#configuration)
4. [Initial Schema Creation](#initial-schema-creation)
5. [Data Migration from SQLite](#data-migration-from-sqlite)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### 1. Install Required Python Packages

```bash
# For MySQL
pip install pymysql sqlalchemy alembic

# For MariaDB (same as MySQL)
pip install pymysql sqlalchemy alembic

# For PostgreSQL (future support)
pip install psycopg2-binary sqlalchemy alembic
```

### 2. Database Server Requirements

- MySQL 5.7+ or MariaDB 10.3+
- Network access from Feilong server to database server
- Database user with CREATE, ALTER, DROP, INSERT, UPDATE, DELETE, SELECT privileges

---

## Database Preparation

### Step 1: Create Database and User

Connect to your MySQL/MariaDB server:

```bash
mysql -h <database-host> -u root -p
```

Create database and user:

```sql
-- Create database
CREATE DATABASE zvmsdk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create user (replace 'password' with a strong password)
CREATE USER 'zvmsdk'@'%' IDENTIFIED BY 'your_secure_password';

-- Grant privileges
GRANT ALL PRIVILEGES ON zvmsdk.* TO 'zvmsdk'@'%';
FLUSH PRIVILEGES;

-- Verify
SHOW GRANTS FOR 'zvmsdk'@'%';
```

**Security Note**: For production, restrict the host to specific IP addresses instead of '%':
```sql
CREATE USER 'zvmsdk'@'192.168.1.100' IDENTIFIED BY 'your_secure_password';
```

### Step 2: Test Connection

From your Feilong server:

```bash
mysql -h <database-host> -u zvmsdk -p zvmsdk
```

If successful, you should see the MySQL prompt.

---

## Configuration

### Option 1: Configuration File (Recommended for Production)

Create or edit `/etc/zvmsdk/zvmsdk.conf`:

```ini
[database]
# Database backend: sqlite, mysql, mariadb, postgresql
backend = mysql

# Remote database connection details
host = 192.168.1.100
port = 3306
name = zvmsdk
user = zvmsdk
password = your_secure_password

# Connection pool settings (optional)
pool_size = 10
pool_recycle = 3600
max_overflow = 20

# For multi-node OpenStack deployments (optional)
# compute_node_id = compute-node-01
```

**File Permissions** (important for security):
```bash
sudo chown root:zvmsdk /etc/zvmsdk/zvmsdk.conf
sudo chmod 640 /etc/zvmsdk/zvmsdk.conf
```

### Option 2: Environment Variables (Good for Testing)

```bash
export ZVMSDK_DB_BACKEND=mysql
export ZVMSDK_DB_HOST=192.168.1.100
export ZVMSDK_DB_PORT=3306
export ZVMSDK_DB_NAME=zvmsdk
export ZVMSDK_DB_USER=zvmsdk
export ZVMSDK_DB_PASSWORD=your_secure_password
```

Add to `~/.bashrc` or `/etc/environment` for persistence.

---

## Initial Schema Creation

### Method 1: Using Python Script (Recommended)

Create a script `create_schema.py`:

```python
#!/usr/bin/env python3
"""
Create database schema for Feilong on remote database.
"""

import sys
from zvmsdk import config
from zvmsdk.db import engine, models

def create_all_tables():
    """Create all database tables."""
    print("Creating database schema...")
    
    # Get all database types
    db_types = ['network', 'image', 'guest', 'fcp']
    
    for db_type in db_types:
        print(f"\nCreating tables for {db_type} database...")
        
        # Get engine
        eng = engine.get_engine(db_type)
        
        # Get tables for this database type
        tables = models.get_tables_by_database_type(db_type)
        
        # Create tables
        for table in tables:
            print(f"  Creating table: {table.name}")
            table.create(eng, checkfirst=True)
        
        print(f"✓ {db_type} database schema created")
    
    print("\n✓ All database schemas created successfully!")

if __name__ == '__main__':
    try:
        # Initialize configuration
        config.CONF = config.ConfigOpts()
        
        # Create tables
        create_all_tables()
        
    except Exception as e:
        print(f"✗ Error creating schema: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
```

Run the script:

```bash
cd /root/feilong
python create_schema.py
```

### Method 2: Using Alembic Migrations

```bash
cd /root/feilong

# Initialize Alembic (if not already done)
alembic -c zvmsdk/db/migrations/alembic.ini init zvmsdk/db/migrations

# Create initial migration
alembic -c zvmsdk/db/migrations/alembic.ini revision --autogenerate -m "Initial schema"

# Apply migration
alembic -c zvmsdk/db/migrations/alembic.ini upgrade head
```

### Method 3: Direct SQL (Manual)

If you prefer SQL, you can create tables manually:

```sql
USE zvmsdk;

-- Network database tables
CREATE TABLE switch (
    userid VARCHAR(8) NOT NULL,
    interface VARCHAR(4) NOT NULL,
    switch VARCHAR(8),
    port VARCHAR(128),
    comments VARCHAR(128),
    PRIMARY KEY (userid, interface)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Image database tables
CREATE TABLE image (
    imagename VARCHAR(128) NOT NULL PRIMARY KEY,
    imageosdistro VARCHAR(16) NOT NULL,
    md5sum VARCHAR(32) NOT NULL,
    disk_size_units VARCHAR(512),
    image_size_in_bytes VARCHAR(512),
    type VARCHAR(16),
    comments VARCHAR(128)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Guest database tables
CREATE TABLE guests (
    id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
    userid VARCHAR(8) NOT NULL UNIQUE,
    metadata TEXT,
    net_set TEXT,
    comments VARCHAR(128)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- FCP database tables
CREATE TABLE fcp (
    fcp_id VARCHAR(16) NOT NULL PRIMARY KEY,
    assigner_id VARCHAR(8) NOT NULL,
    connections INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    path VARCHAR(16),
    npiv_port VARCHAR(16),
    chpid VARCHAR(2),
    pchid VARCHAR(3),
    state VARCHAR(16),
    owner VARCHAR(8),
    tmpl_id VARCHAR(16)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE template (
    id VARCHAR(16) NOT NULL PRIMARY KEY,
    name VARCHAR(32) NOT NULL,
    description VARCHAR(128),
    is_default INTEGER NOT NULL DEFAULT 0,
    min_fcp_paths_count INTEGER
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE template_fcp_mapping (
    fcp_id VARCHAR(16) NOT NULL,
    tmpl_id VARCHAR(16) NOT NULL,
    path INTEGER NOT NULL,
    PRIMARY KEY (fcp_id, tmpl_id),
    FOREIGN KEY (fcp_id) REFERENCES fcp(fcp_id),
    FOREIGN KEY (tmpl_id) REFERENCES template(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE template_sp_mapping (
    sp_name VARCHAR(128) NOT NULL,
    tmpl_id VARCHAR(16) NOT NULL,
    PRIMARY KEY (sp_name, tmpl_id),
    FOREIGN KEY (tmpl_id) REFERENCES template(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## Data Migration from SQLite

If you have existing SQLite databases with data, migrate them to the remote database:

### Step 1: Backup Existing SQLite Data

```bash
# Backup SQLite databases
cp /var/lib/zvmsdk/network.db /var/lib/zvmsdk/network.db.backup
cp /var/lib/zvmsdk/image.db /var/lib/zvmsdk/image.db.backup
cp /var/lib/zvmsdk/guests.db /var/lib/zvmsdk/guests.db.backup
cp /var/lib/zvmsdk/fcp.db /var/lib/zvmsdk/fcp.db.backup
```

### Step 2: Create Migration Script

Create `migrate_data.py`:

```python
#!/usr/bin/env python3
"""
Migrate data from SQLite to remote database.
"""

import sys
from zvmsdk import config
from zvmsdk.db import engine, models
from sqlalchemy import create_engine, select

def migrate_database(db_type, sqlite_path):
    """Migrate data from SQLite to remote database."""
    print(f"\nMigrating {db_type} database...")
    
    # Create SQLite engine
    sqlite_engine = create_engine(f'sqlite:///{sqlite_path}')
    
    # Get remote engine
    remote_engine = engine.get_engine(db_type)
    
    # Get tables
    tables = models.get_tables_by_database_type(db_type)
    
    for table in tables:
        print(f"  Migrating table: {table.name}")
        
        # Read from SQLite
        with sqlite_engine.connect() as sqlite_conn:
            result = sqlite_conn.execute(select(table))
            rows = result.fetchall()
            
            if not rows:
                print(f"    No data to migrate")
                continue
            
            print(f"    Found {len(rows)} rows")
            
            # Write to remote database
            with remote_engine.connect() as remote_conn:
                # Convert rows to dictionaries
                data = [dict(row._mapping) for row in rows]
                
                # Insert data
                remote_conn.execute(table.insert(), data)
                remote_conn.commit()
                
                print(f"    ✓ Migrated {len(rows)} rows")
    
    print(f"✓ {db_type} database migration complete")

def main():
    """Main migration function."""
    # Database paths
    migrations = [
        ('network', '/var/lib/zvmsdk/network.db'),
        ('image', '/var/lib/zvmsdk/image.db'),
        ('guest', '/var/lib/zvmsdk/guests.db'),
        ('fcp', '/var/lib/zvmsdk/fcp.db'),
    ]
    
    print("Starting data migration from SQLite to remote database...")
    
    for db_type, sqlite_path in migrations:
        try:
            migrate_database(db_type, sqlite_path)
        except Exception as e:
            print(f"✗ Error migrating {db_type}: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    print("\n✓ All data migrated successfully!")
    return 0

if __name__ == '__main__':
    try:
        # Initialize configuration
        config.CONF = config.ConfigOpts()
        
        # Run migration
        sys.exit(main())
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
```

Run the migration:

```bash
cd /root/feilong
python migrate_data.py
```

---

## Verification

### Step 1: Verify Tables Created

```bash
mysql -h <database-host> -u zvmsdk -p zvmsdk -e "SHOW TABLES;"
```

Expected output:
```
+---------------------------+
| Tables_in_zvmsdk          |
+---------------------------+
| fcp                       |
| guests                    |
| image                     |
| switch                    |
| template                  |
| template_fcp_mapping      |
| template_sp_mapping       |
+---------------------------+
```

### Step 2: Verify Data Migrated

```bash
mysql -h <database-host> -u zvmsdk -p zvmsdk -e "SELECT COUNT(*) FROM switch;"
mysql -h <database-host> -u zvmsdk -p zvmsdk -e "SELECT COUNT(*) FROM image;"
mysql -h <database-host> -u zvmsdk -p zvmsdk -e "SELECT COUNT(*) FROM guests;"
mysql -h <database-host> -u zvmsdk -p zvmsdk -e "SELECT COUNT(*) FROM fcp;"
```

### Step 3: Test Application

```bash
# Run test script
cd /root/feilong
python scripts/test_database_layer.py mysql

# Or start the application
systemctl start zvmsdk
systemctl status zvmsdk
```

---

## Troubleshooting

### Connection Refused

**Problem**: `Can't connect to MySQL server on 'host'`

**Solutions**:
1. Check firewall:
   ```bash
   # On database server
   sudo firewall-cmd --add-port=3306/tcp --permanent
   sudo firewall-cmd --reload
   ```

2. Check MySQL bind address:
   ```bash
   # Edit /etc/my.cnf or /etc/mysql/my.cnf
   [mysqld]
   bind-address = 0.0.0.0  # Listen on all interfaces
   
   # Restart MySQL
   sudo systemctl restart mysqld
   ```

3. Verify network connectivity:
   ```bash
   telnet <database-host> 3306
   ```

### Access Denied

**Problem**: `Access denied for user 'zvmsdk'@'host'`

**Solutions**:
1. Verify user exists:
   ```sql
   SELECT user, host FROM mysql.user WHERE user='zvmsdk';
   ```

2. Check grants:
   ```sql
   SHOW GRANTS FOR 'zvmsdk'@'%';
   ```

3. Recreate user if needed:
   ```sql
   DROP USER 'zvmsdk'@'%';
   CREATE USER 'zvmsdk'@'%' IDENTIFIED BY 'password';
   GRANT ALL PRIVILEGES ON zvmsdk.* TO 'zvmsdk'@'%';
   FLUSH PRIVILEGES;
   ```

### Table Already Exists

**Problem**: `Table 'switch' already exists`

**Solution**: Drop and recreate:
```sql
DROP DATABASE zvmsdk;
CREATE DATABASE zvmsdk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Slow Performance

**Problem**: Queries are slow

**Solutions**:
1. Add indexes:
   ```sql
   CREATE INDEX idx_switch_userid ON switch(userid);
   CREATE INDEX idx_guests_userid ON guests(userid);
   CREATE INDEX idx_fcp_assigner ON fcp(assigner_id);
   ```

2. Increase connection pool:
   ```ini
   [database]
   pool_size = 20
   max_overflow = 40
   ```

3. Enable query cache (MySQL):
   ```ini
   [mysqld]
   query_cache_type = 1
   query_cache_size = 64M
   ```

---

## Multi-Node OpenStack Deployment

For OpenStack deployments with multiple compute nodes sharing a database:

### Step 1: Add compute_node_id Column

Run the multi-node migration script:

```bash
cd /root/feilong
python scripts/migrate_to_multinode.py compute-node-01 --database zvmsdk
```

### Step 2: Configure Each Compute Node

On each compute node, set unique `compute_node_id`:

```ini
[database]
backend = mysql
host = 192.168.1.100
name = zvmsdk
user = zvmsdk
password = password
compute_node_id = compute-node-01  # Unique per node
```

### Step 3: Verify Data Isolation

```sql
-- Check data segregation
SELECT compute_node_id, COUNT(*) 
FROM guests 
GROUP BY compute_node_id;
```

---

## Summary

**Quick Setup Checklist**:
- ☐ Install pymysql and sqlalchemy
- ☐ Create database and user on MySQL/MariaDB server
- ☐ Configure `/etc/zvmsdk/zvmsdk.conf` with remote database details
- ☐ Run `create_schema.py` to create tables
- ☐ (Optional) Run `migrate_data.py` to migrate existing SQLite data
- ☐ Verify tables and data
- ☐ Test application

**Configuration File Location**: `/etc/zvmsdk/zvmsdk.conf`

**Minimum Configuration**:
```ini
[database]
backend = mysql
host = your-db-host
name = zvmsdk
user = zvmsdk
password = your-password
```

That's it! Your Feilong installation is now using a remote database.