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
Database engine management for zvmsdk.

This module provides SQLAlchemy engine creation and management for multiple
database backends. It supports SQLite, MySQL, MariaDB, and PostgreSQL.
"""

import os
import contextlib
from typing import Optional, Dict
from sqlalchemy import create_engine, event, pool
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from zvmsdk import config
from zvmsdk import log
from zvmsdk import exception

CONF = config.CONF
LOG = log.LOG

# Global engine cache - one engine per database type
_ENGINES: Dict[str, Engine] = {}
_SESSION_MAKERS: Dict[str, sessionmaker] = {}


class DatabaseConfig:
    """Database configuration helper."""
    
    # Default ports for different database backends
    DEFAULT_PORTS = {
        'mysql': 3306,
        'mariadb': 3306,
        'postgresql': 5432,
    }
    
    # Database file names for SQLite (backward compatibility)
    SQLITE_DB_FILES = {
        'network': 'sdk_network.sqlite',
        'image': 'sdk_image.sqlite',
        'guest': 'sdk_guest.sqlite',
        'fcp': 'sdk_fcp.sqlite',
        'volume': 'sdk_volume.sqlite',
    }
    
    @classmethod
    def get_connection_string(cls, db_type: str = 'main') -> str:
        """
        Generate database connection string based on configuration.
        
        Args:
            db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
                    For SQLite, this determines the database file name.
                    For other backends, all types use the same database with different tables.
        
        Returns:
            SQLAlchemy connection string
        """
        # If connection_string is explicitly provided, use it
        if CONF.database.connection_string:
            return CONF.database.connection_string
        
        backend = CONF.database.backend.lower()
        
        if backend == 'sqlite':
            return cls._get_sqlite_connection_string(db_type)
        elif backend in ('mysql', 'mariadb'):
            return cls._get_mysql_connection_string()
        elif backend == 'postgresql':
            return cls._get_postgresql_connection_string()
        else:
            raise exception.SDKDatabaseException(
                msg=f"Unsupported database backend: {backend}"
            )
    
    @classmethod
    def _get_sqlite_connection_string(cls, db_type: str) -> str:
        """Generate SQLite connection string."""
        db_dir = CONF.database.dir
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, 0o755)
        
        # Use specific database file for backward compatibility
        db_file = cls.SQLITE_DB_FILES.get(db_type, 'sdk_main.sqlite')
        db_path = os.path.join(db_dir, db_file)
        
        # SQLite connection string format
        return f"sqlite:///{db_path}"
    
    @classmethod
    def _get_mysql_connection_string(cls) -> str:
        """Generate MySQL/MariaDB connection string."""
        host = CONF.database.host
        port = CONF.database.port or cls.DEFAULT_PORTS['mysql']
        database = CONF.database.name
        user = CONF.database.user
        password = CONF.database.password
        
        if not password:
            raise exception.SDKDatabaseException(
                msg="Database password is required for MySQL/MariaDB"
            )
        
        # Use pymysql driver for MySQL/MariaDB
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    
    @classmethod
    def _get_postgresql_connection_string(cls) -> str:
        """Generate PostgreSQL connection string."""
        host = CONF.database.host
        port = CONF.database.port or cls.DEFAULT_PORTS['postgresql']
        database = CONF.database.name
        user = CONF.database.user
        password = CONF.database.password
        
        if not password:
            raise exception.SDKDatabaseException(
                msg="Database password is required for PostgreSQL"
            )
        
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _configure_sqlite_engine(engine: Engine) -> None:
    """
    Configure SQLite-specific settings.
    
    Args:
        engine: SQLAlchemy engine instance
    """
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Enable foreign keys and set journal mode for SQLite."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
        cursor.close()


def _configure_mysql_engine(engine: Engine) -> None:
    """
    Configure MySQL/MariaDB-specific settings.
    
    Args:
        engine: SQLAlchemy engine instance
    """
    @event.listens_for(engine, "connect")
    def set_mysql_charset(dbapi_conn, connection_record):
        """Set charset to utf8mb4 for full Unicode support."""
        cursor = dbapi_conn.cursor()
        cursor.execute("SET NAMES utf8mb4")
        cursor.close()


def create_db_engine(db_type: str = 'main', force_new: bool = False) -> Engine:
    """
    Create or retrieve a SQLAlchemy engine for the specified database type.
    
    Args:
        db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
        force_new: If True, create a new engine even if one exists
    
    Returns:
        SQLAlchemy Engine instance
    """
    global _ENGINES
    
    # Return cached engine if available and not forcing new
    if not force_new and db_type in _ENGINES:
        return _ENGINES[db_type]
    
    # Get connection string
    connection_string = DatabaseConfig.get_connection_string(db_type)
    backend = CONF.database.backend.lower()
    
    # Engine configuration
    engine_args = {
        'echo': CONF.database.echo,
        'future': True,  # Use SQLAlchemy 2.0 style
    }
    
    # Configure connection pooling for non-SQLite backends
    if backend != 'sqlite':
        engine_args.update({
            'pool_size': CONF.database.pool_size,
            'max_overflow': CONF.database.max_overflow,
            'pool_recycle': CONF.database.pool_recycle,
            'pool_pre_ping': True,  # Verify connections before using
        })
    else:
        # SQLite uses NullPool for better concurrency with file-based DB
        engine_args['poolclass'] = pool.NullPool
    
    # Create engine
    try:
        engine = create_engine(connection_string, **engine_args)
        LOG.info(f"Created database engine for {db_type} using {backend} backend")
    except Exception as e:
        LOG.error(f"Failed to create database engine: {e}")
        raise exception.SDKDatabaseException(
            msg=f"Failed to create database engine: {e}"
        )
    
    # Configure backend-specific settings
    if backend == 'sqlite':
        _configure_sqlite_engine(engine)
    elif backend in ('mysql', 'mariadb'):
        _configure_mysql_engine(engine)
    
    # Cache the engine
    _ENGINES[db_type] = engine
    
    return engine


def get_engine(db_type: str = 'main') -> Engine:
    """
    Get the SQLAlchemy engine for the specified database type.
    
    Args:
        db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
    
    Returns:
        SQLAlchemy Engine instance
    """
    return create_db_engine(db_type)


def create_session_maker(db_type: str = 'main') -> sessionmaker:
    """
    Create or retrieve a session maker for the specified database type.
    
    Args:
        db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
    
    Returns:
        SQLAlchemy sessionmaker instance
    """
    global _SESSION_MAKERS
    
    if db_type not in _SESSION_MAKERS:
        engine = get_engine(db_type)
        _SESSION_MAKERS[db_type] = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False
        )
    
    return _SESSION_MAKERS[db_type]


def get_session(db_type: str = 'main') -> Session:
    """
    Get a new database session for the specified database type.
    
    Args:
        db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
    
    Returns:
        SQLAlchemy Session instance
    """
    session_maker = create_session_maker(db_type)
    return session_maker()


@contextlib.contextmanager
def session_scope(db_type: str = 'main'):
    """
    Provide a transactional scope around a series of operations.
    
    This context manager handles session creation, commit, and rollback
    automatically. Use this for database operations that need transaction
    management.
    
    Args:
        db_type: Type of database ('main', 'network', 'image', 'guest', 'fcp')
    
    Yields:
        SQLAlchemy Session instance
    
    Example:
        with session_scope('network') as session:
            session.execute(...)
            # Automatically commits on success, rolls back on exception
    """
    session = get_session(db_type)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        LOG.error(f"Database session error: {e}")
        raise
    finally:
        session.close()


def dispose_engine(db_type: Optional[str] = None) -> None:
    """
    Dispose of database engine(s) and close all connections.
    
    Args:
        db_type: Specific database type to dispose, or None to dispose all
    """
    global _ENGINES, _SESSION_MAKERS
    
    if db_type:
        # Dispose specific engine
        if db_type in _ENGINES:
            _ENGINES[db_type].dispose()
            del _ENGINES[db_type]
            LOG.info(f"Disposed database engine for {db_type}")
        if db_type in _SESSION_MAKERS:
            del _SESSION_MAKERS[db_type]
    else:
        # Dispose all engines
        for dtype, engine in _ENGINES.items():
            engine.dispose()
            LOG.info(f"Disposed database engine for {dtype}")
        _ENGINES.clear()
        _SESSION_MAKERS.clear()


def test_connection(db_type: str = 'main') -> bool:
    """
    Test database connection.
    
    Args:
        db_type: Type of database to test
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        from sqlalchemy import text
        engine = get_engine(db_type)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        LOG.info(f"Database connection test successful for {db_type}")
        return True
    except Exception as e:
        LOG.error(f"Database connection test failed for {db_type}: {e}")
        return False

# Made with Bob
