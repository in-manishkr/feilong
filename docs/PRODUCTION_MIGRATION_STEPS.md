# Production Migration to OpenStack Nova Database

## Your Environment

- **Remote Database**: MariaDB at `172.26.4.78`
- **Database Name**: `nova` (OpenStack database)
- **User**: `root`
- **Password**: `HelloWorld`
- **Purpose**: Migrate local SQLite data to shared OpenStack Nova database

## ⚠️ Important Notes

1. **Shared Database**: The `nova` database is used by OpenStack, so we'll add Feilong tables alongside OpenStack tables
2. **Multi-Node**: Since this is OpenStack, you likely have multiple compute nodes - we'll configure for that
3. **Backup First**: Always backup before making changes to production databases

---

## Step-by-Step Migration Guide

### Step 1: Backup Current SQLite Databases

```bash
# Create backup directory
sudo mkdir -p /var/lib/zvmsdk/backup
sudo chmod 755 /var/lib/zvmsdk/backup

# Backup all SQLite databases
sudo cp /var/lib/zvmsdk/network.db /var/lib/zvmsdk/backup/network.db.$(date +%Y%m%d)
sudo cp /var/lib/zvmsdk/image.db /var/lib/zvmsdk/backup/image.db.$(date +%Y%m%d)
sudo cp /var/lib/zvmsdk/guests.db /var/lib/zvmsdk/backup/guests.db.$(date +%Y%m%d)
sudo cp /var/lib/zvmsdk/fcp.db /var/lib/zvmsdk/backup/fcp.db.$(date +%Y%m%d)

# Verify backups
ls -lh /var/lib/zvmsdk/backup/
```

### Step 2: Install Required Python Packages

```bash
# Install PyMySQL for MariaDB connectivity
pip install pymysql sqlalchemy alembic

# Verify installation
python3 -c "import pymysql; print('PyMySQL version:', pymysql.__version__)"
python3 -c "import sqlalchemy; print('SQLAlchemy version:', sqlalchemy.__version__)"
```

### Step 3: Test Database Connection

**Using Python (no mysql client needed)**:

```bash
cd /root/feilong

# Test with explicit parameters
python scripts/test_db_connection.py \
  --host 172.26.4.78 \
  --user root \
  --password HelloWorld \
  --database nova
```

**Expected Output**:
```
============================================================
  Checking Dependencies
============================================================
✓ PyMySQL installed (version X.X.X)

============================================================
  Testing Network Connectivity
============================================================
ℹ Testing connection to 172.26.4.78:3306
✓ Port 3306 is open on 172.26.4.78

============================================================
  Testing Database Connection
============================================================
ℹ Host: 172.26.4.78
ℹ Port: 3306
ℹ Database: nova
ℹ User: root
ℹ Connecting...
✓ Connection established!
✓ Query execution successful
✓ Server version: 10.3.28-MariaDB
✓ Current database: nova
✓ Connected as: root@your-host
✓ User has X grant(s)
✓ Found X table(s)
✓ Connection closed successfully

============================================================
  Connection Test Complete
============================================================
✓ All tests passed!
```

**If connection fails**, the script will show helpful error messages:
- Access denied → Check username/password
- Connection refused → Check firewall/network
- Unknown database → Database doesn't exist
- Timeout → Network connectivity issues

**Alternative: Test network connectivity only**:
```bash
# Test if port 3306 is reachable
python3 -c "
import socket
s = socket.socket()
s.settimeout(5)
try:
    s.connect(('172.26.4.78', 3306))
    print('✓ Port 3306 is open')
except:
    print('✗ Cannot connect to port 3306')
finally:
    s.close()
"
```

### Step 4: Configure Feilong for Remote Database

Create or edit `/etc/zvmsdk/zvmsdk.conf`:

```bash
sudo mkdir -p /etc/zvmsdk
sudo nano /etc/zvmsdk/zvmsdk.conf
```

Add this configuration:

