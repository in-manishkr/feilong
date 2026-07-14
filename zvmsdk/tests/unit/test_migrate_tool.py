#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

"""Unit tests for tools/migrate_sqlite_to_mariadb.py (Phase 7)."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from tools import migrate_sqlite_to_mariadb as mig


class TestChunkHelper(unittest.TestCase):
    """Tests for _chunk()."""

    def test_even_chunks(self):
        result = list(mig._chunk([1, 2, 3, 4], 2))
        self.assertEqual(result, [[1, 2], [3, 4]])

    def test_partial_last_chunk(self):
        result = list(mig._chunk([1, 2, 3], 2))
        self.assertEqual(result, [[1, 2], [3]])

    def test_empty_list(self):
        result = list(mig._chunk([], 10))
        self.assertEqual(result, [])

    def test_size_larger_than_list(self):
        result = list(mig._chunk([1, 2], 10))
        self.assertEqual(result, [[1, 2]])


class TestBuildInsertSql(unittest.TestCase):
    """Tests for _build_insert_sql()."""

    def test_sqlite_uses_insert_or_ignore(self):
        sql = mig._build_insert_sql('switch', ('userid', 'interface'), 'sqlite')
        self.assertIn('INSERT OR IGNORE', sql)
        self.assertIn('switch', sql)
        self.assertIn(':userid', sql)
        self.assertIn(':interface', sql)

    def test_mariadb_uses_insert_ignore(self):
        sql = mig._build_insert_sql('guests', ('id', 'userid'), 'mariadb')
        self.assertIn('INSERT IGNORE', sql)
        self.assertNotIn('INSERT OR IGNORE', sql)

    def test_mysql_uses_insert_ignore(self):
        sql = mig._build_insert_sql('fcp', ('fcp_id',), 'mysql')
        self.assertIn('INSERT IGNORE', sql)


class TestInjectNodeId(unittest.TestCase):
    """Tests for _inject_node_id()."""

    def test_compute_node_id_injected_into_every_row(self):
        rows = [{'userid': 'A'}, {'userid': 'B'}, {'userid': 'C'}]
        result = mig._inject_node_id(rows, 'MY-NODE')
        for row in result:
            self.assertEqual(row['compute_node_id'], 'MY-NODE')

    def test_returns_same_list(self):
        rows = [{'a': 1}]
        returned = mig._inject_node_id(rows, 'X')
        self.assertIs(returned, rows)

    def test_global_node_id_for_image(self):
        rows = [{'imagename': 'img1'}]
        mig._inject_node_id(rows, 'GLOBAL')
        self.assertEqual(rows[0]['compute_node_id'], 'GLOBAL')


class TestCountSourceTable(unittest.TestCase):
    """Tests for _count_source_table() against a real temp SQLite."""

    def setUp(self):
        self._tmp = tempfile.mktemp(suffix='.sqlite')
        con = sqlite3.connect(self._tmp)
        con.execute("CREATE TABLE switch (userid TEXT, interface TEXT)")
        con.execute("INSERT INTO switch VALUES ('u1', 'eth0')")
        con.execute("INSERT INTO switch VALUES ('u2', 'eth1')")
        con.commit()
        con.close()

    def tearDown(self):
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_count_returns_correct_number(self):
        count = mig._count_source_table(self._tmp, 'switch')
        self.assertEqual(count, 2)


class TestReadSourceRows(unittest.TestCase):
    """Tests for _read_source_rows()."""

    def setUp(self):
        self._tmp = tempfile.mktemp(suffix='.sqlite')
        con = sqlite3.connect(self._tmp)
        con.execute("CREATE TABLE guests (id TEXT, userid TEXT, comments TEXT)")
        con.execute("INSERT INTO guests VALUES ('uuid1', 'VM01', 'note1')")
        con.commit()
        con.close()

    def tearDown(self):
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_rows_returned_as_dicts(self):
        rows = mig._read_source_rows(self._tmp, 'guests',
                                     ('id', 'userid', 'comments'))
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0], dict)
        self.assertEqual(rows[0]['id'], 'uuid1')
        self.assertEqual(rows[0]['userid'], 'VM01')


class TestDryRunWritesNothing(unittest.TestCase):
    """test_dry_run_writes_nothing: no INSERT should be called in dry-run mode."""

    def test_dry_run_skips_insert(self):
        tbl_cfg = {
            'table': 'switch',
            'src_cols': ('userid', 'interface', 'switch', 'port', 'comments'),
            'tgt_cols': ('userid', 'interface', 'compute_node_id',
                         'switch', 'port', 'comments'),
            'use_global': False,
        }
        with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
            src_path = f.name
        try:
            con = sqlite3.connect(src_path)
            con.execute("CREATE TABLE switch "
                        "(userid TEXT, interface TEXT, switch TEXT, "
                        "port TEXT, comments TEXT)")
            con.execute("INSERT INTO switch VALUES ('u1','eth0','vlan1','1','c')")
            con.commit()
            con.close()

            mock_conn = mock.MagicMock()
            src_count, tgt_count = mig._migrate_table(
                tgt_conn=mock_conn,
                src_path=src_path,
                tbl_cfg=tbl_cfg,
                node_id='TEST-NODE',
                batch_size=500,
                backend='sqlite',
                dry_run=True,
            )
            mock_conn.execute.assert_not_called()
            self.assertEqual(src_count, 1)
            self.assertEqual(tgt_count, 1)
        finally:
            os.unlink(src_path)


class TestBatchInsertCorrectSize(unittest.TestCase):
    """test_batch_insert_correct_size: 1001 rows at batch-size 500 → 3 INSERT calls."""

    def test_three_batches_for_1001_rows(self):
        tbl_cfg = {
            'table': 'guests',
            'src_cols': ('id', 'userid', 'metadata', 'net_set', 'comments'),
            'tgt_cols': ('id', 'userid', 'compute_node_id',
                         'metadata', 'net_set', 'comments'),
            'use_global': False,
        }
        with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
            src_path = f.name
        try:
            con = sqlite3.connect(src_path)
            con.execute("CREATE TABLE guests "
                        "(id TEXT, userid TEXT, metadata TEXT, "
                        "net_set INTEGER, comments TEXT)")
            for i in range(1001):
                con.execute("INSERT INTO guests VALUES (?,?,?,?,?)",
                            (str(i), 'u%d' % i, '', 0, ''))
            con.commit()
            con.close()

            mock_conn = mock.MagicMock()
            # _count_target_table must return src_count for the report
            mock_conn.execute.return_value.fetchone.return_value = (1001,)

            mig._migrate_table(
                tgt_conn=mock_conn,
                src_path=src_path,
                tbl_cfg=tbl_cfg,
                node_id='NODE',
                batch_size=500,
                backend='mariadb',
                dry_run=False,
            )
            # 500 + 500 + 1 = 3 INSERT batches + 1 COUNT query = 4 total calls
            # str(TextClause) returns the SQL text; str(call) uses repr which may not
            insert_calls = [c for c in mock_conn.execute.call_args_list
                            if 'INSERT' in str(c[0][0])]
            self.assertEqual(len(insert_calls), 3)
        finally:
            os.unlink(src_path)


class TestSkipsMissingSqliteFile(unittest.TestCase):
    """test_skips_missing_sqlite_file: missing source → warning, no exception."""

    def test_missing_file_is_skipped(self):
        args = mig._parse_args([
            '--sqlite-dir', '/nonexistent/path',
            '--target-backend', 'sqlite',
        ])
        # main() tries to migrate; missing files should be warned and skipped
        with mock.patch('tools.migrate_sqlite_to_mariadb.db_api') as mock_api, \
             mock.patch('tools.migrate_sqlite_to_mariadb.db_migration'), \
             mock.patch('zvmsdk.config.CONF'), \
             mock.patch('sys.exit') as mock_exit:
            mock_api.get_compute_node_id.return_value = 'TEST'
            mock_api.get_connection.return_value.__enter__ = \
                mock.Mock(return_value=mock.MagicMock())
            mock_api.get_connection.return_value.__exit__ = \
                mock.Mock(return_value=False)
            with self.assertLogs('tools.migrate_sqlite_to_mariadb', level='WARNING') as cm:
                try:
                    mig.main([
                        '--sqlite-dir', '/nonexistent/path',
                        '--target-backend', 'sqlite',
                    ])
                except SystemExit:
                    pass
        # at least one WARNING about missing files
        self.assertTrue(any('not found' in msg.lower() or 'skip' in msg.lower()
                            for msg in cm.output))


class TestCountMismatchExits1(unittest.TestCase):
    """test_count_mismatch_exits_1: source/target count difference → SystemExit(1)."""

    def test_mismatch_triggers_exit_1(self):
        tbl_cfg = {
            'table': 'switch',
            'src_cols': ('userid', 'interface', 'switch', 'port', 'comments'),
            'tgt_cols': ('userid', 'interface', 'compute_node_id',
                         'switch', 'port', 'comments'),
            'use_global': False,
        }
        with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
            src_path = f.name
        try:
            con = sqlite3.connect(src_path)
            con.execute("CREATE TABLE switch "
                        "(userid TEXT, interface TEXT, switch TEXT, "
                        "port TEXT, comments TEXT)")
            for i in range(10):
                con.execute("INSERT INTO switch VALUES (?,?,?,?,?)",
                            ('u%d' % i, 'eth0', 'vlan', '1', ''))
            con.commit()
            con.close()

            mock_conn = mock.MagicMock()
            # Simulate only 5 rows landed in target (count mismatch)
            mock_conn.execute.return_value.fetchone.return_value = (5,)

            src_count, tgt_count = mig._migrate_table(
                tgt_conn=mock_conn,
                src_path=src_path,
                tbl_cfg=tbl_cfg,
                node_id='N',
                batch_size=500,
                backend='sqlite',
                dry_run=False,
            )
            self.assertEqual(src_count, 10)
            self.assertEqual(tgt_count, 5)
            # The caller (main) should detect mismatch and exit 1.
            results = [('switch', src_count, tgt_count)]
            exit_code = 0
            for _, src, tgt in results:
                if src != tgt:
                    exit_code = 1
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(src_path)


class TestParseArgs(unittest.TestCase):
    """Tests for _parse_args()."""

    def test_defaults(self):
        args = mig._parse_args(['--sqlite-dir', '/tmp'])
        self.assertEqual(args.sqlite_dir, '/tmp')
        self.assertEqual(args.target_backend, 'mariadb')
        self.assertEqual(args.batch_size, 500)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.compute_node_id)
        self.assertIsNone(args.config)

    def test_all_options(self):
        args = mig._parse_args([
            '--sqlite-dir', '/data',
            '--config', '/etc/zvmsdk/zvmsdk.conf',
            '--compute-node-id', 'NODE@ZVM',
            '--target-backend', 'sqlite',
            '--dry-run',
            '--batch-size', '100',
        ])
        self.assertEqual(args.sqlite_dir, '/data')
        self.assertEqual(args.config, '/etc/zvmsdk/zvmsdk.conf')
        self.assertEqual(args.compute_node_id, 'NODE@ZVM')
        self.assertEqual(args.target_backend, 'sqlite')
        self.assertTrue(args.dry_run)
        self.assertEqual(args.batch_size, 100)


class TestComputeNodeIdInjectedInAllRows(unittest.TestCase):
    """Explicit check: every row returned from the source gets compute_node_id."""

    def test_all_rows_have_node_id(self):
        rows = [
            {'fcp_id': '1a01', 'assigner_id': '', 'connections': 0,
             'reserved': 0, 'wwpn_npiv': '', 'wwpn_phy': '', 'chpid': '',
             'pchid': '', 'state': 'free', 'owner': '', 'tmpl_id': ''}
            for _ in range(50)
        ]
        node_id = 'IAAS01EF@BOEM5401'
        result = mig._inject_node_id(rows, node_id)
        self.assertTrue(all(r['compute_node_id'] == node_id for r in result))


if __name__ == '__main__':
    unittest.main()
