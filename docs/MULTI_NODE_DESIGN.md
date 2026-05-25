# Multi-Compute-Node Database Design

## Problem Statement

When multiple z/VM compute nodes share a single remote database (e.g., OpenStack Nova database), we need to ensure:

1. **Data Segregation**: Each compute node's data must be isolated
2. **Query Filtering**: All queries must automatically filter by compute node
3. **No Cross-Node Interference**: Node A cannot see or modify Node B's data
4. **Backward Compatibility**: Single-node deployments continue to work

## Solution: Compute Node Identifier

### Architecture

Add a `compute_node_id` column to all tables to identify which compute node owns each record.

```
┌─────────────────────────────────────────────────────┐
│           Shared Remote Database (nova)             │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  switch table                                │  │
│  ├────────────┬──────────┬────────────────────┤  │
│  │ compute_id │ userid   │ interface  │ ...   │  │
│  ├────────────┼──────────┼────────────────────┤  │
│  │ node1      │ VM01     │ 1000       │ ...   │  │
│  │ node1      │ VM02     │ 1000       │ ...   │  │
│  │ node2      │ VM01     │ 1000       │ ...   │  │ ← Different node
│  │ node2      │ VM03     │ 1000       │ ...   │  │
│  └────────────┴──────────┴────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Implementation Strategy

#### 1. Schema Changes

Add `compute_node_id` column to all tables:

```sql
-- Example for switch table
ALTER TABLE switch ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

-- Update primary keys to include compute_node_id
ALTER TABLE switch DROP PRIMARY KEY;
ALTER TABLE switch ADD PRIMARY KEY (compute_node_id, userid, interface);
```

#### 2. Configuration

Add compute node identifier to configuration:

```ini
[database]
backend = mysql
host = nova-db.example.com
name = nova
compute_node_id = compute-node-01  # Unique identifier for this node

# Alternative: Auto-detect from hostname
# compute_node_id = auto  # Uses hostname
```

#### 3. Automatic Query Filtering

All repository methods automatically add `compute_node_id` filter:

```python
# Before (single node)
SELECT * FROM switch WHERE userid = 'VM01'

# After (multi-node)
SELECT * FROM switch 
WHERE compute_node_id = 'compute-node-01' 
  AND userid = 'VM01'
```

## Implementation Details

### Phase 1: Schema Migration

#### Step 1: Add compute_node_id Column

```sql
-- For each table, add the column
ALTER TABLE switch 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE image 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE guests 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE fcp 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE template 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE template_sp_mapping 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';

ALTER TABLE template_fcp_mapping 
ADD COLUMN compute_node_id VARCHAR(64) NOT NULL DEFAULT 'default';
```

#### Step 2: Update Primary Keys

```sql
-- switch table
ALTER TABLE switch DROP PRIMARY KEY;
ALTER TABLE switch ADD PRIMARY KEY (compute_node_id, userid, interface);

-- image table  
ALTER TABLE image DROP PRIMARY KEY;
ALTER TABLE image ADD PRIMARY KEY (compute_node_id, imagename);

-- guests table
ALTER TABLE guests DROP PRIMARY KEY;
ALTER TABLE guests ADD PRIMARY KEY (compute_node_id, id);
ALTER TABLE guests ADD UNIQUE KEY (compute_node_id, userid);

-- fcp table
ALTER TABLE fcp DROP PRIMARY KEY;
ALTER TABLE fcp ADD PRIMARY KEY (compute_node_id, fcp_id);

-- template table
ALTER TABLE template DROP PRIMARY KEY;
ALTER TABLE template ADD PRIMARY KEY (compute_node_id, id);

-- template_sp_mapping table
ALTER TABLE template_sp_mapping DROP PRIMARY KEY;
ALTER TABLE template_sp_mapping ADD PRIMARY KEY (compute_node_id, sp_name);

