#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

# Copyright 2017, 2024 IBM Corp.
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

"""Regression tests for database.py connection manager exception handling.

Each connection manager must:
  1. Re-raise SDKBaseException subclasses unchanged.
  2. Wrap all other exceptions in the appropriate SDK exception type.
"""

import contextlib
import unittest
from unittest.mock import patch, MagicMock

from zvmsdk import database
from zvmsdk import exception
from zvmsdk.tests.unit import base


def _make_failing_get_connection(exc):
    """Return a patched get_connection context manager that raises *exc*."""
    @contextlib.contextmanager
    def _cm():
        raise exc
        yield  # noqa: unreachable — needed to make this a generator
    return _cm


class TestGetNetworkConnExceptionHandling(base.SDKTestCase):

    def test_reraises_sdk_base_exception(self):
        sdk_err = exception.SDKInternalError(msg='internal')
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(sdk_err)):
            with self.assertRaises(exception.SDKInternalError) as ctx:
                with database.get_network_conn():
                    pass
            self.assertIs(ctx.exception, sdk_err)

    def test_wraps_generic_exception_as_sdk_network_operation_error(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(RuntimeError('db gone'))):
            with self.assertRaises(exception.SDKNetworkOperationError):
                with database.get_network_conn():
                    pass

    def test_error_message_contains_original_text(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(OSError('disk full'))):
            with self.assertRaises(exception.SDKNetworkOperationError) as ctx:
                with database.get_network_conn():
                    pass
            self.assertIn('disk full', str(ctx.exception))


class TestGetImageConnExceptionHandling(base.SDKTestCase):

    def test_reraises_sdk_base_exception(self):
        sdk_err = exception.SDKInternalError(msg='internal')
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(sdk_err)):
            with self.assertRaises(exception.SDKInternalError) as ctx:
                with database.get_image_conn():
                    pass
            self.assertIs(ctx.exception, sdk_err)

    def test_wraps_generic_exception_as_sdk_database_exception(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(RuntimeError('db gone'))):
            with self.assertRaises(exception.SDKDatabaseException):
                with database.get_image_conn():
                    pass

    def test_error_message_contains_original_text(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(IOError('no space'))):
            with self.assertRaises(exception.SDKDatabaseException) as ctx:
                with database.get_image_conn():
                    pass
            self.assertIn('no space', str(ctx.exception))


class TestGetGuestConnExceptionHandling(base.SDKTestCase):

    def test_reraises_sdk_base_exception(self):
        sdk_err = exception.SDKInternalError(msg='internal')
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(sdk_err)):
            with self.assertRaises(exception.SDKInternalError) as ctx:
                with database.get_guest_conn():
                    pass
            self.assertIs(ctx.exception, sdk_err)

    def test_wraps_generic_exception_as_sdk_guest_operation_error(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(RuntimeError('db gone'))):
            with self.assertRaises(exception.SDKGuestOperationError):
                with database.get_guest_conn():
                    pass

    def test_error_message_contains_original_text(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(ValueError('bad value'))):
            with self.assertRaises(exception.SDKGuestOperationError) as ctx:
                with database.get_guest_conn():
                    pass
            self.assertIn('bad value', str(ctx.exception))


class TestGetFcpConnExceptionHandling(base.SDKTestCase):

    def test_reraises_sdk_base_exception(self):
        sdk_err = exception.SDKInternalError(msg='internal')
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(sdk_err)):
            with self.assertRaises(exception.SDKInternalError) as ctx:
                with database.get_fcp_conn():
                    pass
            self.assertIs(ctx.exception, sdk_err)

    def test_wraps_generic_exception_as_sdk_guest_operation_error(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(RuntimeError('db gone'))):
            with self.assertRaises(exception.SDKGuestOperationError):
                with database.get_fcp_conn():
                    pass

    def test_error_message_contains_original_text(self):
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(Exception('connection reset'))):
            with self.assertRaises(exception.SDKGuestOperationError) as ctx:
                with database.get_fcp_conn():
                    pass
            self.assertIn('connection reset', str(ctx.exception))

    def test_reraises_sdk_guest_operation_error_unchanged(self):
        # SDKGuestOperationError IS an SDKBaseException — must not be double-wrapped
        sdk_err = exception.SDKGuestOperationError(rs=1, msg='original')
        with patch('zvmsdk.database.get_connection',
                   _make_failing_get_connection(sdk_err)):
            with self.assertRaises(exception.SDKGuestOperationError) as ctx:
                with database.get_fcp_conn():
                    pass
            self.assertIs(ctx.exception, sdk_err)


if __name__ == '__main__':
    unittest.main()
