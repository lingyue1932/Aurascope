"""剪切力计算器的三种面积输入（矩形 / 圆形 / 已知面积）单元测试。"""

import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

from shear_tab import ShearTab, MM2_PER_IN2, FORCE_FACTOR

_app = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])


class ShearAreaInputTests(unittest.TestCase):
    def setUp(self):
        self.tab = ShearTab()

    def tearDown(self):
        self.tab.deleteLater()

    def _force_1x(self):
        g_lb, _n_lb = self.tab.result_widgets[1.0]
        return float(g_lb.text().replace(' g', ''))

    def test_rect_mode(self):
        self.tab.cbo_shape.setCurrentIndex(0)
        self.tab.inp_len.setText('2')
        self.tab.inp_wid.setText('1.5')
        self.assertAlmostEqual(self.tab._last_area_mm2, 3.0, places=6)
        expected = 3.0 / MM2_PER_IN2 * FORCE_FACTOR * 1000
        self.assertAlmostEqual(self._force_1x(), expected, places=1)

    def test_circle_mode_uses_diameter(self):
        self.tab.cbo_shape.setCurrentIndex(1)
        self.tab.inp_dia.setText('2')
        expected_area = math.pi * 4 / 4.0
        self.assertAlmostEqual(self.tab._last_area_mm2, expected_area, places=6)
        self.assertIn('平方毫米', self.tab.lbl_area_mm2.text())

    def test_direct_area_mode(self):
        self.tab.cbo_shape.setCurrentIndex(2)
        self.tab.inp_area.setText('3')
        self.assertAlmostEqual(self.tab._last_area_mm2, 3.0, places=6)
        expected = 3.0 / MM2_PER_IN2 * FORCE_FACTOR * 1000
        self.assertAlmostEqual(self._force_1x(), expected, places=1)

    def test_modes_are_exclusive(self):
        # 矩形填了值，切到圆形但直径为空 → 结果清零，不会沿用矩形面积
        self.tab.cbo_shape.setCurrentIndex(0)
        self.tab.inp_len.setText('2')
        self.tab.inp_wid.setText('1.5')
        self.assertGreater(self.tab._last_area_mm2, 0)
        self.tab.cbo_shape.setCurrentIndex(1)
        self.assertEqual(self.tab._last_area_mm2, 0.0)
        self.assertTrue(self.tab.row_circle.isVisibleTo(self.tab))

    def test_reset_clears_all_modes(self):
        self.tab.inp_len.setText('10')
        self.tab.inp_wid.setText('10')
        self.tab.inp_dia.setText('8')
        self.tab.inp_area.setText('50')
        self.tab.reset()
        self.assertEqual(self.tab.inp_len.text(), '')
        self.assertEqual(self.tab.inp_dia.text(), '')
        self.assertEqual(self.tab.inp_area.text(), '')
        self.assertEqual(self.tab._last_area_mm2, 0.0)

    def test_area_over_limit_marks_not_applicable(self):
        self.tab.cbo_shape.setCurrentIndex(2)
        self.tab.inp_area.setText('9999')
        g_lb, _n_lb = self.tab.result_widgets[1.0]
        self.assertEqual(g_lb.text(), '不适用')


if __name__ == '__main__':
    unittest.main()