-- template_fcp_mapping table
ALTER TABLE template_fcp_mapping DROP PRIMARY KEY;
ALTER TABLE template_fcp_mapping ADD PRIMARY KEY (compute_node_id, fcp_id, tmpl_id);
```

#### Step 3: Add Indexes

```sql
-- Add indexes for efficient filtering
CREATE INDEX idx_switch_compute_node ON switch(compute_node_id);
CREATE INDEX idx_image_compute_node ON image(compute_node_id);
CREATE INDEX idx_guests_compute_node ON guests(compute_node_id);
CREATE INDEX idx_fcp_compute_node ON fcp(compute_node_id);
CREATE INDEX idx_template_compute_node ON template(compute_node_id);
```

### Phase 2: Code Changes

#### Update Configuration (zvmsdk/config.py)

```python
Opt('compute_node_id',
    section='database',
    default='auto',
    opt_type='str',
    help='''
Compute node identifier for multi-node deployments.

When multiple compute nodes share a single database, this identifier
ensures data segregation between nodes. Each node's data is tagged
with its compute_node_id and queries are automatically filtered.

Possible values:
    'auto': Use hostname as compute node ID (recommended)
    'default': Single-node deployment (backward compatible)
    '<custom>': Any unique string identifying this compute node

For OpenStack deployments, this should match the compute node's
hostname or a unique identifier in the deployment.

Example: 'compute-node-01', 'zvm-compute-1', etc.
    '''),
```

#### Update Models (zvmsdk/db/models.py)

```python
# Add compute_node_id to all tables
switch_table = Table(
    'switch',
    metadata,
    Column('compute_node_id', String(64), nullable=False, default='default',
           index=True, comment='Compute node identifier'),
    Column('userid', String(8), nullable=False, index=True),
    Column('interface', String(4), nullable=False),
    # ... other columns ...
    PrimaryKeyConstraint('compute_node_id', 'userid', 'interface'),
)

# Similar changes for all other tables
```

#### Update Base Repository (zvmsdk/db/repositories/base.py)

```python
class BaseRepository:
    def __init__(self, db_type: str, module_id: str = 'database'):
        self.db_type = db_type
        self._module_id = module_id
        self._compute_node_id = self._get_compute_node_id()
        self._ensure_tables_exist()
    
    def _get_compute_node_id(self) -> str:
        """Get the compute node identifier."""
        node_id = CONF.database.compute_node_id
        
        if node_id == 'auto':
            # Use hostname
            import socket
            return socket.gethostname()
        
        return node_id
    
    def _add_compute_node_filter(self, where_clause):
        """Add compute_node_id filter to WHERE clause."""
        from sqlalchemy import and_
        
        # Get the table from the where clause
        # This is a simplified version - actual implementation
        # would need to handle different query types
        compute_filter = (table.c.compute_node_id == self._compute_node_id)
        
        if where_clause is not None:
            return and_(compute_filter, where_clause)
        return compute_filter
    
    def insert_record(self, table, values: Dict[str, Any], 
                     connection: Optional[Connection] = None):
        """Insert a single record with compute_node_id."""
        # Automatically add compute_node_id
        values['compute_node_id'] = self._compute_node_id
        
        query = insert(table).values(**values)
        
        if connection:
            connection.execute(query)
        else:
            with self.transaction() as conn:
                conn.execute(query)
    
    def select_all(self, table, where_clause=None, order_by=None,
                  connection: Optional[Connection] = None):
        """Select records with automatic compute_node_id filtering."""
        # Add compute_node_id filter
        where_clause = self._add_compute_node_filter(where_clause)
        
        query = select(table).where(where_clause)
        
        if order_by is not None:
            query = query.order_by(order_by)
        
        return self.fetch_all(query, connection)
```

#### Update NetworkRepository (zvmsdk/db/repositories/network.py)

```python
class NetworkRepository(BaseRepository):
    def switch_add_record(self, userid: str, interface: str, 
                         port: Optional[str] = None,
                         switch: Optional[str] = None, 
                         comments: Optional[str] = None):
        """Add switch record with automatic compute_node_id."""
        values = {
            'compute_node_id': self._compute_node_id,  # Automatically added
            'userid': userid,
            'interface': interface,
            'switch': switch,
            'port': port,
            'comments': comments
        }
        
        self.insert_record(switch_table, values)
    
    def switch_select_record_for_userid(self, userid: str):
        """Select records for userid on this compute node only."""
        where_clause = and_(
            switch_table.c.compute_node_id == self._compute_node_id,
            switch_table.c.userid == userid
        )
        return self.select_all(switch_table, where_clause)
