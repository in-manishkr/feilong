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
Database repository layer for zvmsdk.

This package provides repository classes that implement database operations
using SQLAlchemy Core. These repositories maintain backward compatibility
with the existing DbOperator classes while providing support for multiple
database backends.
"""

from zvmsdk.db.repositories.base import BaseRepository
from zvmsdk.db.repositories.network import NetworkRepository
from zvmsdk.db.repositories.image import ImageRepository
from zvmsdk.db.repositories.guest import GuestRepository
from zvmsdk.db.repositories.fcp import FCPRepository

__all__ = [
    'BaseRepository',
    'NetworkRepository',
    'ImageRepository',
    'GuestRepository',
    'FCPRepository',
]

# Made with Bob
