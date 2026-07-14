#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0
#
#    Copyright 2017, 2023 IBM Corp.
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


import contextlib
import random
import os
import uuid
import json
import itertools

from sqlalchemy import text, bindparam

from zvmsdk import config
from zvmsdk import exception
from zvmsdk import log
from zvmsdk import utils
from zvmsdk.db import api as db_api
from zvmsdk.db.api import get_connection


CONF = config.CONF
LOG = log.LOG



class _CompatRow:
    """SQLAlchemy Row adapter that supports both positional (row[0]) and
    string-key (row['col']) access, mirroring the sqlite3.Row behavior the
    original code relied on."""
    __slots__ = ('_row', '_mapping')

    def __init__(self, row):
        self._row = row
        self._mapping = row._mapping

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._row)

    def __len__(self):
        return len(self._row)

    def __eq__(self, other):
        if isinstance(other, (tuple, list)):
            return tuple(self._row) == tuple(other)
        if isinstance(other, _CompatRow):
            return tuple(self._row) == tuple(other._row)
        return NotImplemented

    def __hash__(self):
        return hash(tuple(self._row))

    def keys(self):
        return self._mapping.keys()


def _fetchall(result):
    """Wrap CursorResult.fetchall() returning _CompatRow objects."""
    return [_CompatRow(r) for r in result.fetchall()]


def _fetchone(result):
    """Wrap CursorResult.fetchone() returning a _CompatRow or None."""
    row = result.fetchone()
    return _CompatRow(row) if row is not None else None


def _node_filter(prefix=None):
    """Return (sql_fragment, params) to scope a SELECT to the local node.

    In local mode returns ("", {}) so callers can concatenate unconditionally.
    In remote mode returns (" AND <col> = :node_id", {'node_id': ...}).
    For queries without an existing WHERE clause, callers should replace
    the leading " AND" with " WHERE", e.g.:
        filter_sql, filter_params = _node_filter()
        where = filter_sql.replace(" AND", " WHERE", 1)
    """
    if getattr(CONF.database, 'mode', 'local') == 'remote':
        col = ('%s.compute_node_id' % prefix) if prefix else 'compute_node_id'
        return " AND %s = :node_id" % col, {'node_id': db_api.get_compute_node_id()}
    return "", {}


@contextlib.contextmanager
def get_network_conn():
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        raise exception.SDKNetworkOperationError(rs=1, msg=msg)


@contextlib.contextmanager
def get_image_conn():
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        raise exception.SDKDatabaseException(msg=msg)


@contextlib.contextmanager
def get_guest_conn():
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        raise exception.SDKGuestOperationError(rs=1, msg=msg)


@contextlib.contextmanager
def get_fcp_conn():
    try:
        with get_connection() as conn:
            yield conn
    except exception.SDKBaseException:
        raise
    except Exception as err:
        msg = "Execute SQL statements error: %s" % str(err)
        LOG.error(msg)
        raise exception.SDKGuestOperationError(rs=1, msg=msg)


class NetworkDbOperator(object):

    def __init__(self):
        self._module_id = 'network'

    def _get_switch_by_user_interface(self, userid, interface):
        with get_network_conn() as conn:
            res = conn.execute(
                text("SELECT userid, interface, switch, port, comments FROM switch "
                     "WHERE userid=:userid and interface=:interface"),
                {'userid': userid, 'interface': interface})
            switch_record = _fetchall(res)

        if len(switch_record) == 1:
            return switch_record[0]
        elif len(switch_record) == 0:
            return None

    def switch_delete_record_for_userid(self, userid):
        """Remove userid switch record from switch table."""
        with get_network_conn() as conn:
            conn.execute(text("DELETE FROM switch WHERE userid=:userid"),
                         {'userid': userid})
            LOG.debug("Switch record for user %s is removed from "
                      "switch table" % userid)

    def switch_delete_record_for_nic(self, userid, interface):
        """Remove userid switch record from switch table."""
        with get_network_conn() as conn:
            conn.execute(
                text("DELETE FROM switch WHERE userid=:userid and interface=:interface"),
                {'userid': userid, 'interface': interface})
            LOG.debug("Switch record for user %s with nic %s is removed from "
                      "switch table" % (userid, interface))

    def switch_add_record(self, userid, interface, port=None,
                          switch=None, comments=None):
        """Add userid and nic name address into switch table."""
        with get_network_conn() as conn:
            conn.execute(
                text("INSERT INTO switch"
                     " (userid, interface, compute_node_id, switch, port, comments)"
                     " VALUES (:userid, :interface, :node_id, :switch, :port, :comments)"),
                {'userid': userid, 'interface': interface,
                 'node_id': db_api.get_compute_node_id(),
                 'switch': switch, 'port': port, 'comments': comments})
            LOG.debug("New record in the switch table: user %s, "
                      "nic %s, port %s" %
                      (userid, interface, port))

    def switch_add_record_migrated(self, userid, interface, switch,
                             port=None, comments=None):
        """Add userid and interfaces and switch into switch table."""
        with get_network_conn() as conn:
            conn.execute(
                text("INSERT INTO switch"
                     " (userid, interface, compute_node_id, switch, port, comments)"
                     " VALUES (:userid, :interface, :node_id, :switch, :port, :comments)"),
                {'userid': userid, 'interface': interface,
                 'node_id': db_api.get_compute_node_id(),
                 'switch': switch, 'port': port, 'comments': comments})
            LOG.debug("New record in the switch table: user %s, "
                      "nic %s, switch %s" %
                      (userid, interface, switch))

    def switch_update_record_with_switch(self, userid, interface,
                                         switch=None):
        """Update information in switch table."""
        if not self._get_switch_by_user_interface(userid, interface):
            msg = "User %s with nic %s does not exist in DB" % (userid,
                                                                interface)
            LOG.error(msg)
            obj_desc = ('User %s with nic %s' % (userid, interface))
            raise exception.SDKObjectNotExistError(obj_desc,
                                                   modID=self._module_id)

        if switch is not None:
            with get_network_conn() as conn:
                conn.execute(
                    text("UPDATE switch SET switch=:switch "
                         "WHERE userid=:userid and interface=:interface"),
                    {'switch': switch, 'userid': userid, 'interface': interface})
                LOG.debug("Set switch to %s for user %s with nic %s "
                          "in switch table" %
                          (switch, userid, interface))
        else:
            with get_network_conn() as conn:
                conn.execute(
                    text("UPDATE switch SET switch=NULL "
                         "WHERE userid=:userid and interface=:interface"),
                    {'userid': userid, 'interface': interface})
                LOG.debug("Set switch to None for user %s with nic %s "
                          "in switch table" %
                          (userid, interface))

    def _parse_switch_record(self, switch_list):
        return [dict(item._mapping) for item in switch_list]

    def switch_select_table(self):
        filter_sql, filter_params = _node_filter()
        where = filter_sql.replace(" AND", " WHERE", 1)
        with get_network_conn() as conn:
            result = conn.execute(text(
                "SELECT userid, interface, switch, port, comments FROM switch" + where),
                filter_params)
            nic_settings = _fetchall(result)
        return self._parse_switch_record(nic_settings)

    def switch_select_record_for_userid(self, userid):
        filter_sql, filter_params = _node_filter()
        params = {'userid': userid, **filter_params}
        with get_network_conn() as conn:
            result = conn.execute(
                text("SELECT userid, interface, switch, port, comments FROM switch"
                     " WHERE userid=:userid" + filter_sql),
                params)
            switch_info = _fetchall(result)
        return self._parse_switch_record(switch_info)

    def switch_select_record(self, userid=None, nic_id=None, vswitch=None):
        if ((userid is None) and
            (nic_id is None) and
            (vswitch is None)):
            return self.switch_select_table()

        filter_sql, filter_params = _node_filter()
        clauses = []
        params = {}
        if userid is not None:
            clauses.append("userid=:userid")
            params['userid'] = userid
        if nic_id is not None:
            clauses.append("port=:port")
            params['port'] = nic_id
        if vswitch is not None:
            clauses.append("switch=:switch")
            params['switch'] = vswitch
        params.update(filter_params)

        sql_cmd = ("SELECT userid, interface, switch, port, comments FROM switch WHERE "
                   + " AND ".join(clauses) + filter_sql)

        with get_network_conn() as conn:
            result = conn.execute(text(sql_cmd), params)
            switch_list = _fetchall(result)

        return self._parse_switch_record(switch_list)