```

### Phase 3: Migration Script

Create migration script for existing deployments:

```python
#!/usr/bin/env python3
"""
Migrate existing single-node database to multi-node schema.

This script:
1. Adds compute_node_id column to all tables
2. Updates primary keys
3. Migrates existing data with specified compute_node_id
"""

import sys
from zvmsdk import config
from zvmsdk.db import engine
from sqlalchemy import text

def migrate_to_multinode(compute_node_id='default'):
    """Migrate database schema for multi-node support."""
    
    print(f"Migrating database for compute node: {compute_node_id}")
    
    # Get engine
    eng = engine.get_engine('network')
    
    with eng.begin() as conn:
        # Add compute_node_id column
        print("Adding compute_node_id column to switch table...")
        conn.execute(text(
            "ALTER TABLE switch "
            "ADD COLUMN compute_node_id VARCHAR(64) "
            f"NOT NULL DEFAULT '{compute_node_id}'"
        ))
        
        # Update primary key
        print("Updating primary key...")
        conn.execute(text("ALTER TABLE switch DROP PRIMARY KEY"))
        conn.execute(text(
            "ALTER TABLE switch "
            "ADD PRIMARY KEY (compute_node_id, userid, interface)"
        ))
        
        # Add index
        print("Adding index...")
        conn.execute(text(
            "CREATE INDEX idx_switch_compute_node "
            "ON switch(compute_node_id)"
        ))
    
    print("Migration complete!")

if __name__ == '__main__':
    node_id = sys.argv[1] if len(sys.argv) > 1 else 'default'
    migrate_to_multinode(node_id)
```

## Deployment Guide

### For New Deployments

1. **Configure compute node ID**:
```ini
[database]
backend = mysql
host = nova-db.example.com
name = nova
compute_node_id = auto  # or specific ID
```

2. **Deploy normally** - tables will be created with compute_node_id

### For Existing Deployments

1. **Backup database**:
```bash
mysqldump -u root -p nova > nova_backup.sql
```

2. **Run migration**:
```bash
python scripts/migrate_multinode.py compute-node-01
```

3. **Update configuration**:
```ini
[database]
compute_node_id = compute-node-01
```

4. **Restart services**

### For Multiple Compute Nodes

Each compute node needs unique configuration:

**Node 1** (`/etc/zvmsdk/zvmsdk.conf`):
```ini
[database]
backend = mysql
host = nova-db.example.com
name = nova
compute_node_id = compute-node-01
```

**Node 2** (`/etc/zvmsdk/zvmsdk.conf`):
```ini
[database]
backend = mysql
host = nova-db.example.com
name = nova
compute_node_id = compute-node-02
```

## Testing Multi-Node Setup

```python
# On Node 1
from zvmsdk.db.repositories import NetworkRepository
repo1 = NetworkRepository()
repo1.switch_add_record(userid='VM01', interface='1000', port='port1')

# On Node 2
from zvmsdk.db.repositories import NetworkRepository
repo2 = NetworkRepository()
repo2.switch_add_record(userid='VM01', interface='1000', port='port2')

# Verify isolation
records1 = repo1.switch_select_record_for_userid('VM01')
records2 = repo2.switch_select_record_for_userid('VM01')

# Each node sees only its own data
assert len(records1) == 1 and records1[0]['port'] == 'port1'
assert len(records2) == 1 and records2[0]['port'] == 'port2'
```

## Benefits

1. **Data Isolation**: Each compute node's data is completely isolated
2. **Scalability**: Support unlimited compute nodes
3. **Centralized Management**: Single database for all nodes
4. **Backward Compatible**: Single-node deployments use 'default' ID
5. **OpenStack Integration**: Works seamlessly with Nova database
6. **Query Performance**: Indexes ensure efficient filtering

## Security Considerations

1. **Database Permissions**: Each compute node should have its own database user
2. **Row-Level Security**: Consider MySQL/PostgreSQL row-level security policies
3. **Audit Logging**: Log all cross-node access attempts
4. **Validation**: Verify compute_node_id in all operations

## Next Steps

1. Implement compute_node_id in models.py
2. Update base repository with automatic filtering
3. Create migration script
4. Update all repository implementations
5. Add comprehensive tests for multi-node scenarios
6. Update documentation

## Summary

This design ensures complete data segregation in multi-compute-node deployments while maintaining backward compatibility with single-node setups. The compute_node_id is automatically added to all operations, making it transparent to application code.