```ini
[database]
# Database backend
backend = mariadb

# Remote database connection
host = 172.26.4.78
port = 3306
name = nova
user = root
password = HelloWorld

# Connection pool settings
pool_size = 10
pool_recycle = 3600
max_overflow = 20

# Multi-node support (IMPORTANT for OpenStack)
# Replace 'compute-node-01' with your actual compute node hostname
compute_node_id = compute-node-01
```

**Get your compute node ID**:
```bash
# Use your hostname
hostname

# Or use OpenStack compute service name
openstack compute service list --service nova-compute
```

**Set proper permissions**:
```bash
sudo chown root:root /etc/zvmsdk/zvmsdk.conf
sudo chmod 600 /etc/zvmsdk/zvmsdk.conf
```

### Step 5: Create Feilong Tables in Nova Database

```bash
cd /root/feilong

# Run schema creation script
python scripts/create_schema.py
```

**Expected Output**:
```
============================================================
  Verifying Configuration
============================================================
ℹ Database backend: mariadb
ℹ Database host: 172.26.4.78
ℹ Database port: 3306
ℹ Database name: nova
ℹ Database user: root
✓ Database connection successful

============================================================
  Creating Database Schema
============================================================

NETWORK Database:
----------------------------------------
✓ Created table: switch

IMAGE Database:
----------------------------------------
✓ Created table: image

GUEST Database:
----------------------------------------
✓ Created table: guests

FCP Database:
----------------------------------------
✓ Created table: fcp
✓ Created table: template
✓ Created table: template_fcp_mapping
✓ Created table: template_sp_mapping

============================================================
  Schema Creation Complete
============================================================
✓ Created 8 tables across 4 databases
```

### Step 6: Verify Tables Created

**Using Python (no mysql client needed)**:

```bash
cd /root/feilong

# Test connection and list tables
python scripts/test_db_connection.py \
  --host 172.26.4.78 \
  --user root \
  --password HelloWorld \
  --database nova
```

This will show all tables including the new Feilong tables:
- `switch`
- `image`
- `guests`
- `fcp`
- `template`
- `template_fcp_mapping`
- `template_sp_mapping`

**Alternative: Use Python directly**:

```bash
python3 << 'EOF'
import pymysql
conn = pymysql.connect(host='172.26.4.78', user='root', password='HelloWorld', database='nova')
cursor = conn.cursor()
cursor.execute("SHOW TABLES")
tables = [t[0] for t in cursor.fetchall()]
feilong_tables = [t for t in tables if t in ['switch', 'image', 'guests', 'fcp', 'template', 'template_fcp_mapping', 'template_sp_mapping']]
print(f"Feilong tables found: {feilong_tables}")
conn.close()
EOF
```

### Step 7: Migrate Data from SQLite to Nova Database

```bash
cd /root/feilong

# Run data migration script
python scripts/migrate_data.py --sqlite-dir /var/lib/zvmsdk
```

**Expected Output**:
```
============================================================
  Feilong Database Migration Tool
============================================================
ℹ Target database: mariadb
ℹ SQLite source directory: /var/lib/zvmsdk

============================================================
  Starting Data Migration
============================================================

NETWORK Database:
----------------------------------------

Table: switch
ℹ   Found 5 rows
✓   Migrated 5 rows

IMAGE Database:
----------------------------------------

Table: image
ℹ   Found 3 rows
✓   Migrated 3 rows

GUEST Database:
----------------------------------------

Table: guests
ℹ   Found 10 rows
✓   Migrated 10 rows

FCP Database:
----------------------------------------

Table: fcp
ℹ   Found 20 rows
✓   Migrated 20 rows

============================================================
  Migration Complete
============================================================
✓ Migrated 38 rows from 4 databases
```

### Step 8: Verify Data Migrated

**Using Python (no mysql client needed)**:

```bash
python3 << 'EOF'
import pymysql
conn = pymysql.connect(host='172.26.4.78', user='root', password='HelloWorld', database='nova')
cursor = conn.cursor()

tables = ['switch', 'image', 'guests', 'fcp']
print("\nRow counts in nova database:")
print("-" * 40)
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"{table:15} {count:>10} rows")

conn.close()
EOF
```

