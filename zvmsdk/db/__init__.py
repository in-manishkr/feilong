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
Database abstraction layer for zvmsdk.

This package provides a database abstraction layer that supports multiple
database backends (SQLite, MySQL, MariaDB, PostgreSQL) while maintaining
backward compatibility with the existing SQLite-based implementation.
"""

from zvmsdk.db.engine import get_engine, get_session
from zvmsdk.db.models import metadata

__all__ = ['get_engine', 'get_session', 'metadata']

# Made with Bob
