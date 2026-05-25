#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""
Guest repository for database operations.

This module provides the GuestRepository class that implements guest-related
database operations, maintaining backward compatibility with GuestDbOperator.
"""

from typing import List, Dict, Any, Optional

from zvmsdk import log
from zvmsdk import exception
from zvmsdk.db.repositories.base import BaseRepository
from zvmsdk.db.models import guests_table

LOG = log.LOG


class GuestRepository(BaseRepository):
    """
    Repository for guest database operations.
    
    This class maintains backward compatibility with the GuestDbOperator
    class while using the new database abstraction layer.
    
    TODO: Implement all methods from GuestDbOperator class:
    - add_guest()
    - add_guest_registered()
    - delete_guest_by_id()
    - delete_guest_by_userid()
    - get_guest_by_id()
    - get_guest_by_userid()
    - get_guest_list()
    - get_metadata_by_userid()
    - update_guest_by_id()
    - update_guest_by_userid()
    """
    
    def __init__(self):
        """Initialize the guest repository."""
        super().__init__(db_type='guest', module_id='guest')
    
    # TODO: Implement guest operations following the pattern in NetworkRepository


# Backward compatibility alias
GuestDbOperator = GuestRepository

# Made with Bob
