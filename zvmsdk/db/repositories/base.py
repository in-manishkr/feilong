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
Base repository class for database operations.

This module provides the base class for all repository implementations,
offering common functionality for database operations using SQLAlchemy Core.
"""

import contextlib
from typing import Optional, List, Dict, Any
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.engine import Engine, Connection
from sqlalchemy.orm import Session

from zvmsdk import log
from zvmsdk import exception
from zvmsdk.db import engine as db_engine
from zvmsdk.db import models

LOG = log.LOG


class BaseRepository:
    """
    Base repository class providing common database operations.
    
    This class provides a foundation for all repository implementations,
    offering:
    - Connection management
    - Transaction handling
    - Common CRUD operations
    - Error handling
    """
    
    def __init__(self, db_type: str, module_id: str = 'database'):
        """
        Initialize the repository.
        
        Args:
            db_type: Database type ('network', 'image', 'guest', 'fcp')
            module_id: Module identifier for error messages
        """
        self.db_type = db_type
        self._module_id = module_id
        self._engine: Optional[Engine] = None
        self._ensure_tables_exist()
    
    @property
    def engine(self) -> Engine:
        """Get the SQLAlchemy engine for this repository."""
        if self._engine is None:
            self._engine = db_engine.get_engine(self.db_type)
        return self._engine
    
    def _ensure_tables_exist(self):
        """Ensure all required tables exist in the database."""
        try:
            tables = models.get_tables_by_database_type(self.db_type)
            for table in tables:
                table.create(self.engine, checkfirst=True)
            LOG.debug(f"Ensured tables exist for {self.db_type} database")
        except Exception as e:
            LOG.error(f"Failed to create tables for {self.db_type}: {e}")
            raise exception.SDKDatabaseException(
                msg=f"Failed to create tables: {e}"
            )
    
    @contextlib.contextmanager
    def get_connection(self):
        """
        Get a database connection with automatic cleanup.
        
        Yields:
            SQLAlchemy Connection object
        """
        conn = self.engine.connect()
        try:
            yield conn
        except Exception as e:
            LOG.error(f"Database operation error: {e}")
            raise
        finally:
            conn.close()
    
    @contextlib.contextmanager
    def transaction(self):
        """
        Provide a transactional scope for database operations.
        
        Yields:
            SQLAlchemy Connection object with active transaction
        """
        with self.engine.begin() as conn:
            try:
                yield conn
            except Exception as e:
                LOG.error(f"Transaction error: {e}")
                raise
    
    def execute_query(self, query, connection: Optional[Connection] = None):
        """
        Execute a query and return results.
        
        Args:
            query: SQLAlchemy query object
            connection: Optional existing connection to use
        
        Returns:
            Query result
        """
        if connection:
            return connection.execute(query)
        else:
            with self.get_connection() as conn:
                return conn.execute(query)
    
    def fetch_all(self, query, connection: Optional[Connection] = None) -> List[Dict[str, Any]]:
        """
        Execute a query and fetch all results as dictionaries.
        
        Args:
            query: SQLAlchemy query object
            connection: Optional existing connection to use
        
        Returns:
            List of dictionaries representing rows
        """
        if connection:
            # Use provided connection
            result = connection.execute(query)
            return [dict(row._mapping) for row in result]
        else:
            # Create connection and fetch all data before closing
            with self.get_connection() as conn:
                result = conn.execute(query)
                # Fetch all rows while connection is still open
                return [dict(row._mapping) for row in result.fetchall()]
    
    def fetch_one(self, query, connection: Optional[Connection] = None) -> Optional[Dict[str, Any]]:
        """
        Execute a query and fetch one result as a dictionary.
        
        Args:
            query: SQLAlchemy query object
            connection: Optional existing connection to use
        
        Returns:
            Dictionary representing the row, or None if not found
        """
        if connection:
            # Use provided connection
            result = connection.execute(query)
            row = result.fetchone()
            return dict(row._mapping) if row else None
        else:
            # Create connection and fetch data before closing
            with self.get_connection() as conn:
                result = conn.execute(query)
                row = result.fetchone()
                return dict(row._mapping) if row else None
    
    def count(self, table, where_clause=None, connection: Optional[Connection] = None) -> int:
        """
        Count rows in a table.
        
        Args:
            table: SQLAlchemy Table object
            where_clause: Optional WHERE clause
            connection: Optional existing connection to use
        
        Returns:
            Number of rows
        """
        query = select(func.count()).select_from(table)
        if where_clause is not None:
            query = query.where(where_clause)
        
        if connection:
            result = connection.execute(query)
            return result.scalar()
        else:
            with self.get_connection() as conn:
                result = conn.execute(query)
                return result.scalar()
    
    def exists(self, table, where_clause, connection: Optional[Connection] = None) -> bool:
        """
        Check if a row exists.
        
        Args:
            table: SQLAlchemy Table object
            where_clause: WHERE clause
            connection: Optional existing connection to use
        
        Returns:
            True if row exists, False otherwise
        """
        return self.count(table, where_clause, connection) > 0
    
    def insert_record(self, table, values: Dict[str, Any], 
                     connection: Optional[Connection] = None):
        """
        Insert a single record.
        
        Args:
            table: SQLAlchemy Table object
            values: Dictionary of column values
            connection: Optional existing connection to use
        """
        query = insert(table).values(**values)
        
        if connection:
            connection.execute(query)
        else:
            with self.transaction() as conn:
                conn.execute(query)
    
    def bulk_insert(self, table, records: List[Dict[str, Any]],
                   connection: Optional[Connection] = None):
        """
        Insert multiple records.
        
        Args:
            table: SQLAlchemy Table object
            records: List of dictionaries with column values
            connection: Optional existing connection to use
        """
        if not records:
            return
        
        query = insert(table)
        
        if connection:
            connection.execute(query, records)
        else:
            with self.transaction() as conn:
                conn.execute(query, records)
    
    def update_record(self, table, values: Dict[str, Any], where_clause,
                     connection: Optional[Connection] = None):
        """
        Update records.
        
        Args:
            table: SQLAlchemy Table object
            values: Dictionary of column values to update
            where_clause: WHERE clause
            connection: Optional existing connection to use
        """
        query = update(table).where(where_clause).values(**values)
        
        if connection:
            connection.execute(query)
        else:
            with self.transaction() as conn:
                conn.execute(query)
    
    def delete_record(self, table, where_clause,
                     connection: Optional[Connection] = None):
        """
        Delete records.
        
        Args:
            table: SQLAlchemy Table object
            where_clause: WHERE clause
            connection: Optional existing connection to use
        """
        query = delete(table).where(where_clause)
        
        if connection:
            connection.execute(query)
        else:
            with self.transaction() as conn:
                conn.execute(query)
    
    def select_all(self, table, where_clause=None, order_by=None,
                  connection: Optional[Connection] = None) -> List[Dict[str, Any]]:
        """
        Select all records from a table.
        
        Args:
            table: SQLAlchemy Table object
            where_clause: Optional WHERE clause
            order_by: Optional ORDER BY clause
            connection: Optional existing connection to use
        
        Returns:
            List of dictionaries representing rows
        """
        query = select(table)
        
        if where_clause is not None:
            query = query.where(where_clause)
        
        if order_by is not None:
            query = query.order_by(order_by)
        
        return self.fetch_all(query, connection)
    
    def select_one(self, table, where_clause,
                  connection: Optional[Connection] = None) -> Optional[Dict[str, Any]]:
        """
        Select one record from a table.
        
        Args:
            table: SQLAlchemy Table object
            where_clause: WHERE clause
            connection: Optional existing connection to use
        
        Returns:
            Dictionary representing the row, or None if not found
        """
        query = select(table).where(where_clause)
        return self.fetch_one(query, connection)

# Made with Bob
