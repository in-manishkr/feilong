# Database Abstraction Layer Design

## Executive Summary

This document outlines the design and implementation plan for introducing a database abstraction layer to the Feilong project. The current implementation uses SQLite3 directly with raw SQL queries. The new design will support multiple database backends (SQLite3, MySQL, MariaDB) while maintaining backward compatibility.

## Current State Analysis

### Existing Implementation

The current database layer (`zvmsdk/database.py`, 2644 lines) has the following characteristics:

1. **Direct SQLite3 Usage**: Uses `sqlite3` module directly
2. **Multiple Database Files**: 
   - `sdk_network.sqlite` - Network/switch configuration
   - `sdk_image.sqlite` - Image metadata
   - `sdk_guest.sqlite` - Guest/VM information
   - `sdk_fcp.sqlite` - FCP device management
   - `sdk_volume.sqlite` - Volume management

3. **Database Operators**:
   - `NetworkDbOperator` - Manages switch table
   - `ImageDbOperator` - Manages image table
   - `GuestDbOperator` - Manages guests table
   - `FCPDbOperator` - Manages FCP devices and templates (4 tables)

4. **Connection Management**:
   - Context managers: `get_network_conn()`, `get_image_conn()`, `get_guest_conn()`, `get_fcp_conn()`
   - Thread locks for each connection type
   - Global connection objects

5. **Raw SQL Queries**: All operations use raw SQL strings

### Key Tables

#### Network Database
- **switch**: userid, interface, switch, port, comments

#### Image Database
- **image**: imagename, imageosdistro, md5sum, disk_size_units, image_size_in_bytes, type, comments

#### Guest Database
- **guests**: id (UUID), userid, metadata, net_set, comments

#### FCP Database
- **fcp**: fcp_id, assigner_id, connections, reserved, wwpn_npiv, wwpn_phy, chpid, pchid, state, owner, tmpl_id
- **template**: id, name, description, is_default, min_fcp_paths_count
- **template_sp_mapping**: sp_name, tmpl_id
- **template_fcp_mapping**: fcp_id, tmpl_id, path

## Design Goals

1. **Multi-Database Support**: SQLite3, MySQL, MariaDB (PostgreSQL-ready)
2. **Backward Compatibility**: Existing SQLite users continue working
3. **Minimal Breaking Changes**: Preserve existing API where possible
4. **Configuration-Driven**: Database backend selection via configuration
5. **Migration Support**: Tools to migrate existing SQLite data
6. **Maintainability**: Clean separation of concerns
7. **Extensibility**: Easy to add new database backends

## Architecture Design

### Layer Structure

```
┌─────────────────────────────────────────────────────────┐
│           Application Layer (vmops, imageops, etc)      │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│         Repository Layer (NetworkRepo, ImageRepo, etc)  │
│         - High-level business operations                │
│         - Maintains existing DbOperator API             │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Database Abstraction Layer                 │
│         - SQLAlchemy Core (not ORM)                     │
│         - Connection pooling                            │
│         - Transaction management                        │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Database Backends                          │
│         SQLite3  │  MySQL  │  MariaDB  │  PostgreSQL   │
└─────────────────────────────────────────────────────────┘
```

### Component Design

#### 1. Configuration Schema

Add to `zvmsdk/config.py`:

```python
Opt('backend',
    section='database',
    default='sqlite',
    help='Database backend: sqlite, mysql, mariadb, postgresql'),

Opt('connection_string',
    section='database',
    default=None,
    help='Database connection string (overrides other settings)'),

Opt('host',
    section='database',
    default='localhost',
    help='Database host for remote databases'),

Opt('port',
    section='database',
    default=None,
    opt_type='int',
    help='Database port (default: 3306 for MySQL/MariaDB, 5432 for PostgreSQL)'),

Opt('name',
    section='database',
    default='zvmsdk',
    help='Database name'),

Opt('user',
    section='database',
    default='zvmsdk',
    help='Database user'),

Opt('password',
    section='database',
    default=None,
    help='Database password'),

Opt('pool_size',
    section='database',
    default=10,
    opt_type='int',
    help='Connection pool size'),

Opt('pool_recycle',
    section='database',
    default=3600,
    opt_type='int',
    help='Connection pool recycle time in seconds'),

Opt('max_overflow',
    section='database',
    default=20,
    opt_type='int',
    help='Maximum overflow connections'),
```

#### 2. Database Engine Manager

**File**: `zvmsdk/db/engine.py`

Responsibilities:
- Create and manage SQLAlchemy engines
- Handle connection pooling
- Provide database-specific configurations
- Support multiple database instances (network, image, guest, fcp)

#### 3. Table Definitions

**File**: `zvmsdk/db/models.py`

Use SQLAlchemy Core (not ORM) to define tables:
- Maintains schema definitions in Python
- Supports multiple database backends
- Enables Alembic migrations

#### 4. Repository Pattern

**Files**: 
- `zvmsdk/db/repositories/network.py`
- `zvmsdk/db/repositories/image.py`
- `zvmsdk/db/repositories/guest.py`
- `zvmsdk/db/repositories/fcp.py`