**Expected Output**:
```
Row counts in nova database:
----------------------------------------
switch                   5 rows
image                    3 rows
guests                  10 rows
fcp                     20 rows
```

### Step 9: Add Multi-Node Support (For OpenStack)

Since you're using OpenStack with the Nova database, you need to add the `compute_node_id` column:

```bash
cd /root/feilong

# Run multi-node migration
# Replace 'compute-node-01' with your actual compute node hostname
python scripts/migrate_to_multinode.py compute-node-01 --database nova
```

**Expected Output**:
```
============================================================
Multi-Node Database Migration
============================================================

Configuration:
  Compute Node ID: compute-node-01
  Database: nova
  Host: 172.26.4.78

============================================================
Adding compute_node_id Column
============================================================

✓ Added compute_node_id to switch
✓ Added compute_node_id to image
✓ Added compute_node_id to guests
✓ Added compute_node_id to fcp
✓ Added compute_node_id to template
✓ Added compute_node_id to template_fcp_mapping
✓ Added compute_node_id to template_sp_mapping

============================================================
Migration Complete
============================================================
✓ Successfully migrated to multi-node architecture
```

### Step 10: Test the Configuration

```bash
cd /root/feilong

# Run database tests
python scripts/test_database_layer.py mariadb
```

**All 6 tests should pass**:
```
Results: 6/6 tests passed
✓ All tests passed successfully!
```

### Step 11: Update Application Configuration

If you have a systemd service for Feilong:

```bash
# Restart the service
sudo systemctl restart zvmsdk

# Check status
sudo systemctl status zvmsdk

# Check logs
sudo journalctl -u zvmsdk -f
```

---

## Configuration Summary

### Your `/etc/zvmsdk/zvmsdk.conf` File

```ini
[database]
backend = mariadb
host = 172.26.4.78
port = 3306
name = nova
user = root
password = HelloWorld
pool_size = 10
pool_recycle = 3600
max_overflow = 20
compute_node_id = compute-node-01
```

### Environment Variables (Alternative)

If you prefer environment variables:

```bash
export ZVMSDK_DB_BACKEND=mariadb
export ZVMSDK_DB_HOST=172.26.4.78
export ZVMSDK_DB_PORT=3306
export ZVMSDK_DB_NAME=nova
export ZVMSDK_DB_USER=root
export ZVMSDK_DB_PASSWORD=HelloWorld
export ZVMSDK_DB_COMPUTE_NODE_ID=compute-node-01
```

---

## Multi-Node OpenStack Setup

If you have multiple compute nodes, **repeat on each node**:

### On Compute Node 2:

```bash
# Configure with unique compute_node_id
sudo nano /etc/zvmsdk/zvmsdk.conf
```

```ini
[database]
backend = mariadb
host = 172.26.4.78
name = nova
user = root
password = HelloWorld
compute_node_id = compute-node-02  # UNIQUE per node
```

### On Compute Node 3:

```ini
compute_node_id = compute-node-03  # UNIQUE per node
```

**Each node will automatically**:
- See only its own data
- Isolate data by `compute_node_id`
- Share the same Nova database

---

## Verification Queries

### Check Data Segregation by Node

**Using Python (no mysql client needed)**:

```bash
python3 << 'EOF'
import pymysql
conn = pymysql.connect(host='172.26.4.78', user='root', password='HelloWorld', database='nova')
cursor = conn.cursor()

print("\nData segregation by compute node:")
print("=" * 60)

# Check guests by node
print("\nGuests by node:")
cursor.execute("SELECT compute_node_id, COUNT(*) FROM guests GROUP BY compute_node_id")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} guests")

# Check switches by node
print("\nSwitches by node:")
cursor.execute("SELECT compute_node_id, COUNT(*) FROM switch GROUP BY compute_node_id")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} switches")

# Check FCP by node
print("\nFCP devices by node:")
cursor.execute("SELECT compute_node_id, COUNT(*) FROM fcp GROUP BY compute_node_id")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} FCP devices")

conn.close()
EOF
```

---

