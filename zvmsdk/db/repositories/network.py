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
Network repository for database operations.

This module provides the NetworkRepository class that implements network-related
database operations, maintaining backward compatibility with NetworkDbOperator.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy import and_

from zvmsdk import log
from zvmsdk import exception
from zvmsdk.db.repositories.base import BaseRepository
from zvmsdk.db.models import switch_table

LOG = log.LOG


class NetworkRepository(BaseRepository):
    """
    Repository for network database operations.
    
    This class maintains backward compatibility with the NetworkDbOperator
    class while using the new database abstraction layer.
    """
    
    def __init__(self):
        """Initialize the network repository."""
        super().__init__(db_type='network', module_id='network')
    
    def switch_add_record(self, userid: str, interface: str, 
                         port: Optional[str] = None,
                         switch: Optional[str] = None, 
                         comments: Optional[str] = None):
        """
        Add userid and nic name address into switch table.
        
        Args:
            userid: z/VM user ID
            interface: Network interface device number
            port: Network port identifier (optional)
            switch: Virtual switch name (optional)
            comments: Additional comments (optional)
        """
        values = {
            'userid': userid,
            'interface': interface,
            'switch': switch,
            'port': port,
            'comments': comments
        }
        
        self.insert_record(switch_table, values)
        LOG.debug(f"New record in switch table: user {userid}, "
                 f"nic {interface}, port {port}")
    
    def switch_add_record_migrated(self, userid: str, interface: str, 
                                   switch: str,
                                   port: Optional[str] = None, 
                                   comments: Optional[str] = None):
        """
        Add userid, interfaces and switch into switch table.
        
        Args:
            userid: z/VM user ID
            interface: Network interface device number
            switch: Virtual switch name
            port: Network port identifier (optional)
            comments: Additional comments (optional)
        """
        values = {
            'userid': userid,
            'interface': interface,
            'switch': switch,
            'port': port,
            'comments': comments
        }
        
        self.insert_record(switch_table, values)
        LOG.debug(f"New record in switch table: user {userid}, "
                 f"nic {interface}, switch {switch}")
    
    def switch_delete_record_for_userid(self, userid: str):
        """
        Remove userid switch record from switch table.
        
        Args:
            userid: z/VM user ID
        """
        where_clause = switch_table.c.userid == userid
        self.delete_record(switch_table, where_clause)
        LOG.debug(f"Switch record for user {userid} removed from switch table")
    
    def switch_delete_record_for_nic(self, userid: str, interface: str):
        """
        Remove userid switch record for specific NIC from switch table.
        
        Args:
            userid: z/VM user ID
            interface: Network interface device number
        """
        where_clause = and_(
            switch_table.c.userid == userid,
            switch_table.c.interface == interface
        )
        self.delete_record(switch_table, where_clause)
        LOG.debug(f"Switch record for user {userid} with nic {interface} "
                 f"removed from switch table")
    
    def switch_update_record_with_switch(self, userid: str, interface: str,
                                        switch: Optional[str] = None):
        """
        Update switch information in switch table.
        
        Args:
            userid: z/VM user ID
            interface: Network interface device number
            switch: Virtual switch name (None to clear)
        
        Raises:
            SDKObjectNotExistError: If the record doesn't exist
        """
        # Check if record exists
        where_clause = and_(
            switch_table.c.userid == userid,
            switch_table.c.interface == interface
        )
        
        if not self.exists(switch_table, where_clause):
            msg = f"User {userid} with nic {interface} does not exist in DB"
            LOG.error(msg)
            obj_desc = f'User {userid} with nic {interface}'
            raise exception.SDKObjectNotExistError(obj_desc,
                                                   modID=self._module_id)
        
        # Update the record
        values = {'switch': switch}
        self.update_record(switch_table, values, where_clause)
        
        switch_val = switch if switch is not None else "None"
        LOG.debug(f"Set switch to {switch_val} for user {userid} "
                 f"with nic {interface} in switch table")
    
    def switch_select_table(self) -> List[Dict[str, Any]]:
        """
        Select all records from switch table.
        
        Returns:
            List of dictionaries representing switch records
        """
        return self.select_all(switch_table)
    
    def switch_select_record_for_userid(self, userid: str) -> List[Dict[str, Any]]:
        """
        Select switch records for a specific userid.
        
        Args:
            userid: z/VM user ID
        
        Returns:
            List of dictionaries representing switch records
        """
        where_clause = switch_table.c.userid == userid
        return self.select_all(switch_table, where_clause)
    
    def switch_select_record(self, userid: Optional[str] = None,
                            nic_id: Optional[str] = None,
                            vswitch: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Select switch records based on criteria.
        
        Args:
            userid: z/VM user ID (optional)
            nic_id: Network port identifier (optional)
            vswitch: Virtual switch name (optional)
        
        Returns:
            List of dictionaries representing switch records
        """
        # If no criteria provided, return all records
        if userid is None and nic_id is None and vswitch is None:
            return self.switch_select_table()
        
        # Build WHERE clause
        conditions = []
        if userid is not None:
            conditions.append(switch_table.c.userid == userid)
        if nic_id is not None:
            conditions.append(switch_table.c.port == nic_id)
        if vswitch is not None:
            conditions.append(switch_table.c.switch == vswitch)
        
        where_clause = and_(*conditions) if len(conditions) > 1 else conditions[0]
        return self.select_all(switch_table, where_clause)
    
    def _get_switch_by_user_interface(self, userid: str, 
                                      interface: str) -> Optional[Dict[str, Any]]:
        """
        Get switch record by userid and interface.
        
        Args:
            userid: z/VM user ID
            interface: Network interface device number
        
        Returns:
            Dictionary representing the switch record, or None if not found
        """
        where_clause = and_(
            switch_table.c.userid == userid,
            switch_table.c.interface == interface
        )
        return self.select_one(switch_table, where_clause)


# Backward compatibility alias
NetworkDbOperator = NetworkRepository

# Made with Bob