Responsibilities:
- Implement business logic for database operations
- Maintain backward-compatible API with existing DbOperators
- Use SQLAlchemy Core for queries
- Handle transactions

#### 5. Migration Support

**Directory**: `zvmsdk/db/migrations/`

- Alembic configuration
- Version scripts
- Data migration utilities

### Backward Compatibility Strategy

1. **Dual Implementation Period**:
   - Keep existing `database.py` as `database_legacy.py`
   - New code uses repository layer
   - Configuration flag to switch between implementations

2. **API Preservation**:
   - Repository classes maintain same method signatures as DbOperators
   - Existing code continues to work with minimal changes

3. **Migration Path**:
   - Provide migration tool to convert SQLite to new backend
   - Support running both implementations side-by-side during transition

## Implementation Plan

### Phase 1: Foundation (Week 1-2)

1. Add SQLAlchemy and Alembic to requirements
2. Create database configuration schema
3. Implement engine manager
4. Define table models using SQLAlchemy Core

### Phase 2: Repository Layer (Week 3-4)

1. Implement NetworkRepository
2. Implement ImageRepository
3. Implement GuestRepository
4. Implement FCPRepository
5. Add comprehensive unit tests

### Phase 3: Migration Support (Week 5)

1. Set up Alembic
2. Create initial migration scripts
3. Implement data migration tool from SQLite
4. Test migrations with all supported backends

### Phase 4: Integration (Week 6)

1. Update existing code to use repositories
2. Add integration tests
3. Performance testing and optimization
4. Documentation updates

### Phase 5: Deployment (Week 7)

1. Backward compatibility testing
2. Migration guide
3. Configuration examples
4. Release preparation

## Database Connection Strings

### SQLite (Default)
```
sqlite:////var/lib/zvmsdk/databases/zvmsdk.db
```

### MySQL/MariaDB
```
mysql+pymysql://user:password@localhost:3306/zvmsdk
```

### PostgreSQL (Future)
```
postgresql://user:password@localhost:5432/zvmsdk
```

## Migration Strategy

### For Existing SQLite Users

1. **No Action Required**: Continue using SQLite with no changes
2. **Optional Migration**: Use migration tool to move to MySQL/MariaDB
3. **Configuration Update**: Update `zvmsdk.conf` to specify new backend

### Migration Tool

```bash
zvmsdk-migrate --from sqlite --to mysql \
  --source /var/lib/zvmsdk/databases/ \
  --target mysql://user:pass@host/zvmsdk
```

## Testing Strategy

1. **Unit Tests**: Test each repository independently
2. **Integration Tests**: Test with all supported backends
3. **Migration Tests**: Verify data integrity after migration
4. **Performance Tests**: Compare performance across backends
5. **Backward Compatibility Tests**: Ensure existing code works

## Security Considerations

1. **Password Storage**: Never store passwords in code
2. **Connection Encryption**: Support SSL/TLS for remote databases
3. **SQL Injection**: Use parameterized queries (SQLAlchemy handles this)
4. **Access Control**: Database-level permissions
5. **Audit Logging**: Log database operations

## Performance Considerations

1. **Connection Pooling**: Reuse connections efficiently
2. **Query Optimization**: Use indexes appropriately
3. **Batch Operations**: Support bulk inserts/updates
4. **Caching**: Consider caching frequently accessed data
5. **Monitoring**: Add metrics for database operations

## Dependencies

### New Requirements

```
SQLAlchemy>=1.4.0,<2.0.0
alembic>=1.7.0
PyMySQL>=1.0.0  # For MySQL/MariaDB
psycopg2-binary>=2.9.0  # For PostgreSQL (future)
```

## Configuration Example

```ini
[database]
# Backend selection: sqlite, mysql, mariadb, postgresql
backend = mysql

# For SQLite (default)
dir = /var/lib/zvmsdk/databases/

# For MySQL/MariaDB
host = localhost
port = 3306
name = zvmsdk
user = zvmsdk
password = <secure_password>

# Connection pool settings
pool_size = 10
pool_recycle = 3600
max_overflow = 20
```

## Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing deployments | High | Maintain backward compatibility, thorough testing |
| Performance degradation | Medium | Performance testing, optimization |
| Data loss during migration | High | Backup procedures, migration validation |
| Increased complexity | Medium | Clear documentation, training |
| Database-specific bugs | Medium | Comprehensive testing across all backends |

## Success Criteria

1. ✅ Support SQLite3, MySQL, and MariaDB
2. ✅ Zero breaking changes for existing SQLite users
3. ✅ Migration tool successfully migrates data
4. ✅ Performance within 10% of current implementation
5. ✅ All existing tests pass
6. ✅ Comprehensive documentation
7. ✅ Easy to add PostgreSQL support later

## Future Enhancements

1. **PostgreSQL Support**: Add when needed
2. **Read Replicas**: Support read-only replicas for scaling
3. **Sharding**: Distribute data across multiple databases
4. **Async Support**: Add async database operations
5. **ORM Layer**: Optional ORM for complex queries

## Conclusion

This design provides a robust, maintainable database abstraction layer that supports multiple backends while maintaining backward compatibility. The phased implementation approach minimizes risk and allows for iterative improvements.