class FCPDbOperator(object):

    def __init__(self):
        self._module_id = 'volume'

    #########################################################
    #                DML for Table fcp                      #
    #########################################################
    def unreserve_fcps(self, fcp_ids):
        if not fcp_ids:
            return
        records = [{'fcp_id': fcp_id} for fcp_id in fcp_ids]
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET reserved=0, tmpl_id='' WHERE fcp_id=:fcp_id"),
                records)

    def reserve_fcps(self, fcp_ids, assigner_id, fcp_template_id):
        records = [{'assigner_id': assigner_id, 'tmpl_id': fcp_template_id,
                    'fcp_id': fcp_id}
                   for fcp_id in fcp_ids]
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET reserved=1, assigner_id=:assigner_id, "
                     "tmpl_id=:tmpl_id WHERE fcp_id=:fcp_id"),
                records)

    def bulk_insert_zvm_fcp_info_into_fcp_table(self, fcp_info_list: list):
        """Insert multiple records into fcp table witch fcp info queried
        from z/VM.

        The input fcp_info_list should be list of FCP info, for example:
        [(fcp_id, wwpn_npiv, wwpn_phy, chpid, pchid, state, owner),
         ('1a06', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'active',
          'user1'),
         ('1a07', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'free',
          'user1'),
         ('1a08', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'active',
          'user2')]
        """
        node_id = db_api.get_compute_node_id()
        records = [{'fcp_id': r[0], 'node_id': node_id,
                    'wwpn_npiv': r[1], 'wwpn_phy': r[2],
                    'chpid': r[3], 'pchid': r[4], 'state': r[5], 'owner': r[6]}
                   for r in fcp_info_list]
        if not records:
            return
        with get_fcp_conn() as conn:
            conn.execute(
                text("INSERT INTO fcp"
                     " (fcp_id, compute_node_id, wwpn_npiv, wwpn_phy,"
                     "  chpid, pchid, state, owner)"
                     " VALUES (:fcp_id, :node_id, :wwpn_npiv, :wwpn_phy,"
                     "  :chpid, :pchid, :state, :owner)"),
                records)

    def bulk_delete_from_fcp_table(self, fcp_id_list: list):
        """Delete multiple FCP records from fcp table
        The fcp_id_list is list of FCP IDs, for example:
        ['1a00', '1b01', '1c02']
        """
        if not fcp_id_list:
            return
        records = [{'fcp_id': fcp_id} for fcp_id in fcp_id_list]
        with get_fcp_conn() as conn:
            conn.execute(text("DELETE FROM fcp WHERE fcp_id=:fcp_id"), records)

    def bulk_update_zvm_fcp_info_in_fcp_table(self, fcp_info_list: list):
        """Update multiple records with FCP info queried from z/VM.

        The input fcp_info_list should be list of FCP info set, for example:
        [(fcp_id, wwpn_npiv, wwpn_phy, chpid, pchid, state, owner),
         ('1a06', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'active',
          'user1'),
         ('1a07', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'free',
          'user1'),
         ('1a08', 'c05076de33000355', 'c05076de33002641', '27', '02e4', 'active',
          'user2')]
        """
        records = [{'wwpn_npiv': r[1], 'wwpn_phy': r[2], 'chpid': r[3],
                    'pchid': r[4], 'state': r[5], 'owner': r[6], 'fcp_id': r[0]}
                   for r in fcp_info_list]
        if not records:
            return
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET wwpn_npiv=:wwpn_npiv, wwpn_phy=:wwpn_phy, "
                     "chpid=:chpid, pchid=:pchid, state=:state, owner=:owner "
                     "WHERE fcp_id=:fcp_id"),
                records)

    def bulk_update_state_in_fcp_table(self, fcp_id_list: list,
                                       new_state: str):
        """Update multiple records' comments to update the state to nofound.
        """
        if not fcp_id_list:
            return
        records = [{'state': new_state, 'fcp_id': fcp_id}
                   for fcp_id in fcp_id_list]
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET state=:state WHERE fcp_id=:fcp_id"),
                records)

    def reset_fcps_of_assigner(self, userid):
        """Reset fcp records for a given assigner."""
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET assigner_id='', reserved=0, "
                     "connections=0, tmpl_id='' WHERE assigner_id=:userid"),
                {'userid': userid})
            LOG.debug("FCP records for user %s are reset in "
                      "fcp table" % userid)

    def get_all_fcps_of_assigner(self, assigner_id=None):
        """Get dict of all fcp records of specified assigner.
        If assigner is None, will get all fcp records.
        Format of return is like :
        [
          (fcp_id, userid, connections, reserved, wwpn_npiv, wwpn_phy,
           chpid, pchid, state, owner, tmpl_id),
          ('283c', 'user1', 2, 1, 'c05076ddf7000002', 'c05076ddf7001d81',
           '27', '02e4', 'active', 'user1', ''),
          ('483c', 'user2', 0, 0, 'c05076ddf7000001', 'c05076ddf7001d82',
           '27', '02e4', 'free', 'NONE', '')
        ]
        """
        filter_sql, filter_params = _node_filter()
        _cols = ("SELECT fcp_id, assigner_id, connections, reserved, "
                 "wwpn_npiv, wwpn_phy, chpid, pchid, state, owner, tmpl_id FROM fcp")
        with get_fcp_conn() as conn:
            if assigner_id:
                params = {'assigner_id': assigner_id, **filter_params}
                result = conn.execute(
                    text(_cols + " WHERE assigner_id=:assigner_id" + filter_sql),
                    params)
            else:
                where = filter_sql.replace(" AND", " WHERE", 1)
                result = conn.execute(text(_cols + where), filter_params)
            fcp_info = _fetchall(result)
            if not fcp_info:
                if assigner_id:
                    obj_desc = ("FCP record in fcp table belongs to "
                                "userid: %s" % assigner_id)
                else:
                    obj_desc = "FCP records in fcp table"
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
        return fcp_info

    def get_usage_of_fcp(self, fcp_id):
        connections = 0
        reserved = 0
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT assigner_id, reserved, connections, tmpl_id "
                     "FROM fcp WHERE fcp_id=:fcp_id" + filter_sql),
                {'fcp_id': fcp_id, **filter_params})
            fcp_info = _fetchone(result)
            if not fcp_info:
                msg = 'FCP with id: %s does not exist in DB.' % fcp_id
                LOG.error(msg)
                obj_desc = "FCP with id: %s" % fcp_id
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
            assigner_id = fcp_info['assigner_id']
            reserved = fcp_info['reserved']
            connections = fcp_info['connections']
            tmpl_id = fcp_info['tmpl_id']

        return assigner_id, reserved, connections, tmpl_id

    def update_usage_of_fcp(self, fcp, assigner_id, reserved, connections,
                            fcp_template_id):
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE fcp SET assigner_id=:assigner_id, reserved=:reserved, "
                     "connections=:connections, tmpl_id=:tmpl_id WHERE fcp_id=:fcp_id"),
                {'assigner_id': assigner_id, 'reserved': reserved,
                 'connections': connections, 'tmpl_id': fcp_template_id,
                 'fcp_id': fcp})

    def increase_connections_by_assigner(self, fcp, assigner_id):
        """Increase connections of the given FCP device

        :param fcp: (str) a FCP device
        :param assigner_id: (str) the userid of the virtual machine
        :return connections: (dict) the connections of the FCP device
        """
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT connections FROM fcp "
                     "WHERE fcp_id=:fcp_id AND assigner_id=:assigner_id"),
                {'fcp_id': fcp, 'assigner_id': assigner_id})
            fcp_info = _fetchone(result)
            if not fcp_info:
                msg = 'FCP with id: %s does not exist in DB.' % fcp
                LOG.error(msg)
                obj_desc = "FCP with id: %s" % fcp
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
            connections = fcp_info['connections'] + 1

            conn.execute(
                text("UPDATE fcp SET connections=:connections "
                     "WHERE fcp_id=:fcp_id AND assigner_id=:assigner_id"),
                {'connections': connections, 'fcp_id': fcp,
                 'assigner_id': assigner_id})
            # check the result
            result = conn.execute(
                text("SELECT connections FROM fcp WHERE fcp_id=:fcp_id"),
                {'fcp_id': fcp})
            connections = _fetchone(result)['connections']
            return connections

    def decrease_connections(self, fcp):
        """Decrease connections of the given FCP device

        :param fcp: (str) a FCP device
        :return connections: (dict) the connections of the FCP device
        """
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT connections FROM fcp WHERE fcp_id=:fcp_id"),
                {'fcp_id': fcp})
            fcp_list = _fetchone(result)
            if not fcp_list:
                msg = 'FCP with id: %s does not exist in DB.' % fcp
                LOG.error(msg)
                obj_desc = "FCP with id: %s" % fcp
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
            connections = fcp_list['connections']
            if connections == 0:
                msg = 'FCP with id: %s no connections in DB.' % fcp
                LOG.error(msg)
                obj_desc = "FCP with id: %s" % fcp
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
            else:
                connections -= 1
            if connections < 0:
                connections = 0
                LOG.warning("Warning: connections of fcp is negative",
                            fcp)
            # decrease connections by 1
            conn.execute(
                text("UPDATE fcp SET connections=:connections WHERE fcp_id=:fcp_id"),
                {'connections': connections, 'fcp_id': fcp})
            # check the result
            result = conn.execute(
                text("SELECT connections FROM fcp WHERE fcp_id=:fcp_id"),
                {'fcp_id': fcp})
            connections = _fetchone(result)['connections']
            return connections

    def get_connections_from_fcp(self, fcp):
        connections = 0
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT connections FROM fcp WHERE fcp_id=:fcp_id" + filter_sql),
                {'fcp_id': fcp, **filter_params})
            fcp_info = _fetchone(result)
            if not fcp_info:
                msg = 'FCP with id: %s does not exist in DB.' % fcp
                LOG.error(msg)
                obj_desc = "FCP with id: %s" % fcp
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
            connections = fcp_info['connections']

        return connections

    def get_all(self):
        filter_sql, filter_params = _node_filter()
        where = filter_sql.replace(" AND", " WHERE", 1)
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT fcp_id, assigner_id, connections, reserved, "
                     "wwpn_npiv, wwpn_phy, chpid, pchid, state, owner, "
                     "tmpl_id FROM fcp" + where),
                filter_params)
            fcp_list = _fetchall(result)

        return fcp_list

    @staticmethod
    def get_inuse_fcp_device_by_fcp_template(fcp_template_id):
        """ Get the FCP devices allocated from the template """
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            query_sql = conn.execute(
                text("SELECT fcp_id FROM fcp WHERE tmpl_id=:tmpl_id" + filter_sql),
                {'tmpl_id': fcp_template_id, **filter_params})
            result = _fetchall(query_sql)
        return result

    #########################################################
    #          DML for Table template_fcp_mapping           #
    #########################################################
    @staticmethod
    def update_path_of_fcp_device(record):
        """ update path of single fcp device
            from table template_fcp_mapping

            :param record (tuple)
                example:
                (path, fcp_id, fcp_template_id)

            :return NULL
        """
        path, fcp_id, tmpl_id = record
        with get_fcp_conn() as conn:
            conn.execute(
                text("UPDATE template_fcp_mapping SET path=:path "
                     "WHERE fcp_id=:fcp_id and tmpl_id=:tmpl_id"),
                {'path': path, 'fcp_id': fcp_id, 'tmpl_id': tmpl_id})

    def get_path_count(self, fcp_template_id):
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            # Get distinct path list in DB
            result = conn.execute(
                text("SELECT DISTINCT path FROM template_fcp_mapping "
                     "WHERE tmpl_id=:tmpl_id" + filter_sql),
                {'tmpl_id': fcp_template_id, **filter_params})
            path_list = _fetchall(result)

        return len(path_list)

    @staticmethod
    def bulk_delete_fcp_device_from_fcp_template(records):
        """ Delete multiple fcp device
            from table template_fcp_mapping

            :param records (iter)
                example:
                [(fcp_template_id, fcp_id), ...]

            :return NULL
        """
        dicts = [{'tmpl_id': r[0], 'fcp_id': r[1]} for r in records]
        if not dicts:
            return
        with get_fcp_conn() as conn:
            conn.execute(
                text("DELETE FROM template_fcp_mapping "
                     "WHERE tmpl_id=:tmpl_id AND fcp_id=:fcp_id"),
                dicts)

    @staticmethod
    def bulk_insert_fcp_device_into_fcp_template(records):
        """ Insert multiple fcp device
            from table template_fcp_mapping

            :param records (iter)
                example:
                [
                    (fcp_template_id, fcp_id, path),
                    ...
                ]

            :return NULL
        """
        node_id = db_api.get_compute_node_id()
        dicts = [{'fcp_id': r[1], 'tmpl_id': r[0], 'node_id': node_id, 'path': r[2]}
                 for r in records]
        if not dicts:
            return
        with get_fcp_conn() as conn:
            conn.execute(
                text("INSERT INTO template_fcp_mapping"
                     " (fcp_id, tmpl_id, compute_node_id, path)"
                     " VALUES (:fcp_id, :tmpl_id, :node_id, :path)"),
                dicts)

    #########################################################
    #               DML for Table template                  #
    #########################################################
    def fcp_template_exist_in_db(self, fcp_template_id: str):
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            query_sql = conn.execute(
                text("SELECT id FROM template WHERE id=:id" + filter_sql),
                {'id': fcp_template_id, **filter_params})
            query_ids = _fetchall(query_sql)
        if query_ids:
            return True
        else:
            return False

    def get_min_fcp_paths_count_from_db(self, fcp_template_id):
        filter_sql, filter_params = _node_filter()
        with get_fcp_conn() as conn:
            query_sql = conn.execute(
                text("SELECT min_fcp_paths_count FROM template WHERE id=:id" + filter_sql),
                {'id': fcp_template_id, **filter_params})
            min_fcp_paths_count = _fetchone(query_sql)
            if min_fcp_paths_count:
                return min_fcp_paths_count['min_fcp_paths_count']
            else:
                return None

    @staticmethod
    def update_basic_info_of_fcp_template(record):
        """ update basic info of a FCP Multipath Template
            in table template

            :param record (tuple)
                example:
                (name, description, host_default, min_fcp_paths_count, fcp_template_id)

            :return NULL
        """
        name, description, host_default, min_fcp_paths_count, fcp_template_id = record
        with get_fcp_conn() as conn:
            # 1. change the is_default of existing templates to False,
            #    if the is_default of the being-created template is True,
            #    because only one default template per host is allowed
            if host_default is True:
                conn.execute(text("UPDATE template SET is_default=:val"),
                             {'val': False})
            # 2. update current template
            conn.execute(
                text("UPDATE template SET name=:name, description=:desc, "
                     "is_default=:is_default, min_fcp_paths_count=:min_count "
                     "WHERE id=:id"),
                {'name': name, 'desc': description, 'is_default': host_default,
                 'min_count': min_fcp_paths_count, 'id': fcp_template_id})

    #########################################################
    #          DML for Table template_sp_mapping            #
    #########################################################
    def sp_name_exist_in_db(self, sp_name: str):
        with get_fcp_conn() as conn:
            query_sp = conn.execute(
                text("SELECT sp_name FROM template_sp_mapping "
                     "WHERE sp_name=:sp_name"),
                {'sp_name': sp_name})
            query_sp_names = _fetchall(query_sp)

        if query_sp_names:
            return True
        else:
            return False

    @staticmethod
    def bulk_set_sp_default_by_fcp_template(template_id,
                                            sp_name_list):
        """ Set a default FCP Multipath Template
            for multiple storage providers

            The function only manipulate table(template_fcp_mapping)

            :param template_id: the FCP Multipath Template ID
            :param sp_name_list: a list of storage provider hostname

            :return NULL
        """
        # Example:
        # if
        #  a.the existing-in-db storage providers for template_id:
        #      ['sp1', 'sp2']
        #  b.the sp_name_list is ['sp3', 'sp4']
        # then
        #  c.remove records of ['sp1', 'sp2'] from db
        #  d.remove records of ['sp3', 'sp4'] if any from db
        #  e.insert ['sp3', 'sp4'] with template_id as default
        with get_fcp_conn() as conn:
            # delete all records related to the template_id
            conn.execute(
                text("DELETE FROM template_sp_mapping WHERE tmpl_id=:tmpl_id"),
                {'tmpl_id': template_id})
            # delete all records related to the storage providers in sp_name_list
            conn.execute(
                text("DELETE FROM template_sp_mapping WHERE sp_name=:sp_name"),
                [{'sp_name': sp} for sp in sp_name_list])
            # insert new record for each storage provider in sp_name_list
            node_id = db_api.get_compute_node_id()
            conn.execute(
                text("INSERT INTO template_sp_mapping"
                     " (sp_name, tmpl_id, compute_node_id)"
                     " VALUES (:sp_name, :tmpl_id, :node_id)"),
                [{'sp_name': sp, 'tmpl_id': template_id, 'node_id': node_id}
                 for sp in sp_name_list])

    #########################################################
    #           DML related to multiple tables              #
    #########################################################
    def get_allocated_fcps_from_assigner(self,
                                         assigner_id, fcp_template_id):
        """ Get the previously allocated FCP devices of the instance
        by fcp.connections<>0 OR fcp.reserved<>0

        @param assigner_id: (str) instance userid in z/VM
        @param fcp_template_id: (str) FCP multipath template ID
        @return: a list of sqlite3.Row objects.
          sqlite3.Row can be accessed in dict-style.
          example:
          [{'fcp_id':'1B02', 'path':1, 'pchid':'A', 'wwpn_npiv':'aa', 'wwpn_phy':'xx'},
           {'fcp_id':'1C04', 'path':4, 'pchid':'B', 'wwpn_npiv':'bb', 'wwpn_phy':'yy'},
           {'fcp_id':'1E05', 'path':5, 'pchid':'E', 'wwpn_npiv':'cc', 'wwpn_phy':'zz'}]
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT fcp.fcp_id, fcp.wwpn_npiv, fcp.wwpn_phy, "
                     "tf.path, fcp.pchid "
                     "FROM template_fcp_mapping AS tf "
                     "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id "
                     "WHERE tf.tmpl_id=:tmpl_id "
                     "AND fcp.assigner_id=:assigner_id "
                     "AND (fcp.connections<>0 OR fcp.reserved<>0) "
                     "AND fcp.tmpl_id=:tmpl_id2"
                     + filter_sql +
                     " ORDER BY tf.fcp_id ASC"),
                {'tmpl_id': fcp_template_id, 'assigner_id': assigner_id,
                 'tmpl_id2': fcp_template_id, **filter_params})
            fcp_list = _fetchall(result)
        return fcp_list

    def get_reserved_fcps_from_assigner(self, assigner_id, fcp_template_id):
        """ Get the previously reserved FCP devices of the instance
        by fcp.reserved<>0

        @param assigner_id: (str) instance userid in z/VM
        @param fcp_template_id: (str) FCP multipath template ID
        @return: a list of sqlite3.Row objects.
          sqlite3.Row can be accessed in dict-style.
          example:
          [{'fcp_id':'1B02', 'path':1, 'pchid':'A', 'wwpn_npiv':'aa', 'wwpn_phy':'xx', 'connections':0},
           {'fcp_id':'1C04', 'path':4, 'pchid':'C', 'wwpn_npiv':'bb', 'wwpn_phy':'yy', 'connections':0},
           {'fcp_id':'1E05', 'path':5, 'pchid':'E', 'wwpn_npiv':'cc', 'wwpn_phy':'zz', 'connections':0}]
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT fcp.fcp_id, fcp.wwpn_npiv, fcp.wwpn_phy, "
                     "fcp.connections, tf.path, fcp.pchid "
                     "FROM template_fcp_mapping AS tf "
                     "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id "
                     "WHERE tf.tmpl_id=:tmpl_id "
                     "AND fcp.assigner_id=:assigner_id "
                     "AND fcp.reserved<>0 "
                     "AND fcp.tmpl_id=:tmpl_id2"
                     + filter_sql +
                     " ORDER BY tf.fcp_id ASC"),
                {'tmpl_id': fcp_template_id, 'assigner_id': assigner_id,
                 'tmpl_id2': fcp_template_id, **filter_params})
            fcp_list = _fetchall(result)

        return fcp_list

    def get_fcp_devices_with_same_index(self, fcp_template_id, pchid_info):
        """ Get a group of available FCPs with the same index,
        which also satisfy the following conditions:
            a. connections = 0
            b. reserved = 0
            c. state = 'free'
            d. wwpn_npiv IS NOT ''
            e. wwpn_phy IS NOT ''
            f. ignore min_fcp_paths_count

        @param fcp_template_id: (str) FCP multipath template ID
        @param pchid_info: (dict) PCHID as key,
            'allocated' means the count of allocated FCP devices from the PCHID
            'max' means the maximum allowable count of FCP devices that can be allocated from the PCHID
            example:
            {'AAAA': {'allocated': 128, 'max': 128},
             'BBBB': {'allocated': 109, 'max': 110},
             'CCCC': {'allocated': 111, 'max': 128},
             'DDDD': {'allocated': 113, 'max': 110},
             'EEEE': {'allocated': 70,  'max': 90}}
        @return: fcp_list, empty_fcp_list_reason
          empty_fcp_list_reason: (str) the reason of why fcp_list is empty
          fcp_list example:
          [{'fcp_id':'1B02', 'path':1, 'pchid':'BBBB', 'wwpn_npiv':'aa', 'wwpn_phy':'xx'},
           {'fcp_id':'1C04', 'path':4, 'pchid':'CCCC', 'wwpn_npiv':'bb', 'wwpn_phy':'yy'},
           {'fcp_id':'1E05', 'path':5, 'pchid':'EEEE', 'wwpn_npiv':'cc', 'wwpn_phy':'zz'}]
        case 1
            an empty list(i.e. [])
            if no fcp exist in DB
        case 2
           an empty list(i.e. [])
           if no expected pair found
        case 3
           randomly choose one of the following combinations:
                [1a00,1b00] ,[1a01,1b01] ,[1a02,1b02]...
           rather than below combinations:
               [1a00,1b02] ,[1a03,1b00]
               [1a02], [1b03]
        """
        fcp_list = []
        empty_fcp_list_reason = ''
        fcp_pair_map = {}
        filter_sql, filter_params = _node_filter(prefix='fcp')
        with get_fcp_conn() as conn:
            # count_per_path examples:
            # in normal cases, all path has same count, eg.
            #   4 paths: [7, 7, 7, 7]
            #   2 paths: [7, 7]
            # we can also handle rare abnormal cases,
            # where path count differs, eg.
            #   4 paths: [7, 4, 5, 6]
            #   2 paths: [7, 6]
            result = conn.execute(
                text("SELECT COUNT(path) AS cnt "
                     "FROM template_fcp_mapping "
                     "WHERE tmpl_id=:tmpl_id "
                     "GROUP BY path "
                     "ORDER BY path ASC"),
                {'tmpl_id': fcp_template_id})
            count_per_path = [a['cnt'] for a in _fetchall(result)]
            # case1: return [] if no fcp found in FCP DB
            if not count_per_path:
                LOG.error('Because the FCP template ({}) does not include any FCP device, '
                          'return empty list.'.format(fcp_template_id))
                empty_fcp_list_reason = (
                    'No FCP device exists in FCP multipath template (id={}). '
                    'To use this template, '
                    'you must add more free FCP devices by editing the template. '
                    'For load balance across multiple PCHIDs, '
                    'suggest adding the same amount of '
                    'FCP devices per PCHID.'.format(fcp_template_id))
                return [], empty_fcp_list_reason
            result = conn.execute(
                text("SELECT COUNT(template_fcp_mapping.path) AS cnt "
                     "FROM template_fcp_mapping "
                     "INNER JOIN fcp "
                     "ON template_fcp_mapping.fcp_id=fcp.fcp_id "
                     "WHERE template_fcp_mapping.tmpl_id=:tmpl_id "
                     "AND fcp.connections=0 "
                     "AND fcp.reserved=0 "
                     "AND fcp.state='free' "
                     "AND fcp.wwpn_npiv <> '' "
                     "AND fcp.wwpn_phy <> '' "
                     + filter_sql +
                     " GROUP BY template_fcp_mapping.path "
                     "ORDER BY template_fcp_mapping.path"),
                {'tmpl_id': fcp_template_id, **filter_params})
            free_count_per_path = [a['cnt'] for a in _fetchall(result)]
            # case2: return [] if no free fcp found from at least one path
            if len(free_count_per_path) < len(count_per_path):
                # For get_fcp_pair_with_same_index, we will not check the
                # CONF.volume.min_fcp_paths_count, the returned fcp count
                # should always equal to the total paths count
                LOG.error('Because free path count ({}) is less than '
                          'total path count ({}), return empty list.'
                          .format(len(free_count_per_path), len(count_per_path)))
                empty_fcp_list_reason = (
                    'As the option get_fcp_pair_with_same_index is enabled on this host, '
                    'when you choose an FCP multipath template of this host for '
                    'attaching volume or booting from volume, '
                    'all the paths of the template must have free FCP devices. '
                    'However, {} path(s) of template (id={}) does not have free FCP devices. '
                    'To use this template, you must add more free FCP devices '
                    'by editing the template to meet the requirement.'
                    .format(
                        len(count_per_path) - len(free_count_per_path),
                        fcp_template_id))
                return [], empty_fcp_list_reason
            # fcps 2 paths example:
            #    fcp  conn reserved state path pchid wwpn_npiv wwpn_phy
            #   ------------------
            # [('1a00', 1, 1, 'active', ...),
            #  ('1a01', 0, 0, 'free', ...),
            #  ('1a02', 0, 0, 'free', ...),
            #  ('1a03', 0, 0, 'free', ...),
            #  ('1a04', 0, 0, 'offline', ...),
            #  ...
            #  ('1b00', 1, 0, 'active', ...),
            #  ('1b01', 2, 1, 'active', ...),
            #  ('1b02', 0, 0, 'free', ...),
            #  ('1b03', 0, 0, 'free', ...),
            #  ('1b04', 0, 0, 'free', ...),
            #  ...]
            result = conn.execute(
                text("SELECT fcp.fcp_id, fcp.connections, tf.path, fcp.pchid, "
                     "fcp.reserved, fcp.state, fcp.wwpn_npiv, fcp.wwpn_phy "
                     "FROM fcp "
                     "INNER JOIN template_fcp_mapping AS tf "
                     "ON tf.fcp_id=fcp.fcp_id "
                     "WHERE tf.tmpl_id=:tmpl_id"
                     + filter_sql +
                     " ORDER BY tf.path, tf.fcp_id"),
                {'tmpl_id': fcp_template_id, **filter_params})
            fcps = _fetchall(result)
        # get all free fcps from 1st path
        # fcp_pair_map example:
        #  idx    fcp_pair
        #  ----------------
        # { 1 : [('1a01', 'c0507...', 'c0604...', 0, 'AAAA')],
        #   2 : [('1a02', ...)],
        #   3 : [('1a03', ...)]}
        #
        # The FCP count of 1st path
        for i in range(min(count_per_path)):
            row = fcps[i]
            fcp_no = row['fcp_id']
            connections = row['connections']
            path = row['path']
            pchid = row['pchid']
            reserved = row['reserved']
            state = row['state']
            wwpn_npiv = row['wwpn_npiv']
            wwpn_phy = row['wwpn_phy']
            if connections == reserved == 0 and state == 'free':
                fcp_pair_map[i] = [(fcp_no, wwpn_npiv, wwpn_phy, path, pchid)]
        # select out pairs if member count == path count
        # fcp_pair_map example:
        #  idx    fcp_pair
        #  ----------------------
        # { 2 : [('1a02', ...), ('1b02', ...)],
        #   3 : [('1a03', ...), ('1b03', ...)]}
        for idx in fcp_pair_map.copy():
            s = 0
            for i, c in enumerate(count_per_path[:-1]):
                s += c
                # avoid index out of range for per path in fcps[]
                row = fcps[s + idx]
                fcp_no = row['fcp_id']
                connections = row['connections']
                path = row['path']
                pchid = row['pchid']
                reserved = row['reserved']
                state = row['state']
                wwpn_npiv = row['wwpn_npiv']
                wwpn_phy = row['wwpn_phy']
                if (idx < count_per_path[i + 1] and
                        connections == reserved == 0 and
                        state == 'free'):
                    fcp_pair_map[idx].append(
                        (fcp_no, wwpn_npiv, wwpn_phy, path, pchid))
                else:
                    fcp_pair_map.pop(idx)
                    break
        # fcp_combinations ex:
        # [ [('1a02', ...), ('1b02', ...), ('1c02', ...)],
        #   [('1a03', ...), ('1b03', ...), ('1c03', ...)] ]
        fcp_combinations = list(fcp_pair_map.values())

        if not fcp_combinations:
            empty_fcp_list_reason = (
                'No FCP device combination of FCP multipath template (id={}) '
                'matches the same index policy. '
                'To use this template, '
                'you must add more free FCP devices '
                'by editing the template to meet the above requirement.'
                .format(fcp_template_id))
            LOG.error(empty_fcp_list_reason)
            return [], empty_fcp_list_reason

        def _remove_invalid_combinations(pchids_without_enough_free_cap):
            """remove the combinations whose weight is less than 1"""
            # free_count_in_pchid_info:
            # PCHID as key, free-FCP-device-count as value. Ex:
            # {'AAAA': 0, 'BBBB': 1, 'CCCC': 1, 'DDDD': -3, 'EEEE': 3}
            free_count_in_pchid_info = dict()
            for pchid in pchid_info:
                free_fcp_count = (pchid_info[pchid]['max'] -
                                  pchid_info[pchid]['allocated'])
                free_count_in_pchid_info[pchid.upper()] = free_fcp_count
            LOG.info('free_count_in_pchid_info: {}'.format(free_count_in_pchid_info))
            # comb ex:
            # [(fcp_no, wwpn_npiv, wwpn_phy, path, pchid)
            #  ('1a03', '.......', '......', 0,   'eeee'),
            #  ('1b03', '.......', '......', 1,   'cccc'),
            #  ('1c03', '.......', '......', 2,   'cccc')]
            for comb in fcp_combinations.copy():
                # pchids ex:
                # ['EEEE', 'CCCC', 'CCCC']
                pchids = [item[-1].upper() for item in comb]
                # comb_fcp_count_per_pchid:
                # PCHID as key, occurance-count-in-comb as value. Ex:
                # {'EEEE': 1, 'CCCC': 2}
                # In the example, for this comb
                # it means PCHID 'EEEE' occurs once, PCHID 'CCCC' occurs twice;
                # it indicates 1 FCP device is from 'EEEE' and 2 from 'CCCC'
                # will be consumed to satisfy one time of FCP device allocation.
                comb_fcp_count_per_pchid = {
                    pchid: pchids.count(pchid)
                    for pchid in set(pchids)}
                # weights ex:
                # {'EEEE': 3/1, 'CCCC': 1/2}
                weights = {p: free_count_in_pchid_info[p] / comb_fcp_count_per_pchid[p]
                           for p in comb_fcp_count_per_pchid}
                for pchid in weights:
                    # if a PCHID's weight < 1,
                    # indicating not enough free capacity for allocating FCP device
                    if weights[pchid] < 1:
                        pchids_without_enough_free_cap[pchid] = free_count_in_pchid_info[pchid]
                # weight:
                # In a way, the weight reflects the capability of how many times
                # of FCP device allocation can be done if choosing this comb.
                # take PCHIDs 'EEEE' and 'CCCC' as example:
                # min(3/1, 1/2) -> min(3, 0.5) -> 0.5
                weight = min(weights.values())
                # remove invalid comb
                if weight < 1:
                    fcp_combinations.remove(comb)
        # pchids_without_enough_free_cap ex:
        # {'CCCC': 1, 'EEEE': 0}
        pchids_without_enough_free_cap = dict()
        _remove_invalid_combinations(pchids_without_enough_free_cap)

        if not fcp_combinations:
            empty_fcp_list_reason = (
                'Not enough free capacity of the following PCHIDs left. '
                'Their free capacity is {}. '
                'To use this FCP multipath template (id={}), '
                'you must either increase free capacity of above PCHIDs '
                'or add more free FCP devices '
                'whose PCHIDs have enough free capacity by editing the template.'
                .format(sorted(pchids_without_enough_free_cap.items()),
                        fcp_template_id))
            LOG.error(empty_fcp_list_reason)
            return [], empty_fcp_list_reason
        else:
            # case3: return one group randomly chosen from fcp_combinations
            # fcp_list example:
            # [('1a03', ...), ('1b03', ...), ('1c01', ...)]
            LOG.info("Print at most 5 available FCP device combinations: {}".format(
                fcp_combinations[:5]))
            # tmp_list ex:
            # [(fcp_no, wwpn_npiv, wwpn_phy, path, pchid)
            #  ('1a03', '.......', '......', 0,   'AAAA'),
            #  ('1b03', '.......', '......', 1,   'BBBB'),
            #  ('1c03', '.......', '......', 1,   'CCCC')]
            tmp_list = random.choice(sorted(fcp_combinations))
            # fcp_list ex:
            # [{'fcp_id':'1A03', 'path':0, 'pchid':'AAAA', 'wwpn_npiv':'aa', 'wwpn_phy':'xx'},
            #  {'fcp_id':'1B03', 'path':1, 'pchid':'BBBB', 'wwpn_npiv':'cc', 'wwpn_phy':'zz'},
            #  {'fcp_id':'1C03', 'path':2, 'pchid':'CCCC', 'wwpn_npiv':'dd', 'wwpn_phy':'yy'}]
            for fcp in tmp_list:
                item = {
                    'fcp_id': fcp[0].upper(),
                    'wwpn_npiv': fcp[1],
                    'wwpn_phy': fcp[2],
                    'path': fcp[3],
                    'pchid': fcp[4].upper()
                }
                fcp_list.append(item)
            return fcp_list, empty_fcp_list_reason

    def get_fcp_devices(self, fcp_template_id, pchid_info):
        """ Get a group of available FCPs,
        which satisfy the following conditions:
        a. connections = 0
        b. reserved = 0
        c. state = free
        d. wwpn_npiv IS NOT ''
        e. wwpn_phy IS NOT ''

        @param fcp_template_id: (str) FCP multipath template ID
        @param pchid_info: (dict) PCHID as key,
            'allocated' means the count of allocated FCP devices from the PCHID
            'max' means the maximum allowable count of FCP devices that can be allocated from the PCHID
            example:
            {'AAAA': {'allocated': 128, 'max': 128},
             'BBBB': {'allocated': 109, 'max': 110},
             'CCCC': {'allocated': 111, 'max': 128},
             'DDDD': {'allocated': 113, 'max': 110},
             'EEEE': {'allocated': 70,  'max': 90}}
        @return: fcp_list, empty_fcp_list_reason
          empty_fcp_list_reason: (str) the reason of why fcp_list is empty
          fcp_list example:
          [{'fcp_id':'1B02', 'path':1, 'pchid':'BBBB', 'wwpn_npiv':'aa', 'wwpn_phy':'xx'},
           {'fcp_id':'1C04', 'path':4, 'pchid':'CCCC', 'wwpn_npiv':'bb', 'wwpn_phy':'yy'},
           {'fcp_id':'1E05', 'path':5, 'pchid':'EEEE', 'wwpn_npiv':'cc', 'wwpn_phy':'zz'}]
        """

        def _calculate_weight(pchid_info, pchids_per_path_combinations, pchids_without_enough_free_cap):
            """ Calculate the weight based on PCHID info
            In a way, the weight reflects the capability
            of how many times of FCP device allocation can be done.
            The higher is the weight, the stronger is the capability.
            """

            # free_count_in_pchid_info:
            # PCHID as key, free-FCP-device-count as value. Ex:
            # {'AAAA': 1, 'BBBB': 1, 'CCCC': 17, 'DDDD': -3, 'EEEE': 20}
            free_count_in_pchid_info = dict()
            for pchid in pchid_info:
                free_fcp_count = (pchid_info[pchid]['max'] -
                                  pchid_info[pchid]['allocated'])
                free_count_in_pchid_info[pchid.upper()] = free_fcp_count
            LOG.info('free_count_in_pchid_info: {}'.format(free_count_in_pchid_info))
            # comb:
            # path as key, PCHID as value. Ex:
            # {3: 'CCCC', 4: 'CCCC', 5: 'EEEE'}
            for comb in pchids_per_path_combinations:
                # comb_fcp_count_per_pchid:
                # PCHID as key, occurance-count-in-comb as value. Ex:
                # {'EEEE': 1, 'CCCC': 2}
                # In the example, for this comb
                # it means PCHID 'EEEE' occurs once, PCHID 'CCCC' occurs twice;
                # it indicates 1 FCP device from 'EEEE' and 2 from 'CCCC'
                # will be consumed to satisfy one time of FCP device allocation.
                comb_fcp_count_per_pchid = {
                    pchid: (list(comb.values()).count(pchid))
                    for pchid in set(comb.values())}
                # weights ex:
                # {'EEEE': 20/1, 'CCCC': 17/2}
                weights = {p: free_count_in_pchid_info[p] / comb_fcp_count_per_pchid[p]
                           for p in comb_fcp_count_per_pchid}
                for pchid in weights:
                    # if a PCHID's weight < 1,
                    # indicating not enough free capacity for allocating FCP device
                    if weights[pchid] < 1:
                        pchids_without_enough_free_cap[pchid] = free_count_in_pchid_info[pchid]
                # weight:
                # In a way, the weight reflects the capability of how many times
                # of FCP device allocation can be done if choosing this comb.
                # take PCHIDs 'EEEE' and 'CCCC' as example:
                # min(20/1, 17/2) -> min(20, 8.5) -> 8.5
                weight = min(weights.values())
                # comb ex:
                # {3: 'CCCC', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5}
                comb['weight'] = weight
            # log
            LOG.info(
                'after _calculate_weight, pchids_per_path_combinations: '
                '{}'.format(pchids_per_path_combinations))

        def _remove_invalid_weight(pchids_per_path_combinations):
            """remove the combinations whose weight is less than 1"""
            for comb in pchids_per_path_combinations.copy():
                if comb['weight'] < 1:
                    pchids_per_path_combinations.remove(comb)
            # log
            LOG.info(
                'after _remove_invalid_weight, pchids_per_path_combinations: '
                '{}'.format(pchids_per_path_combinations))

        def _select_max_weight(pchids_per_path_combinations):
            """ keep only the combinations with max weight """
            # max_weight ex: 8.5
            max_weight = max(
                p['weight'] for p in pchids_per_path_combinations)
            # keep only the combinations with max weight
            for comb in pchids_per_path_combinations.copy():
                if comb['weight'] != max_weight:
                    pchids_per_path_combinations.remove(comb)
            # log
            LOG.info(
                'after _select_max_weight, pchids_per_path_combinations: '
                '{}'.format(pchids_per_path_combinations))

        def _select_most_distributed_pchids(pchids_per_path_combinations):
            """ keep only the combinations with most distributed PCHIDs """
            # pop the weight
            for comb in pchids_per_path_combinations:
                comb.pop('weight')
            # max_pchid_count ex:
            # max(3,3,2)
            max_pchid_count = max(
                len(set(p.values())) for p in pchids_per_path_combinations)
            # keep only the combinations with most distributed PCHIDs
            for comb in pchids_per_path_combinations.copy():
                if len(set(comb.values())) != max_pchid_count:
                    pchids_per_path_combinations.remove(comb)
            # log
            LOG.info(
                'after _select_most_distributed_pchids, pchids_per_path_combinations: '
                '{}'.format(pchids_per_path_combinations))

        def _get_one_random_fcp_combinations(fcp_template_id, final_pchid_per_path):
            """ randomly choose one FCP device per path
            @param fcp_template_id:
            @param final_pchid_per_path:
                ex: {1: 'BBBB', 4: 'CCCC', 5: 'EEEE'}
            @return: None
            """
            LOG.info('final_pchid_per_path: {}'.format(final_pchid_per_path))
            # Build parameterized per-path/pchid filter
            param_clauses = []
            params = {'tmpl_id': fcp_template_id}
            for i, path in enumerate(final_pchid_per_path):
                p_key = 'p_%d' % i
                pc_key = 'pchid_%d' % i
                param_clauses.append(
                    "(tf.path=:%s AND fcp.pchid=:%s)" % (p_key, pc_key))
                params[p_key] = path
                params[pc_key] = final_pchid_per_path[path]
            pchid_path_filter = ' OR '.join(param_clauses)
            filter_sql, filter_params = _node_filter(prefix='fcp')
            params.update(filter_params)
            sql = (
                "SELECT fcp.fcp_id, fcp.wwpn_npiv, fcp.wwpn_phy, tf.path, fcp.pchid "
                "FROM template_fcp_mapping as tf "
                "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id "
                "WHERE tf.tmpl_id=:tmpl_id "
                "AND fcp.connections=0 "
                "AND fcp.reserved=0 "
                "AND fcp.state='free' "
                "AND fcp.wwpn_npiv <> '' "
                "AND fcp.wwpn_phy <> '' "
                "AND (%s)"
                "%s "
                "ORDER BY tf.path, fcp.pchid, fcp.fcp_id") % (pchid_path_filter,
                                                               filter_sql)

            with get_fcp_conn() as conn:
                query_sql = conn.execute(text(sql), params)
                fcps = query_sql.mappings().fetchall()
            # tmp_dict:
            # path as key, list of FCP devices as value. Ex:
            # { 1: [{'fcp_id': '1B02', ...}, {'fcp_id': '1B05', ...}, ...],
            #   4: [{'fcp_id': '1C04', ...}, {'fcp_id': '1C02', ...}, ...],
            #   5: [{'fcp_id': '1E05', ...}, {'fcp_id': '1E02', ...}, ...]}
            tmp_dict = {path: [] for path in final_pchid_per_path}
            for f in fcps:
                item = {
                    'fcp_id': f['fcp_id'].upper(),
                    'wwpn_npiv': f['wwpn_npiv'],
                    'wwpn_phy': f['wwpn_phy'],
                    'path': f['path'],
                    'pchid': f['pchid'].upper()
                }
                tmp_dict[f['path']].append(item)
            # randomly choose one FCP device per path
            # fcp_comb ex:
            # [{'fcp_id': '1B02', ...},
            #  {'fcp_id': '1C04', ...},
            #  {'fcp_id': '1E05', ...}]
            fcp_comb = [random.choice(tmp_dict[path]) for path in tmp_dict]
            # log
            LOG.info(
                'after _get_one_random_fcp_combinations, '
                'fcp_list: {}'.format(fcp_comb))
            return fcp_comb

        fcp_list = []
        empty_fcp_list_reason = ''
        with get_fcp_conn():
            # free_pchids_per_path:
            # path as key, PCHID (that have free FCP devices) as value. Ex:
            #   { 1: ['AAAA', 'BBBB'],
            #     3: ['CCCC'],
            #     4: ['CCCC', 'DDDD'],
            #     5: ['EEEE']}
            # In the example,
            # both path-3 and path-4 have free FCP devices from PCHID 'CCCC',
            # but the FCP devices in path-3 must differ from that in path-4,
            # because, for each template, one FCP device can only belong to one path.
            free_pchids_per_path = self.get_free_pchids_by_fcp_template(fcp_template_id)
            LOG.info('free_pchids_per_path: {}'.format(free_pchids_per_path))
            if not free_pchids_per_path:
                msg = (
                    'No free FCP device left in FCP multipath template (id={}). '
                    'To use this template, '
                    'you must add more free FCP devices by editing the template. '
                    'For load balance across multiple PCHIDs, '
                    'suggest adding the same amount of '
                    'FCP devices per PCHID.'.format(fcp_template_id))
                LOG.error(msg)
                empty_fcp_list_reason = msg
            else:
                # min_path_count ex: 2
                min_path_count = self.get_min_fcp_paths_count(fcp_template_id)
                # free_path_count ex: 4
                free_path_count = len(free_pchids_per_path)
                # total_path_count
                total_path_count = self.get_path_count(fcp_template_id)
                # compaire total_path_count, min_path_count, free_path_count
                LOG.info('minimum path count is {}. '
                         'total paths count is {}. '
                         'free path count is {}.'
                         .format(min_path_count, total_path_count, free_path_count))
                if free_path_count < min_path_count:
                    empty_fcp_list_reason = (
                        'When you choose an FCP multipath template for '
                        'attaching volume or booting from volume, '
                        'the count of paths with free FCP devices '
                        'must not be less than the minimum path count. '
                        'However, free path count of template (id={}) is {}, '
                        'which is less than its minimum path count {}. '
                        'To use this template, '
                        'you must either modify the minimum path count '
                        'or add more free FCP devices '
                        'by editing the template to meet the requirement.'
                        .format(fcp_template_id, free_path_count, min_path_count))
                    LOG.error(empty_fcp_list_reason)
                else:
                    # free_path_idx ex: [1, 3, 4, 5]
                    free_path_idx = sorted(list(free_pchids_per_path))
                    # path_count_choices:
                    # if min_path_count > free_path_count:
                    #   []
                    # otherwise for example:
                    #   [4, 3, 2] rather than [2, 3, 4]
                    #   because we want to select FCP devices on as more paths as possible
                    path_count_choices = reversed(range(min_path_count, free_path_count + 1))
                    # the for-loop will alwyas be entered.
                    # go through each possible path count, bigest first,
                    # because we want to select FCP devices on as more paths as possible
                    for path_cnt in path_count_choices:
                        # path_cnt      path_idx_combinations
                        # -----------------------------------
                        # 4             [(1, 3, 4, 5)]
                        # 3             [(1, 3, 4), (1, 3, 5), (1, 4, 5), (3, 4, 5)]
                        # 2             ...
                        path_idx_combinations = list(
                            itertools.combinations(free_path_idx, path_cnt))
                        # pchids_per_path_combinations:
                        # a list of dicts with path as key and PCHID as value
                        # path_cnt      pchids_per_path_combinations
                        # -----------------------------------
                        # 3            [{1: 'AAAA', 3: 'CCCC', 4: 'CCCC'},
                        #               {1: 'AAAA', 3: 'CCCC', 4: 'DDDD'},
                        #               {1: 'BBBB', 3: 'CCCC', 4: 'CCCC'},
                        #               {1: 'BBBB', 3: 'CCCC', 4: 'DDDD'},
                        #               {1: 'AAAA', 3: 'CCCC', 5: 'EEEE'},
                        #               {1: 'BBBB', 3: 'CCCC', 5: 'EEEE'},
                        #               {1: 'AAAA', 4: 'CCCC', 5: 'EEEE'},
                        #               {1: 'AAAA', 4: 'DDDD', 5: 'EEEE'},
                        #               {1: 'BBBB', 4: 'CCCC', 5: 'EEEE'},
                        #               {1: 'BBBB', 4: 'DDDD', 5: 'EEEE'},
                        #               {3: 'CCCC', 4: 'CCCC', 5: 'EEEE'},
                        #               {3: 'CCCC', 4: 'DDDD', 5: 'EEEE'}]
                        pchids_per_path_combinations = list()
                        for path_idx_comb in path_idx_combinations:
                            # path_idx_comb  pchids_per_path_comb
                            # -------------------------------
                            # (1, 3, 4)      [['AAAA', 'BBBB'],
                            #                 ['CCCC'],
                            #                 ['CCCC', 'DDDD']]
                            pchids_per_path_comb = [free_pchids_per_path[idx]
                                                    for idx in path_idx_comb]
                            # path_idx_comb     tmp_pchid_comb
                            # -------------------------------
                            # (1, 3, 4)         [('AAAA', 'CCCC', 'CCCC'),
                            #                    ('AAAA', 'CCCC', 'DDDD'),
                            #                    ('BBBB', 'CCCC', 'CCCC'),
                            #                    ('BBBB', 'CCCC', 'DDDD')]
                            tmp_pchid_comb = list(itertools.product(*pchids_per_path_comb))
                            # tmp_pchid_comb_with_path:
                            # a list of dicts with path as key and PCHID as value
                            # path_idx_comb     tmp_pchid_comb_with_path
                            # -------------------------------
                            # (1, 3, 4)         [{1: 'AAAA', 3: 'CCCC', 4: 'CCCC'},
                            #                    {1: 'AAAA', 3: 'CCCC', 4: 'DDDD'},
                            #                    {1: 'BBBB', 3: 'CCCC', 4: 'CCCC'},
                            #                    {1: 'BBBB', 3: 'CCCC', 4: 'DDDD'}]
                            tmp_pchid_comb_with_path = [
                                dict(zip(path_idx_comb, comb)) for comb in tmp_pchid_comb]
                            pchids_per_path_combinations.extend(tmp_pchid_comb_with_path)

                        # pchids_without_enough_free_cap ex:
                        # {'AAAA': 1, 'DDDD': -3}
                        pchids_without_enough_free_cap = dict()
                        # calculate weight for each combination,
                        # afterwards, weight is added, ex:
                        # path_cnt pchids_per_path_combinations
                        # -----------------------------------
                        # 3        [{1: 'AAAA', 3: 'CCCC', 4: 'CCCC', 'weight': 0.0},
                        #           {1: 'AAAA', 3: 'CCCC', 4: 'DDDD', 'weight': -3.0},
                        #           {1: 'BBBB', 3: 'CCCC', 4: 'CCCC', 'weight': 1.0},
                        #           {1: 'BBBB', 3: 'CCCC', 4: 'DDDD', 'weight': -3.0},
                        #           {1: 'AAAA', 3: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                        #           {1: 'BBBB', 3: 'CCCC', 5: 'EEEE', 'weight': 1.0},
                        #           {1: 'AAAA', 4: 'CCCC', 5: 'EEEE', 'weight': 0.0},
                        #           {1: 'AAAA', 4: 'DDDD', 5: 'EEEE', 'weight': -3.0},
                        #           {1: 'BBBB', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                        #           {1: 'BBBB', 4: 'DDDD', 5: 'EEEE', 'weight': -3.0},
                        #           {3: 'CCCC', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                        #           {3: 'CCCC', 4: 'DDDD', 5: 'EEEE', 'weight': -3.0}]
                        _calculate_weight(
                            pchid_info, pchids_per_path_combinations, pchids_without_enough_free_cap)
                        # remove the combinations
                        # whose weight is less than 1, ex:
                        # path_cnt pchids_per_path_combinations
                        # -----------------------------------
                        # 3        [{1: 'BBBB', 3: 'CCCC', 4: 'CCCC', 'weight': 1.0},
                        #           {1: 'AAAA', 3: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                        #           {1: 'BBBB', 3: 'CCCC', 5: 'EEEE', 'weight': 1.0},
                        #           {1: 'BBBB', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                        #           {3: 'CCCC', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5}]
                        _remove_invalid_weight(pchids_per_path_combinations)
                        # _select_max_weight must be called before
                        # _select_most_distributed_pchids, because we treat
                        # _select_max_weight with higher priority
                        if pchids_per_path_combinations:
                            # keep only the combinations with max weight
                            # path_cnt pchids_per_path_combinations
                            # -----------------------------------
                            # 3        [{1: 'BBBB', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                            #           {1: 'AAAA', 3: 'CCCC', 5: 'EEEE', 'weight': 8.5},
                            #           {3: 'CCCC', 4: 'CCCC', 5: 'EEEE', 'weight': 8.5}]
                            _select_max_weight(pchids_per_path_combinations)
                            # keep only the combinations with most distributed PCHIDs
                            # path_cnt pchids_per_path_combinations
                            # -----------------------------------
                            # 3        [{1: 'BBBB', 4: 'CCCC', 5: 'EEEE'},
                            #           {1: 'AAAA', 3: 'CCCC', 5: 'EEEE'}]
                            _select_most_distributed_pchids(pchids_per_path_combinations)
                            # random select one from the final candidate combinations
                            # path_cnt final_pchid_per_path
                            # -----------------------------------
                            # 3        {1: 'BBBB', 4: 'CCCC', 5: 'EEEE'}
                            final_pchid_per_path = random.choice(pchids_per_path_combinations)
                            # randomly choose one FCP device per path
                            # fcp_list ex:
                            # [{'fcp_id':'1B02', 'path':1, 'pchid':'BBBB', 'wwpn_npiv':'aa', 'wwpn_phy':'xx'},
                            #  {'fcp_id':'1C04', 'path':4, 'pchid':'CCCC', 'wwpn_npiv':'bb', 'wwpn_phy':'yy'},
                            #  {'fcp_id':'1E05', 'path':5, 'pchid':'EEEE', 'wwpn_npiv':'cc', 'wwpn_phy':'zz'}]
                            fcp_list = _get_one_random_fcp_combinations(fcp_template_id, final_pchid_per_path)
                            break
                    # check
                    if not fcp_list:
                        empty_fcp_list_reason = (
                            'Not enough free capacity of the following PCHIDs left. '
                            'Their free capacity is {}. '
                            'To use this FCP multipath template (id={}), '
                            'you must either increase free capacity of above PCHIDs '
                            'or add more free FCP devices '
                            'whose PCHIDs have enough free capacity by editing the template.'
                            .format(sorted(pchids_without_enough_free_cap.items()),
                                    fcp_template_id))
                        LOG.error(empty_fcp_list_reason)
        # return
        return fcp_list, empty_fcp_list_reason

    def create_fcp_template(self, fcp_template_id, name, description,
                            fcp_devices_by_path, host_default,
                            default_sp_list, min_fcp_paths_count=None):
        """ Insert records of new FCP Multipath Template in fcp DB

        :param fcp_template_id: FCP Multipath Template ID
        :param name: FCP Multipath Template name
        :param description: description
        :param fcp_devices_by_path:
            Example:
            if fcp_list is "0011-0013;0015;0017-0018",
            then fcp_devices_by_path should be passed like:
            {
              0: {'0011' ,'0012', '0013'}
              1: {'0015'}
              2: {'0017', '0018'}
            }
        :param host_default: (bool)
        :param default_sp_list: (list)
        :param min_fcp_paths_count: (int) if it is None, -1 will be saved
                                    to template table as default value.
        :return: NULL
        """
        # The following multiple DQLs (Database query)
        # are put into the with-block with DMLs
        # because the consequent DMLs (Database modification)
        # depend on the result of the DQLs.
        # So that, other threads can NOT begin a sqlite transaction
        # until current thread exits the with-block.
        # Refer to 'def get_fcp_conn' for thread lock
        with get_fcp_conn() as conn:
            # first check the template exist or not
            # if already exist, raise exception
            if self.fcp_template_exist_in_db(fcp_template_id):
                raise exception.SDKObjectAlreadyExistError(
                    obj_desc=("FCP Multipath Template "
                              "(id: %s) " % fcp_template_id),
                    modID=self._module_id)
            # then check the SP records exist in template_sp_mapping or not
            # if already exist, will update the tmpl_id
            # if not exist, will insert new records
            sp_mapping_to_add = list()
            sp_mapping_to_update = list()
            if not default_sp_list:
                default_sp_list = []
            for sp_name in default_sp_list:
                record = (fcp_template_id, sp_name)
                if self.sp_name_exist_in_db(sp_name):
                    sp_mapping_to_update.append(record)
                else:
                    sp_mapping_to_add.append(record)
            # Prepare records include (fcp_id, tmpl_id, path)
            # to be inserted into table template_fcp_mapping
            fcp_mapping = list()
            for path in fcp_devices_by_path:
                for fcp_id in fcp_devices_by_path[path]:
                    new_record = [fcp_id, fcp_template_id, path]
                    fcp_mapping.append(new_record)

            # 1. change the is_default of existing templates to False,
            #    if the is_default of the being-created template is True,
            #    because only one default template per host is allowed
            if host_default is True:
                conn.execute(text("UPDATE template SET is_default=:val"),
                             {'val': False})
            # 2. insert a new record in template table
            #    if min_fcp_paths_count is None, -1 will be used as the default
            node_id = db_api.get_compute_node_id()
            if not min_fcp_paths_count:
                conn.execute(
                    text("INSERT INTO template"
                         " (id, compute_node_id, name, description, is_default)"
                         " VALUES (:id, :node_id, :name, :desc, :is_default)"),
                    {'id': fcp_template_id, 'node_id': node_id,
                     'name': name, 'desc': description,
                     'is_default': host_default})
            else:
                conn.execute(
                    text("INSERT INTO template"
                         " (id, compute_node_id, name, description,"
                         "  is_default, min_fcp_paths_count)"
                         " VALUES (:id, :node_id, :name, :desc,"
                         "  :is_default, :min_count)"),
                    {'id': fcp_template_id, 'node_id': node_id,
                     'name': name, 'desc': description,
                     'is_default': host_default, 'min_count': min_fcp_paths_count})
            # 3. insert new records in template_fcp_mapping
            if fcp_mapping:
                conn.execute(
                    text("INSERT INTO template_fcp_mapping"
                         " (fcp_id, tmpl_id, compute_node_id, path)"
                         " VALUES (:fcp_id, :tmpl_id, :node_id, :path)"),
                    [{'fcp_id': r[0], 'tmpl_id': r[1], 'node_id': node_id, 'path': r[2]}
                     for r in fcp_mapping])
            # 4. insert a new record in template_sp_mapping
            if default_sp_list:
                if sp_mapping_to_add:
                    conn.execute(
                        text("INSERT INTO template_sp_mapping"
                             " (sp_name, tmpl_id, compute_node_id)"
                             " VALUES (:sp_name, :tmpl_id, :node_id)"),
                        [{'sp_name': r[1], 'tmpl_id': r[0], 'node_id': node_id}
                         for r in sp_mapping_to_add])
                if sp_mapping_to_update:
                    conn.execute(
                        text("UPDATE template_sp_mapping SET tmpl_id=:tmpl_id "
                             "WHERE sp_name=:sp_name"),
                        [{'tmpl_id': r[0], 'sp_name': r[1]}
                         for r in sp_mapping_to_update])

    def _validate_min_fcp_paths_count(self, fcp_devices, min_fcp_paths_count, fcp_template_id):
        """
        When to edit FCP Multipath Template, if min_fcp_paths_count is not None or
        fcp_devices is not None (None means no need to update this field, but keep the original value),
        need to validate the values.
        min_fcp_paths_count should not be larger than fcp_device_path_count.
        If min_fcp_paths_count is None, get the value from template table.
        If fcp_devices is None, get the fcp_device_path_count from template_fcp_mapping table.
        """
        if min_fcp_paths_count or fcp_devices:
            with get_fcp_conn():
                if not fcp_devices:
                    fcp_devices_path_count = self.get_path_count(fcp_template_id)
                else:
                    fcp_devices_by_path = utils.expand_fcp_list(fcp_devices)
                    fcp_devices_path_count = len(fcp_devices_by_path)
                if not min_fcp_paths_count:
                    min_fcp_paths_count = self.get_min_fcp_paths_count_from_db(fcp_template_id)
            # raise exception
            if min_fcp_paths_count > fcp_devices_path_count:
                msg = ("min_fcp_paths_count %s is larger than fcp device path count %s. "
                       "Adjust the fcp_devices setting or "
                       "min_fcp_paths_count." % (min_fcp_paths_count, fcp_devices_path_count))
                LOG.error(msg)
                raise exception.SDKConflictError(modID=self._module_id, rs=23, msg=msg)

    def get_min_fcp_paths_count(self, fcp_template_id):
        """ Get min_fcp_paths_count from FCP multipath template

        @param fcp_template_id: (str) id of FCP multipath template
        @return: (integer)
            If it is -1, return path count of the template from template_fcp_mapping table.
            otherwise, return the min_fcp_paths_count from template table.
            If it is None, raise error.
        """
        if not fcp_template_id:
            min_fcp_paths_count = None
        else:
            with get_fcp_conn():
                min_fcp_paths_count = self.get_min_fcp_paths_count_from_db(fcp_template_id)
                if min_fcp_paths_count == -1:
                    min_fcp_paths_count = self.get_path_count(fcp_template_id)
        if min_fcp_paths_count is None:
            obj_desc = "min_fcp_paths_count from fcp_template_id %s" % fcp_template_id
            raise exception.SDKObjectNotExistError(obj_desc=obj_desc)
        return min_fcp_paths_count

    def edit_fcp_template(self, fcp_template_id, name=None, description=None,
                          fcp_devices=None, host_default=None,
                          default_sp_list=None, min_fcp_paths_count=None):
        """ Edit a FCP Multipath Template.

        The kwargs values are pre-validated in two places:
          validate kwargs types
            in zvmsdk/sdkwsgi/schemas/volume.py
          set a kwarg as None if not passed by user
            in zvmsdk/sdkwsgi/handlers/volume.py

        If any kwarg is None, the kwarg will not be updated.

        :param fcp_template_id:     template id
        :param name:                template name
        :param description:         template desc
        :param fcp_devices:         FCP devices divided into
                                    different paths by semicolon
          Format:
            "fcp-devices-from-path0;fcp-devices-from-path1;..."
          Example:
            "0011-0013;0015;0017-0018",
        :param host_default: (bool)
        :param default_sp_list: (list)
          Example:
            ["SP1", "SP2"]
        :param min_fcp_paths_count: if it is None, then will not update this field in db.
        :return:
          Example
            {
              'fcp_template': {
                'name': 'bjcb-test-template',
                'id': '36439338-db14-11ec-bb41-0201018b1dd2',
                'description': 'This is Default template',
                'host_default': True,
                'storage_providers': ['sp4', 'v7k60'],
                'min_fcp_paths_count': 2,
                'pchids': {
                    'add' : {
                        'all': ['A', 'B'],
                        'first_used_by_templates': ['B']
                    },
                    'delete' : {
                        'all': ['D', 'E'],
                        'not_exist_in_any_template': ['E']
                    },
                    'all' : ['A', 'B', 'C']
                }
              }
            }
        """
        # The following multiple DQLs (Database query)
        # are put into the with-block with DMLs
        # because the consequent DMLs (Database modification)
        # depend on the result of the DQLs.
        # So that, other threads can NOT begin a sqlite transaction
        # until current thread exits the with-block.
        # Refer to 'def get_fcp_conn' for thread lock
        with get_fcp_conn():
            # DQL: validate: FCP Multipath Template
            if not self.fcp_template_exist_in_db(fcp_template_id):
                obj_desc = ("FCP Multipath Template {}".format(fcp_template_id))
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc)

            # DQL: validate: add or delete path from FCP Multipath Template.
            # If fcp_devices is None, it means user do not want to
            # modify fcp_devices, so skip the validation;
            # otherwise, perform the validation.
            if fcp_devices is not None:
                fcp_path_count_from_input = len(
                    [i for i in fcp_devices.split(';') if i])
                fcp_path_count_in_db = self.get_path_count(fcp_template_id)
                if fcp_path_count_from_input != fcp_path_count_in_db:
                    inuse_fcp = self.get_inuse_fcp_device_by_fcp_template(
                        fcp_template_id)
                    if inuse_fcp:
                        inuse_fcp = utils.shrink_fcp_list(
                            [fcp['fcp_id'] for fcp in inuse_fcp])
                        detail = ("The FCP devices ({}) are allocated to virtual machines "
                                  "by the FCP Multipath Template (id={}). "
                                  "Adding or deleting a FCP device path from a FCP Multipath Template "
                                  "is not allowed if there is any FCP device allocated from the template. "
                                  "You must deallocate those FCP devices "
                                  "before adding or deleting a path from the template."
                                  .format(inuse_fcp, fcp_template_id))
                        raise exception.SDKConflictError(modID=self._module_id, rs=24, msg=detail)
            # If min_fcp_paths_count is not None or fcp_devices is not None, need to validate the value.
            # min_fcp_paths_count should not be larger than fcp device path count, or else, raise error.
            self._validate_min_fcp_paths_count(fcp_devices, min_fcp_paths_count, fcp_template_id)
            ori_pchid_list = self.get_pchids_by_fcp_template(fcp_template_id)
            all_pchid_used_by_templates = self.get_pchids_from_all_fcp_templates()
            tmpl_basic, fcp_detail = self.get_fcp_templates_details(
                [fcp_template_id])

            # DML: table template_fcp_mapping
            if fcp_devices is not None:
                # fcp_from_input:
                # fcp devices from user input
                # example:
                # {'0011': 0, '0013': 0,  <<< path 0
                #  '0015': 1,             <<< path 1
                #  '0018': 2, '0017': 2}  <<< path 2
                fcp_from_input = dict()
                # fcp_devices_by_path:
                # example:
                # if fcp_devices is "0011-0013;0015;0017-0018",
                # then fcp_devices_by_path is :
                # {
                #   0: {'0011', '0013'}
                #   1: {'0015'}
                #   2: {'0017', '0018'}
                # }
                fcp_devices_by_path = utils.expand_fcp_list(fcp_devices)
                for path in fcp_devices_by_path:
                    for fcp_id in fcp_devices_by_path[path]:
                        fcp_from_input[fcp_id] = path
                # fcp_in_db:
                # FCP devices belonging to fcp_template_id
                # queried from database including the FCP devices
                # that are not found in z/VM
                # example:
                # {'0011': <sqlite3.Row object at 0x3ff85>,
                #  '0013': <sqlite3.Row object at 0x3f3da>}
                fcp_in_db = dict()
                for row in fcp_detail:
                    fcp_in_db[row['fcp_id']] = row
                # Divide the FCP devices into three sets
                add_set = set(fcp_from_input) - set(fcp_in_db)
                inter_set = set(fcp_from_input) & set(fcp_in_db)
                del_set = set(fcp_in_db) - set(fcp_from_input)
                # only unused FCP devices can be
                # deleted from a FCP Multipath Template.
                # Two types of unused FCP devices:
                # 1. connections/reserved == None:
                #   the fcp only exists in table(template_fcp_mapping),
                #   rather than table(fcp)
                # 2. connections/reserved == 0:
                #   the fcp exists in both tables
                #   and it is not allocated from FCP DB
                not_allow_for_del = set()
                for fcp in del_set:
                    if (fcp_in_db[fcp]['connections'] not in (None, 0) or
                            fcp_in_db[fcp]['reserved'] not in (None, 0)):
                        not_allow_for_del.add(fcp)
                # For a FCP device included in multiple FCP Multipath Templates,
                # the FCP device is allowed to be deleted from the current template
                # only if it is allocated from another template rather than the current one
                inuse_fcp_devices = self.get_inuse_fcp_device_by_fcp_template(fcp_template_id)
                inuse_fcp_by_current_template = set(fcp['fcp_id'] for fcp in inuse_fcp_devices)
                not_allow_for_del &= inuse_fcp_by_current_template
                # validate: not allowed to remove inuse FCP devices
                if not_allow_for_del:
                    not_allow_for_del = utils.shrink_fcp_list(
                        list(not_allow_for_del))
                    detail = ("The FCP devices ({}) are missing from the FCP device list. "
                              "These FCP devices are allocated to virtual machines "
                              "from the FCP Multipath Template (id={}). "
                              "Deleting the allocated FCP devices from this template is not allowed. "
                              "You must ensure those FCP devices are included in the FCP device list."
                              .format(not_allow_for_del, fcp_template_id))
                    raise exception.SDKConflictError(modID=self._module_id, rs=24, msg=detail)

                # DML: table template_fcp_mapping
                LOG.info("DML: table template_fcp_mapping")
                # 1. delete from table template_fcp_mapping
                records_to_delete = [
                    (fcp_template_id, fcp_id)
                    for fcp_id in del_set]
                self.bulk_delete_fcp_device_from_fcp_template(
                    records_to_delete)
                LOG.info("FCP devices ({}) removed from FCP Multipath Template {}."
                         .format(utils.shrink_fcp_list(list(del_set)),
                                 fcp_template_id))
                # 2. insert into table template_fcp_mapping
                records_to_insert = [
                    (fcp_template_id, fcp_id, fcp_from_input[fcp_id])
                    for fcp_id in add_set]
                self.bulk_insert_fcp_device_into_fcp_template(
                    records_to_insert)
                LOG.info("FCP devices ({}) added into FCP Multipath Template {}."
                         .format(utils.shrink_fcp_list(list(add_set)),
                                 fcp_template_id))
                # 3. update table template_fcp_mapping
                #    update path of fcp devices if changed
                for fcp in inter_set:
                    path_from_input = fcp_from_input[fcp]
                    path_in_db = fcp_in_db[fcp]['path']
                    if path_from_input != path_in_db:
                        record_to_update = (
                            fcp_from_input[fcp], fcp, fcp_template_id)
                        self.update_path_of_fcp_device(record_to_update)
                        LOG.info("FCP device ({}) updated into "
                                 "FCP Multipath Template {} from path {} to path {}."
                                 .format(fcp, fcp_template_id,
                                         fcp_in_db[fcp]['path'],
                                         fcp_from_input[fcp]))

            # DML: table template
            if (name, description, host_default, min_fcp_paths_count) != (None, None, None, None):
                LOG.info("DML: table template")
                record_to_update = (
                    name if name is not None
                    else tmpl_basic[0]['name'],
                    description if description is not None
                    else tmpl_basic[0]['description'],
                    host_default if host_default is not None
                    else tmpl_basic[0]['is_default'],
                    min_fcp_paths_count if min_fcp_paths_count is not None
                    else tmpl_basic[0]['min_fcp_paths_count'],
                    fcp_template_id)
                self.update_basic_info_of_fcp_template(record_to_update)
                LOG.info("FCP Multipath Template basic info updated.")

            # DML: table template_sp_mapping
            if default_sp_list is not None:
                LOG.info("DML: table template_sp_mapping")
                self.bulk_set_sp_default_by_fcp_template(fcp_template_id,
                                                         default_sp_list)
                LOG.info("Default template of storage providers ({}) "
                         "updated.".format(default_sp_list))

            # Return template basic info queried from DB
            # tmpl_basic is a list containing one or more sqlite.Row objects
            # Example:
            #  if a template is the SP-level default for 2 SPs (SP1 and SP2)
            #  (i.e. the template has 2 entries in table template_sp_mapping
            #  then tmpl_basic is a list containing 2 Row objects,
            #  the only different value between the 2 Row objects is 'sp_name'
            #  (i.e. tmpl_basic[0]['sp_name'] is 'SP1',
            #  while tmpl_basic[1]['sp_name'] is 'SP2'.
            tmpl_basic = self.get_fcp_templates_details([fcp_template_id])[0]
            final_pchid_list = self.get_pchids_by_fcp_template(fcp_template_id)
            add_pchids = dict(all=list(set(final_pchid_list) -
                                       set(ori_pchid_list)),
                              first_used_by_templates=list(set(final_pchid_list) -
                                                           set(all_pchid_used_by_templates)))

            del_pchids = list(set(ori_pchid_list) - set(final_pchid_list))
            all_pchids_in_template = self.get_pchids_from_all_fcp_templates()
            not_used_in_any_template = list(set(del_pchids) - set(all_pchids_in_template))
            delete_dict = dict(all=del_pchids,
                               not_exist_in_any_template=not_used_in_any_template)
            return {'fcp_template': {
                'name': tmpl_basic[0]['name'],
                'id': tmpl_basic[0]['id'],
                'description': tmpl_basic[0]['description'],
                'host_default': bool(tmpl_basic[0]['is_default']),
                'storage_providers':
                    [] if tmpl_basic[0]['sp_name'] is None
                    else [r['sp_name'] for r in tmpl_basic],
                'min_fcp_paths_count': self.get_min_fcp_paths_count(fcp_template_id),
                'pchids': {
                    'add': add_pchids,
                    'delete': delete_dict,
                    'all': final_pchid_list
                }
            }}

    def get_pchids_from_all_fcp_templates(self):
        """Get pchids info used by all FCP Multipath Templates.
            :param None
            :return pchids: (list) a list of pchid
            for example: ['0240', '0260']
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        where = filter_sql.replace(" AND", " WHERE", 1)
        pchids = []
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT DISTINCT fcp.pchid "
                     "FROM template_fcp_mapping AS tf "
                     "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id" + where),
                filter_params)
            raw = _fetchall(result)
            for item in raw:
                pchids.append(item['pchid'].upper())
        return pchids

    def get_pchids_of_all_inuse_fcp_devices(self):
        """Get the PCHIDs of all the FCP devices allocated from any FCP multipath template

        :param None
        :return pchids: (dict) PCHIDs as keys, FCP devices as values
            for example:
            {
                '02E0': '1A01 - 1A03',
                '03FC': '1B02, 1B05'
            }
        """
        filter_sql, filter_params = _node_filter()
        pchids = dict()
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT pchid, fcp_id FROM fcp "
                     "WHERE tmpl_id <> ''"
                     + filter_sql +
                     " ORDER BY pchid"),
                filter_params)
            # already ORDER BY pchid in SQL
            # inuse_fcp_devices ex:
            # [ each item is a sqlite3.Row object that can be accessed in dict-style
            #   {'pchid': '02e0',  'fcp_id': '1a01'},
            #   {'pchid': '02e0',  'fcp_id': '1a02'},
            #   {'pchid': '02e0',  'fcp_id': '1a03'},
            #   {'pchid': '03fc',  'fcp_id': '1b02'},
            #   {'pchid': '03fc',  'fcp_id': '1b05'} ]
            inuse_fcp_devices = _fetchall(result)

        # shrink_fcp_list
        if inuse_fcp_devices:
            # tmp_fcps ex:
            # ('1A01', '1A02', '1A03', '1B02', '1B05')
            tmp_fcps = tuple(fcp['fcp_id'] for fcp in inuse_fcp_devices)
            # tmp_pchids ex:
            # ('02E0', '02E0', '02E0', '03FC', '03FC')
            tmp_pchids = tuple(fcp['pchid'] for fcp in inuse_fcp_devices)
            # process per pchid
            for pd in set(tmp_pchids):
                first_idx = tmp_pchids.index(pd)
                last_idx = first_idx + tmp_pchids.count(pd)
                # shrink_fcp_list
                shrunk_fcp_devices = utils.shrink_fcp_list(
                    list(tmp_fcps[first_idx:last_idx]))
                pchids[pd.upper()] = shrunk_fcp_devices
        return pchids

    def get_fcp_templates(self, template_id_list=None):
        """Get FCP Multipath Templates base info by template_id_list.
        If template_id_list is None, will get all the FCP Multipath Templates in db.

        return format:
        [(id|name|description|is_default|min_fcp_paths_count|sp_name)]
        """
        filter_sql, filter_params = _node_filter(prefix='template')
        cmd = ("SELECT template.id, template.name, template.description, "
               "template.is_default, template.min_fcp_paths_count, template_sp_mapping.sp_name "
               "FROM template "
               "LEFT OUTER JOIN template_sp_mapping "
               "ON template.id=template_sp_mapping.tmpl_id")

        with get_fcp_conn() as conn:
            if template_id_list:
                params = {'ids': template_id_list, **filter_params}
                result = conn.execute(
                    text(cmd + " WHERE template.id IN :ids" + filter_sql).bindparams(
                        bindparam('ids', expanding=True)),
                    params)
            else:
                where = filter_sql.replace(" AND", " WHERE", 1)
                result = conn.execute(text(cmd + where), filter_params)

            raw = _fetchall(result)
        return raw

    def get_pchids_by_fcp_template(self, fcp_template_id):
        """Get pchid info of one FCP Multipath Template by fcp_template_id.

        :param fcp_template_id: (str) id of FCP Multipath Template

        :return pchids: (list) a list of pchid
        for example: ['02E0', '02C0']
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        pchids = []
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT DISTINCT fcp.pchid "
                     "FROM template_fcp_mapping AS tf "
                     "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id "
                     "WHERE tf.tmpl_id=:tmpl_id" + filter_sql),
                {'tmpl_id': fcp_template_id, **filter_params})

            raw = _fetchall(result)
            for item in raw:
                pchids.append(item['pchid'].upper())
        return pchids

    def get_free_pchids_by_fcp_template(self, fcp_template_id):
        """Get PCHIDs that have free FCP devices per path of the template

        :param fcp_template_id: (str) id of FCP Multipath Template

        :return pchids: (dict) path number as key, PCHIDs as value
            for example:
            {'1': ['01E0', '02A0'],
             '3': ['02A0', '03FC']}
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        pchids = dict()
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT DISTINCT path, pchid "
                     "FROM template_fcp_mapping AS tf "
                     "INNER JOIN fcp ON tf.fcp_id=fcp.fcp_id "
                     "WHERE tf.tmpl_id=:tmpl_id "
                     "AND fcp.connections=0 "
                     "AND fcp.reserved=0 "
                     "AND fcp.state='free' "
                     "AND fcp.wwpn_npiv <> '' "
                     "AND fcp.wwpn_phy <> '' "
                     + filter_sql +
                     " ORDER BY path, pchid"),
                {'tmpl_id': fcp_template_id, **filter_params})

            # free_pchids_per_path ex:
            # [ each item is a sqlite3.Row object that can be accessed in dict-style
            #   {'pchid': '01E0',  'path': '1'},
            #   {'pchid': '02A0',  'path': '1'},
            #   {'pchid': '02A0',  'path': '3'},
            #   {'pchid': '03FC',  'path': '3'} ]
            free_pchids_per_path = _fetchall(result)
            for item in free_pchids_per_path:
                if item['path'] not in pchids:
                    pchids[item['path']] = []
                pchids[item['path']].append(item['pchid'].upper())
        return pchids

    def get_host_default_fcp_template(self, host_default=True):
        """Get the host default FCP Multipath Template base info.
        return format: (id|name|description|is_default|sp_name)

        when the  template is more than one SP's default,
        then it will show up several times in the result.
        """
        filter_sql, filter_params = _node_filter(prefix='t')
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT t.id, t.name, t.description, t.is_default, "
                     "t.min_fcp_paths_count, ts.sp_name "
                     "FROM template AS t "
                     "LEFT OUTER JOIN template_sp_mapping AS ts "
                     "ON t.id=ts.tmpl_id "
                     "WHERE t.is_default=:val" + filter_sql),
                {'val': 1 if host_default else 0, **filter_params})
            raw = _fetchall(result)
        return raw

    def get_sp_default_fcp_template(self, sp_host_list):
        """Get the sp_host_list default FCP Multipath Template.
        """
        filter_sql, filter_params = _node_filter(prefix='t')
        cmd = ("SELECT t.id, t.name, t.description, t.is_default, "
               "t.min_fcp_paths_count, ts.sp_name "
               "FROM template_sp_mapping AS ts "
               "INNER JOIN template AS t "
               "ON ts.tmpl_id=t.id")
        raw = []
        with get_fcp_conn() as conn:
            if (len(sp_host_list) == 1 and
                    sp_host_list[0].lower() == 'all'):
                where = filter_sql.replace(" AND", " WHERE", 1)
                result = conn.execute(text(cmd + where), filter_params)
                raw = _fetchall(result)
            else:
                for sp_host in sp_host_list:
                    params = {'sp_name': sp_host, **filter_params}
                    result = conn.execute(
                        text(cmd + " WHERE ts.sp_name=:sp_name" + filter_sql),
                        params)
                    raw.extend(_fetchall(result))
        return raw

    def get_fcp_template_by_assigner_id(self, assigner_id):
        """Get a templates list of specified assigner.
        """
        filter_sql, filter_params = _node_filter(prefix='fcp')
        with get_fcp_conn() as conn:
            result = conn.execute(
                text("SELECT t.id, t.name, t.description, t.is_default, "
                     "t.min_fcp_paths_count, ts.sp_name "
                     "FROM fcp "
                     "INNER JOIN template AS t ON fcp.tmpl_id=t.id "
                     "LEFT OUTER JOIN template_sp_mapping AS ts "
                     "ON fcp.tmpl_id=ts.tmpl_id "
                     "WHERE fcp.assigner_id=:assigner_id" + filter_sql),
                {'assigner_id': assigner_id, **filter_params})
            raw = _fetchall(result)
            # id|name|description|is_default|min_fcp_paths_count|sp_name
        return raw

    def get_fcp_templates_details(self, template_id_list=None):
        """Get templates detail info by template_id_list

        :param template_id_list: must be a list or None

        If template_id_list=None, will get all the templates detail info.

        Detail info including two parts: base info and fcp device info, these
        two parts info will use two cmds to get from db and return out, outer
        method will join these two return output.

        'tmpl_cmd' is used to get base info from template table and
        template_sp_mapping table.

        tmpl_cmd result format:
        id|name|description|is_default|min_fcp_paths_count|sp_name

        'devices_cmd' is used to get fcp device info. Device's template id is
        gotten from template_fcp_mapping table, device's usage info is gotten
        from fcp table. Because not all the templates' fcp device is in fcp
        table, so the fcp device's template id should being gotten from
        template_fcp_mapping table insteading of fcp table.

        'devices_cmd' result format:
        fcp_id|tmpl_id|path|assigner_id|connections|reserved|
        wwpn_npiv|wwpn_phy|chpid|pchid|state|owner|tmpl_id

        In 'devices_cmd' result: the first three properties are from
        template_fcp_mapping table, and the others are from fcp table.
        when the device is not in fcp table, all the properties in fcp
        table will be None. For example: template '12345678' has a fcp
        "1aaa" on path 0, but this device is not in fcp table, the
        query result will be as below.

        1aaa|12345678|0|||||||||
        """
        t_filter_sql, t_filter_params = _node_filter(prefix='t')
        fcp_filter_sql, fcp_filter_params = _node_filter(prefix='fcp')
        tmpl_cmd = (
            "SELECT t.id, t.name, t.description, "
            "t.is_default, t.min_fcp_paths_count, ts.sp_name "
            "FROM template AS t "
            "LEFT OUTER JOIN template_sp_mapping AS ts "
            "ON t.id=ts.tmpl_id")

        devices_cmd = (
            "SELECT tf.fcp_id, tf.tmpl_id, tf.path, fcp.assigner_id, "
            "fcp.connections, fcp.reserved, fcp.wwpn_npiv, fcp.wwpn_phy, "
            "fcp.chpid, fcp.pchid, fcp.state, fcp.owner, fcp.tmpl_id "
            "FROM template_fcp_mapping AS tf "
            "LEFT OUTER JOIN fcp "
            "ON tf.fcp_id=fcp.fcp_id")

        with get_fcp_conn() as conn:
            if template_id_list:
                tmpl_params = {'ids': template_id_list, **t_filter_params}
                tmpl_result = conn.execute(
                    text(tmpl_cmd + " WHERE t.id IN :ids" + t_filter_sql).bindparams(
                        bindparam('ids', expanding=True)),
                    tmpl_params)
                dev_params = {'ids': template_id_list, **fcp_filter_params}
                devices_result = conn.execute(
                    text(devices_cmd + " WHERE tf.tmpl_id IN :ids" + fcp_filter_sql).bindparams(
                        bindparam('ids', expanding=True)),
                    dev_params)
            else:
                t_where = t_filter_sql.replace(" AND", " WHERE", 1)
                tmpl_result = conn.execute(text(tmpl_cmd + t_where), t_filter_params)
                fcp_where = fcp_filter_sql.replace(" AND", " WHERE", 1)
                devices_result = conn.execute(text(devices_cmd + fcp_where), fcp_filter_params)

            tmpl_result = _fetchall(tmpl_result)
            devices_result = _fetchall(devices_result)

        return tmpl_result, devices_result

    def bulk_delete_fcp_from_template(self, fcp_id_list, fcp_template_id):
        """Delete multiple FCP records from the table template_fcp_mapping in the
        specified FCP Multipath Template only if the FCP devices are available."""
        records_to_delete = [{'tmpl_id': fcp_template_id, 'fcp_id': fcp_id}
                              for fcp_id in fcp_id_list]
        with get_fcp_conn() as conn:
            conn.execute(
                text("DELETE FROM template_fcp_mapping "
                     "WHERE fcp_id NOT IN ("
                     "SELECT fcp_id FROM fcp "
                     "WHERE fcp.connections<>0 OR fcp.reserved<>0) "
                     "AND tmpl_id=:tmpl_id AND fcp_id=:fcp_id"),
                records_to_delete)

    def delete_fcp_template(self, template_id):
        """Remove FCP Multipath Template record from template, template_sp_mapping,
        template_fcp_mapping and fcp tables."""
        with get_fcp_conn() as conn:
            if not self.fcp_template_exist_in_db(template_id):
                obj_desc = ("FCP Multipath Template {} ".format(template_id))
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc)
            inuse_fcp_devices = self.get_inuse_fcp_device_by_fcp_template(
                template_id)
            if inuse_fcp_devices:
                inuse_fcp_devices = utils.shrink_fcp_list(
                    [fcp['fcp_id'] for fcp in inuse_fcp_devices])
                detail = ("The FCP devices ({}) are allocated to virtual machines "
                          "by the FCP Multipath Template (id={}). "
                          "Deleting a FCP Multipath Template is not allowed "
                          "if there is any FCP device allocated from the template. "
                          "You must deallocate those FCP devices before deleting the template."
                          .format(inuse_fcp_devices, template_id))
                raise exception.SDKConflictError(modID=self._module_id, rs=22,
                                                 msg=detail)
            conn.execute(text("DELETE FROM template WHERE id=:id"),
                         {'id': template_id})
            conn.execute(
                text("DELETE FROM template_sp_mapping WHERE tmpl_id=:tmpl_id"),
                {'tmpl_id': template_id})
            conn.execute(
                text("DELETE FROM template_fcp_mapping WHERE tmpl_id=:tmpl_id"),
                {'tmpl_id': template_id})
            LOG.info("FCP Multipath Template with id %s is removed from "
                     "template, template_sp_mapping and "
                     "template_fcp_mapping tables" % template_id)

    def get_wwpn_phy_from_pchids(self, pchids):
        """Get wwpn_phy info of multiple pchids.

        :param pchids: (list) Physical channel ID list of FCP devices

        :return pchid_to_phy_wwpn_dict: (dict) PCHID as key, Physical WWPN as value
            for example:
            {
                '02E4': 'c05076de33002e41',
                '021C': 'c05076de330021c1'
            }
        """
        filter_sql, filter_params = _node_filter()
        pchid_to_phy_wwpn_dict = {}
        with get_fcp_conn() as conn:
            params = {'pchids': list(pchids), **filter_params}
            result = conn.execute(
                text("SELECT DISTINCT pchid, wwpn_phy "
                     "FROM fcp WHERE pchid IN :pchids" + filter_sql).bindparams(
                    bindparam('pchids', expanding=True)),
                params)

            raw = _fetchall(result)
        for item in raw:
            pchid_to_phy_wwpn_dict.update({item['pchid'].upper(): item['wwpn_phy']})
        return pchid_to_phy_wwpn_dict


class ImageDbOperator(object):

    def __init__(self):
        self._module_id = 'image'

    def image_add_record(self, imagename, imageosdistro, md5sum,
                         disk_size_units, image_size_in_bytes,
                         type, comments=None):
        # Images are globally shared across nodes ('GLOBAL' sentinel).
        _params = {'imagename': imagename, 'node_id': 'GLOBAL',
                   'imageosdistro': imageosdistro, 'md5sum': md5sum,
                   'disk_size_units': disk_size_units,
                   'image_size_in_bytes': image_size_in_bytes, 'type': type}
        if comments is not None:
            _params['comments'] = comments
            with get_image_conn() as conn:
                conn.execute(
                    text("INSERT INTO image"
                         " (imagename, compute_node_id, imageosdistro,"
                         "  md5sum, disk_size_units, image_size_in_bytes,"
                         "  type, comments)"
                         " VALUES (:imagename, :node_id, :imageosdistro,"
                         "  :md5sum, :disk_size_units, :image_size_in_bytes,"
                         "  :type, :comments)"),
                    _params)
        else:
            with get_image_conn() as conn:
                conn.execute(
                    text("INSERT INTO image"
                         " (imagename, compute_node_id, imageosdistro,"
                         "  md5sum, disk_size_units, image_size_in_bytes, type)"
                         " VALUES (:imagename, :node_id, :imageosdistro,"
                         "  :md5sum, :disk_size_units, :image_size_in_bytes, :type)"),
                    _params)

    def image_query_record(self, imagename=None):
        """Query the image record from database, if imagename is None, all
        of the image records will be returned, otherwise only the specified
        image record will be returned."""

        _cols = ("imagename, imageosdistro, md5sum, disk_size_units,"
                 " image_size_in_bytes, type, comments")
        filter_sql, filter_params = _node_filter()
        if imagename:
            params = {'imagename': imagename, **filter_params}
            with get_image_conn() as conn:
                result = conn.execute(
                    text("SELECT %s FROM image WHERE imagename=:imagename" % _cols
                         + filter_sql),
                    params)
                image_list = _fetchall(result)
            if not image_list:
                obj_desc = "Image with name: %s" % imagename
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                   modID=self._module_id)
        else:
            where = filter_sql.replace(" AND", " WHERE", 1)
            with get_image_conn() as conn:
                result = conn.execute(
                    text("SELECT %s FROM image" % _cols + where),
                    filter_params)
                image_list = _fetchall(result)

        return [dict(item._mapping) for item in image_list]

    def image_delete_record(self, imagename):
        """Delete the record of specified imagename from image table"""
        with get_image_conn() as conn:
            conn.execute(text("DELETE FROM image WHERE imagename=:imagename"),
                         {'imagename': imagename})


class GuestDbOperator(object):

    def __init__(self):
        self._module_id = 'guest'

    def _check_existence_by_id(self, guest_id, ignore=False):
        guest = self.get_guest_by_id(guest_id)
        if guest is None:
            msg = 'Guest with id: %s does not exist in DB.' % guest_id
            if ignore:
                # Just print a warning message
                LOG.info(msg)
            else:
                LOG.error(msg)
                obj_desc = "Guest with id: %s" % guest_id
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
        return guest

    def _check_existence_by_userid(self, userid, ignore=False):
        guest = self.get_guest_by_userid(userid)
        if guest is None:
            msg = 'Guest with userid: %s does not exist in DB.' % userid
            if ignore:
                # Just print a warning message
                LOG.info(msg)
            else:
                LOG.error(msg)
                obj_desc = "Guest with userid: %s" % userid
                raise exception.SDKObjectNotExistError(obj_desc=obj_desc,
                                                       modID=self._module_id)
        return guest

    def add_guest_registered(self, userid, meta, net_set,
                             comments=None):
        # Add guest which is migrated from other host or onboarded.
        guest_id = str(uuid.uuid4())
        with get_guest_conn() as conn:
            conn.execute(
                text("INSERT INTO guests"
                     " (id, userid, compute_node_id, metadata, net_set, comments)"
                     " VALUES (:id, :userid, :node_id, :meta, :net_set, :comments)"),
                {'id': guest_id, 'userid': userid,
                 'node_id': db_api.get_compute_node_id(),
                 'meta': meta, 'net_set': net_set, 'comments': comments})

    def add_guest(self, userid, meta='', comments=''):
        # Generate uuid automatically
        guest_id = str(uuid.uuid4())
        net_set = '0'
        with get_guest_conn() as conn:
            conn.execute(
                text("INSERT INTO guests"
                     " (id, userid, compute_node_id, metadata, net_set, comments)"
                     " VALUES (:id, :userid, :node_id, :meta, :net_set, :comments)"),
                {'id': guest_id, 'userid': userid,
                 'node_id': db_api.get_compute_node_id(),
                 'meta': meta, 'net_set': net_set, 'comments': comments})

    def delete_guest_by_id(self, guest_id):
        # First check whether the guest exist in db table
        guest = self._check_existence_by_id(guest_id, ignore=True)
        if guest is None:
            return
        # Update guest if exist
        with get_guest_conn() as conn:
            conn.execute(
                text("DELETE FROM guests WHERE id=:id"), {'id': guest_id})

    def delete_guest_by_userid(self, userid):
        # First check whether the guest exist in db table
        guest = self._check_existence_by_userid(userid, ignore=True)
        if guest is None:
            return
        with get_guest_conn() as conn:
            conn.execute(
                text("DELETE FROM guests WHERE userid=:userid"),
                {'userid': userid})

    def get_guest_metadata_with_userid(self, userid):
        filter_sql, filter_params = _node_filter()
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT metadata FROM guests WHERE userid=:userid" + filter_sql),
                {'userid': userid, **filter_params})
            guests = _fetchall(res)
        return guests

    def update_guest_by_id(self, uuid, userid=None, meta=None, net_set=None,
                           comments=None):
        if ((userid is None) and (meta is None) and
            (net_set is None) and (comments is None)):
            msg = ("Update guest with id: %s failed, no field "
                   "specified to be updated." % uuid)
            LOG.error(msg)
            raise exception.SDKInternalError(msg=msg, modID=self._module_id)

        # First check whether the guest exist in db table
        self._check_existence_by_id(uuid)
        # Start update
        sql_cmd = "UPDATE guests SET"
        params = {}
        if userid is not None:
            sql_cmd += " userid=:userid,"
            params['userid'] = userid
        if meta is not None:
            sql_cmd += " metadata=:meta,"
            params['meta'] = meta
        if net_set is not None:
            sql_cmd += " net_set=:net_set,"
            params['net_set'] = net_set
        if comments is not None:
            sql_cmd += " comments=:comments,"
            params['comments'] = comments

        # remove the tailing comma
        sql_cmd = sql_cmd.strip(',')
        # Add the id filter
        sql_cmd += " WHERE id=:uuid"
        params['uuid'] = uuid

        with get_guest_conn() as conn:
            conn.execute(text(sql_cmd), params)

    def update_guest_by_userid(self, userid, meta=None, net_set=None,
                               comments=None):
        userid = userid
        if (meta is None) and (net_set is None) and (comments is None):
            msg = ("Update guest with userid: %s failed, no field "
                   "specified to be updated." % userid)
            LOG.error(msg)
            raise exception.SDKInternalError(msg=msg, modID=self._module_id)

        # First check whether the guest exist in db table
        self._check_existence_by_userid(userid)
        # Start update
        sql_cmd = "UPDATE guests SET"
        params = {}
        if meta is not None:
            sql_cmd += " metadata=:meta,"
            params['meta'] = meta
        if net_set is not None:
            sql_cmd += " net_set=:net_set,"
            params['net_set'] = net_set
        if comments is not None:
            new_comments = json.dumps(comments)
            sql_cmd += " comments=:comments,"
            params['comments'] = new_comments

        # remove the tailing comma
        sql_cmd = sql_cmd.strip(',')
        # Add the userid filter
        sql_cmd += " WHERE userid=:userid"
        params['userid'] = userid

        with get_guest_conn() as conn:
            conn.execute(text(sql_cmd), params)

    def get_guest_list(self):
        filter_sql, filter_params = _node_filter()
        where = filter_sql.replace(" AND", " WHERE", 1)
        with get_guest_conn() as conn:
            res = conn.execute(text(
                "SELECT id, userid, metadata, net_set, comments FROM guests" + where),
                filter_params)
            guests = _fetchall(res)
        return guests

    def get_migrated_guest_list(self):
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT userid FROM guests "
                     "WHERE comments LIKE '%\"migrated\": 1%'"))
            guests = _fetchall(res)
        return guests

    def get_migrated_guest_info_list(self):
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT id, userid, metadata, net_set, comments FROM guests "
                     "WHERE comments LIKE '%\"migrated\": 1%'"))
            guests = _fetchall(res)
        return guests

    def get_comments_by_userid(self, userid):
        """ Get comments record.
        output should be like: {'k1': 'v1', 'k2': 'v2'}'
        """
        userid = userid
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT comments FROM guests WHERE userid=:userid"),
                {'userid': userid})
            result = _fetchall(res)
        comments = {}
        if result[0]['comments']:
            comments = json.loads(result[0]['comments'])
        return comments

    def get_metadata_by_userid(self, userid):
        """get metadata record.
        output should be like: "a=1,b=2,c=3"
        """
        userid = userid
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT id, userid, metadata, net_set, comments FROM guests"
                     " WHERE userid=:userid"),
                {'userid': userid})
            guest = _fetchall(res)

        if len(guest) == 1:
            return guest[0]['metadata']
        elif len(guest) == 0:
            LOG.debug("Guest with userid: %s not found from DB!" % userid)
            return ''
        else:
            msg = "Guest with userid: %s have multiple records!" % userid
            LOG.error(msg)
            raise exception.SDKInternalError(msg=msg, modID=self._module_id)

    def transfer_metadata_to_dict(self, meta):
        """transfer str to dict.
        output should be like: {'a':1, 'b':2, 'c':3}
        """
        dic = {}
        arr = meta.strip(' ,').split(',')
        for i in arr:
            temp = i.split('=')
            key = temp[0].strip()
            value = temp[1].strip()
            dic[key] = value
        return dic

    def get_guest_by_id(self, guest_id):
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT id, userid, metadata, net_set, comments FROM guests"
                     " WHERE id=:id"),
                {'id': guest_id})
            guest = _fetchall(res)
        # As id is the primary key, the filtered entry number should be 0 or 1
        if len(guest) == 1:
            return guest[0]
        elif len(guest) == 0:
            LOG.debug("Guest with id: %s not found from DB!" % guest_id)
            return None
        # Code shouldn't come here, just in case
        return None

    def get_guest_by_userid(self, userid):
        userid = userid
        filter_sql, filter_params = _node_filter()
        with get_guest_conn() as conn:
            res = conn.execute(
                text("SELECT id, userid, metadata, net_set, comments FROM guests"
                     " WHERE userid=:userid" + filter_sql),
                {'userid': userid, **filter_params})
            guest = _fetchall(res)
        # As id is the primary key, the filtered entry number should be 0 or 1
        if len(guest) == 1:
            return guest[0]
        elif len(guest) == 0:
            LOG.debug("Guest with userid: %s not found from DB!" % userid)
            return None
        # Code shouldn't come here, just in case
        return None
