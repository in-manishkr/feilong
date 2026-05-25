# Quick Test - Database Layer

## TL;DR - How to Test in 30 Seconds

```bash
# 1. Install dependencies (if not already done)
pip install -r requirements.txt

# 2. Run the test script
python scripts/test_database_layer.py

# 3. Look for this at the end:
# ✓ All tests passed!
```

That's it! If you see "All tests passed!", the database layer is working correctly.

## What Gets Tested

The test script automatically verifies:

1. ✅ **Engine Creation** - Can create database engines
2. ✅ **Connection** - Can connect to databases
3. ✅ **Table Creation** - Can create tables
4. ✅ **CRUD Operations** - Can INSERT, SELECT, UPDATE, DELETE
5. ✅ **Transactions** - Transactions roll back on errors
6. ✅ **Bulk Operations** - Can handle multiple records

## Expected Output

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

============================================================
              Testing Table Creation
============================================================

✓ Created tables for network database
✓ Created tables for image database
✓ Created tables for guest database
✓ Created tables for fcp database

============================================================
           Testing NetworkRepository
============================================================

✓ NetworkRepository initialized
ℹ Testing INSERT operation...
✓ INSERT: Added test record
ℹ Testing SELECT operation...
✓ SELECT: Found 1 record
ℹ   Record: {'userid': 'TESTVM01', 'interface': '1000', 'switch': 'VSWITCH1', 'port': 'testport123', 'comments': 'Test record'}
ℹ Testing UPDATE operation...
✓ UPDATE: Switch updated successfully
ℹ Testing DELETE operation...
✓ DELETE: Record deleted successfully

============================================================
          Testing Transaction Rollback
============================================================

✓ Added initial record
✓ Transaction correctly rolled back on error
✓ Original record intact after rollback

============================================================
            Testing Bulk Operations
============================================================

ℹ Adding 5 test records...
✓ Added 5 records
✓ Found all 5 test records
ℹ Cleaning up test records...
✓ Cleanup complete

============================================================
                    Cleanup
============================================================

✓ Disposed all database engines

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

## Testing with MySQL/MariaDB

```bash
# Set up test database first (one time)
mysql -u root -p << 'EOF'
CREATE DATABASE zvmsdk_test;
CREATE USER 'zvmsdk'@'localhost' IDENTIFIED BY 'test_password';
GRANT ALL PRIVILEGES ON zvmsdk_test.* TO 'zvmsdk'@'localhost';
FLUSH PRIVILEGES;
EOF

# Set environment variables
export ZVMSDK_DB_HOST=localhost
export ZVMSDK_DB_NAME=zvmsdk_test
export ZVMSDK_DB_USER=zvmsdk
export ZVMSDK_DB_PASSWORD=test_password

# Run test
python scripts/test_database_layer.py mysql
```

## Manual Quick Test

If you prefer to test manually:

```python
python3 << 'EOF'
# Test imports
from zvmsdk import config
from zvmsdk.db.repositories import NetworkRepository

# Load config
config.load_config()

# Test CRUD
repo = NetworkRepository()
repo.switch_add_record(userid='TEST', interface='1000', port='test')
records = repo.switch_select_record_for_userid('TEST')
print(f"✓ Found {len(records)} record(s)")
repo.switch_delete_record_for_userid('TEST')
print("✓ All operations successful!")
EOF
```

## Troubleshooting

### If you see errors about missing modules:

```bash
pip install -r requirements.txt
```

### If you see permission errors:

```bash
sudo mkdir -p /var/lib/zvmsdk/databases/
sudo chown $USER:$USER /var/lib/zvmsdk/databases/
```

### If tests fail:

1. Check the error message - it usually tells you what's wrong
2. See the full testing guide: `docs/TESTING_GUIDE.md`
3. Check configuration: `cat /etc/zvmsdk/zvmsdk.conf`

## What This Proves

When tests pass, you know:

- ✅ SQLAlchemy is installed and working
- ✅ Database engines can be created
- ✅ Connections work
- ✅ Tables can be created
- ✅ The NetworkRepository is fully functional
- ✅ Transactions work correctly
- ✅ The abstraction layer is ready to use

## Next Steps

After successful testing:

1. **Use it in your code**:
   ```python
   from zvmsdk.db.repositories import NetworkRepository
   repo = NetworkRepository()
   # Use repo methods...
   ```

2. **Complete remaining repositories** (Image, Guest, FCP)

3. **Deploy to production** with confidence

## More Information

- Full testing guide: [`docs/TESTING_GUIDE.md`](TESTING_GUIDE.md)
- Implementation guide: [`docs/database_implementation_guide.md`](database_implementation_guide.md)
- Architecture design: [`docs/database_abstraction_layer_design.md`](database_abstraction_layer_design.md)
- Project summary: [`docs/DATABASE_REDESIGN_SUMMARY.md`](DATABASE_REDESIGN_SUMMARY.md)