## Troubleshooting

### Connection Refused

```bash
# On database server (172.26.4.78), check MariaDB is listening
sudo netstat -tlnp | grep 3306

# Check bind-address in MariaDB config
sudo grep bind-address /etc/my.cnf.d/*.cnf

# Should be:
# bind-address = 0.0.0.0

# Restart MariaDB if changed
sudo systemctl restart mariadb
```

### Firewall Issues

```bash
# On database server (172.26.4.78)
sudo firewall-cmd --list-all
sudo firewall-cmd --add-port=3306/tcp --permanent
sudo firewall-cmd --reload
```

### Access Denied

```sql
-- On database server, grant remote access
GRANT ALL PRIVILEGES ON nova.* TO 'root'@'%' IDENTIFIED BY 'HelloWorld';
FLUSH PRIVILEGES;
```

### Tables Already Exist

**Using Python (no mysql client needed)**:

```bash
# Drop all Feilong tables if you need to start over
python3 << 'EOF'
import pymysql
conn = pymysql.connect(host='172.26.4.78', user='root', password='HelloWorld', database='nova')
cursor = conn.cursor()

tables = [
    'template_sp_mapping',
    'template_fcp_mapping',
    'template',
    'fcp',
    'guests',
    'image',
    'switch'
]

for table in tables:
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        print(f"✓ Dropped table: {table}")
    except Exception as e:
        print(f"✗ Failed to drop {table}: {e}")

conn.commit()
conn.close()
print("\n✓ All Feilong tables dropped")
EOF

# Then re-run schema creation
cd /root/feilong
python scripts/create_schema.py
```

---

## Rollback Plan

If something goes wrong:

```bash
# 1. Stop Feilong service
sudo systemctl stop zvmsdk

# 2. Restore SQLite configuration
sudo nano /etc/zvmsdk/zvmsdk.conf
```

```ini
[database]
backend = sqlite
dir = /var/lib/zvmsdk
```

```bash
# 3. Restore SQLite databases from backup
sudo cp /var/lib/zvmsdk/backup/network.db.* /var/lib/zvmsdk/network.db
sudo cp /var/lib/zvmsdk/backup/image.db.* /var/lib/zvmsdk/image.db
sudo cp /var/lib/zvmsdk/backup/guests.db.* /var/lib/zvmsdk/guests.db
sudo cp /var/lib/zvmsdk/backup/fcp.db.* /var/lib/zvmsdk/fcp.db

# 4. Restart service
sudo systemctl start zvmsdk
```

---

## Success Checklist

- ☐ SQLite databases backed up
- ☐ PyMySQL and SQLAlchemy installed
- ☐ Connection to 172.26.4.78:3306 successful
- ☐ `/etc/zvmsdk/zvmsdk.conf` configured
- ☐ Feilong tables created in nova database
- ☐ Data migrated from SQLite to nova database
- ☐ Multi-node support added (compute_node_id column)
- ☐ Tests passing (6/6)
- ☐ Application restarted and working
- ☐ Data verified in remote database

---

## Quick Command Reference

```bash
# Test connection
mysql -h 172.26.4.78 -u root -pHelloWorld nova -e "SELECT 1;"

# Create schema
cd /root/feilong && python scripts/create_schema.py

# Migrate data
cd /root/feilong && python scripts/migrate_data.py

# Add multi-node support
cd /root/feilong && python scripts/migrate_to_multinode.py $(hostname)

# Test
cd /root/feilong && python scripts/test_database_layer.py mariadb

# Verify
mysql -h 172.26.4.78 -u root -pHelloWorld nova -e "SHOW TABLES;"
```

---

## Next Steps After Migration

1. **Monitor Performance**: Watch database connection pool usage
2. **Set Up Monitoring**: Add database health checks
3. **Document Node IDs**: Keep track of which compute_node_id maps to which physical server
4. **Plan Backups**: Ensure Nova database backups include Feilong tables
5. **Update Documentation**: Document your specific OpenStack integration

Your Feilong installation will now use the shared OpenStack Nova database at 172.26.4.78!