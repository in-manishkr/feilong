#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

import unittest

from zvmsdk.db import models


class TestModelMetadata(unittest.TestCase):
    """Verify that all 8 table definitions are present in the metadata."""

    def test_all_eight_tables_in_metadata(self):
        expected = {
            'compute_nodes',
            'guests',
            'switch',
            'image',
            'fcp',
            'template',
            'template_sp_mapping',
            'template_fcp_mapping',
        }
        self.assertEqual(expected, set(models.metadata.tables.keys()))

    def test_guests_has_compute_node_id_column(self):
        self.assertIn('compute_node_id', models.guests.c)

    def test_image_pk_includes_compute_node_id(self):
        pk_cols = {c.name for c in models.image.primary_key.columns}
        self.assertIn('imagename', pk_cols)
        self.assertIn('compute_node_id', pk_cols)

    def test_template_fcp_mapping_has_two_fks(self):
        fk_constraints = [
            c for c in models.template_fcp_mapping.constraints
            if c.__class__.__name__ == 'ForeignKeyConstraint'
        ]
        self.assertEqual(2, len(fk_constraints),
                         "template_fcp_mapping must have exactly 2 FKs "
                         "(to template and to fcp)")

    def test_template_sp_mapping_has_fk_to_template(self):
        fk_constraints = [
            c for c in models.template_sp_mapping.constraints
            if c.__class__.__name__ == 'ForeignKeyConstraint'
        ]
        self.assertEqual(1, len(fk_constraints))
        referenced_tables = {
            fk.column.table.name
            for fk_c in fk_constraints
            for fk in fk_c.elements
        }
        self.assertIn('template', referenced_tables)


if __name__ == '__main__':
    unittest.main()
