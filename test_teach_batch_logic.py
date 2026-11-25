# -*- coding: utf-8 -*-
"""示教/批量 Tab 的入口合并与单一模型状态测试。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication


class TeachBatchLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'AURASCOPE_RECIPE_DIR': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        from teach_batch_tab import TeachBatchTab
        self.tab = TeachBatchTab()
        self.tab.resize(1200, 760)
        self.tab.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.tab.close()
        self.tab.deleteLater()
        self.app.processEvents()

    def test_quick_model_is_alias_of_single_active_model(self):
        model = {'name': '<快速示教>', 'type': 'taught'}
        self.tab.quick_model = model
        self.assertIs(self.tab.model, model)
        self.assertIs(self.tab.quick_model, model)
        self.tab.quick_model = None
        self.assertIsNone(self.tab.model)
        self.assertIsNone(self.tab.quick_model)

    def test_quick_teach_is_only_teaching_entry(self):
        self.assertEqual(self.tab._mode, 'batch')
        self.assertEqual(self.tab.btn_quick_teach.objectName(), 'PrimaryBtn')
        self.assertFalse(hasattr(self.tab, 'btn_mode_teach'))
        self.assertEqual(self.tab.left_stack.count(), 1)

    def test_quick_dialog_has_optional_scale_calibration(self):
        from unittest.mock import MagicMock
        import numpy as np
        from PyQt6.QtCore import QPointF
        from quick_teach_dialog import QuickTeachDialog
        gray = np.full((80, 120), 180, np.uint8)
        gray[20:50, 20:100] = 40
        dlg = QuickTeachDialog(gray, sample_name='s.png')
        try:
            self.assertTrue(hasattr(dlg, 'chk_scale'))
            self.assertFalse(dlg.btn_scale.isEnabled())
            fake = MagicMock()
            fake.exec.return_value = 1
            fake.doubleValue.return_value = 10.0
            with patch('quick_teach_dialog.QInputDialog', return_value=fake):
                dlg._on_calib_drawn(QPointF(0, 0), QPointF(100, 0))
            self.assertAlmostEqual(dlg.pixel_scale, 10.0)
            self.assertEqual(dlg.bar_info['length_px'], 100.0)
            self.assertIn('μm', dlg.lbl_scale.text())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_select_recipe_matches_data_then_text(self):
        combo = self.tab.combo_recipe
        combo.addItem('6', '6.taught.json')
        combo.addItem('CP-1', 'CP-1.taught.json')
        self.assertTrue(self.tab._select_recipe('6'))
        self.assertEqual(combo.currentData(), '6.taught.json')
        self.assertTrue(self.tab._select_recipe('CP-1'))
        self.assertEqual(combo.currentData(), 'CP-1.taught.json')
        self.assertFalse(self.tab._select_recipe('不存在'))


if __name__ == '__main__':
    unittest.main()
