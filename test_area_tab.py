"""缺陷面积算法与 UI 验收：原图像素、Qt 交互、标定及 CSV。"""

import unittest

import numpy as np

import image


class DetectDefectsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(image, 'detect_defects', None)),
                        '缺少 image.detect_defects 函数')

    def test_rectangle_exact_area_schema_and_full_image_coordinates(self):
        gray = np.zeros((40, 60), dtype=np.uint8)
        gray[7:17, 13:33] = 255
        objects = image.detect_defects(gray, 127)
        self.assertIsInstance(objects, list)
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertEqual(set(obj), {'id', 'area_px', 'cx', 'cy',
                                    'rect', 'points', 'mask'})
        self.assertEqual(obj['id'], 1)
        self.assertIs(type(obj['id']), int)
        self.assertEqual(obj['area_px'], 200)
        self.assertIs(type(obj['area_px']), int)
        self.assertEqual(obj['rect'], (13, 7, 20, 10))
        self.assertIs(type(obj['rect']), tuple)
        for value in obj['rect']:
            self.assertIs(type(value), int)
        self.assertEqual((obj['cx'], obj['cy']), (22.5, 11.5))
        self.assertIs(type(obj['cx']), float)
        self.assertIs(type(obj['cy']), float)
        self.assertIsInstance(obj['points'], list)
        self.assertEqual({tuple(p) for p in obj['points']},
                         {(13, 7), (32, 7), (32, 16), (13, 16)})
        self.assertEqual(obj['mask'].dtype, np.uint8)
        self.assertEqual(obj['mask'].shape, (10, 20))
        np.testing.assert_array_equal(obj['mask'], np.full((10, 20), 255, np.uint8))

    def test_one_pixel_wide_lines_count_all_30_pixels(self):
        for shape, rect, points, center in (
                ((1, 30), (0, 0, 30, 1), {(0, 0), (29, 0)}, (14.5, 0.0)),
                ((30, 1), (0, 0, 1, 30), {(0, 0), (0, 29)}, (0.0, 14.5))):
            with self.subTest(shape=shape):
                objects = image.detect_defects(np.full(shape, 255, np.uint8), 127)
                self.assertEqual(len(objects), 1)
                obj = objects[0]
                self.assertEqual(obj['area_px'], 30)
                self.assertEqual(obj['rect'], rect)
                self.assertEqual((obj['cx'], obj['cy']), center)
                self.assertEqual({tuple(p) for p in obj['points']}, points)
                np.testing.assert_array_equal(obj['mask'], np.full(shape, 255, np.uint8))

    def test_single_pixel_and_one_by_one_image_are_valid(self):
        for shape, x, y in (((1, 1), 0, 0), ((12, 16), 11, 7)):
            with self.subTest(shape=shape):
                gray = np.zeros(shape, np.uint8)
                gray[y, x] = 255
                objects = image.detect_defects(gray, 127)
                self.assertEqual(len(objects), 1)
                obj = objects[0]
                self.assertEqual(obj['area_px'], 1)
                self.assertEqual(obj['rect'], (x, y, 1, 1))
                self.assertEqual((obj['cx'], obj['cy']), (float(x), float(y)))
                self.assertEqual(obj['points'], [[x, y]])
                np.testing.assert_array_equal(obj['mask'], np.array([[255]], np.uint8))

    def test_hole_is_not_filled_or_counted(self):
        gray = np.zeros((25, 30), np.uint8)
        gray[5:15, 8:18] = 255
        gray[7:13, 10:16] = 0
        objects = image.detect_defects(gray, 127)
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertEqual(obj['area_px'], 64)
        self.assertEqual(obj['rect'], (8, 5, 10, 10))
        self.assertEqual((obj['cx'], obj['cy']), (12.5, 9.5))
        self.assertEqual({tuple(p) for p in obj['points']},
                         {(8, 5), (17, 5), (17, 14), (8, 14)})
        np.testing.assert_array_equal(obj['mask'], gray[5:15, 8:18])
        self.assertEqual(np.count_nonzero(obj['mask']), 64)
        self.assertFalse(obj['mask'][2:8, 2:8].any())

    def test_nested_component_does_not_leak_into_outer_component_mask(self):
        gray = np.zeros((15, 17), np.uint8)
        gray[3:12, 4:13] = 255
        gray[4:11, 5:12] = 0
        gray[7, 8] = 255
        objects = image.detect_defects(gray, 127)
        self.assertEqual(len(objects), 2)
        self.assertEqual([obj['id'] for obj in objects], [1, 2])
        ring, island = sorted(objects, key=lambda obj: -obj['area_px'])
        self.assertEqual((ring['area_px'], island['area_px']), (32, 1))
        self.assertEqual(ring['rect'], (4, 3, 9, 9))
        self.assertEqual(ring['mask'].shape, (9, 9))
        self.assertFalse(ring['mask'][1:8, 1:8].any())
        self.assertEqual(np.count_nonzero(ring['mask']), 32)
        self.assertEqual(island['rect'], (8, 7, 1, 1))
        self.assertEqual(island['points'], [[8, 7]])
        np.testing.assert_array_equal(island['mask'], np.array([[255]], np.uint8))

    def test_diagonal_pixels_use_eight_connectivity(self):
        gray = np.zeros((10, 12), np.uint8)
        gray[3, 5] = gray[4, 6] = gray[5, 7] = 255
        objects = image.detect_defects(gray, 127)
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertEqual(obj['area_px'], 3)
        self.assertEqual(obj['rect'], (5, 3, 3, 3))
        self.assertEqual((obj['cx'], obj['cy']), (6.0, 4.0))
        np.testing.assert_array_equal(obj['mask'], np.eye(3, dtype=np.uint8) * 255)

    def test_centroid_uses_pixel_mass_not_bbox_center(self):
        gray = np.zeros((10, 12), np.uint8)
        gray[3, 5:7] = 255
        gray[4, 5] = 255
        obj = image.detect_defects(gray, 127)[0]
        self.assertEqual(obj['area_px'], 3)
        self.assertAlmostEqual(obj['cx'], 5 + 1 / 3)
        self.assertAlmostEqual(obj['cy'], 3 + 1 / 3)

    def test_empty_foreground_and_empty_roi_return_empty_list(self):
        for bright, value in ((True, 0), (False, 255)):
            with self.subTest(bright=bright):
                gray = np.full((6, 8), value, np.uint8)
                self.assertEqual(image.detect_defects(gray, 127, bright=bright), [])
                foreground = np.full((6, 8), 255 - value, np.uint8)
                self.assertEqual(image.detect_defects(
                    foreground, 127, bright=bright,
                    roi_mask=np.zeros((6, 8), np.uint8)), [])

    def test_threshold_equality_belongs_only_to_dark_foreground(self):
        gray = np.array([[99, 100, 101]], np.uint8)
        bright = image.detect_defects(gray, 100, bright=True)
        dark = image.detect_defects(gray, 100, bright=False)
        self.assertEqual(len(bright), 1)
        self.assertEqual(len(dark), 1)
        self.assertEqual((bright[0]['area_px'], bright[0]['rect']), (1, (2, 0, 1, 1)))
        self.assertEqual((dark[0]['area_px'], dark[0]['rect']), (2, (0, 0, 2, 1)))

    def test_threshold_endpoints_zero_and_255(self):
        gray = np.array([[0, 1, 254, 255]], np.uint8)
        for threshold, bright, areas in ((0, True, [3]), (0, False, [1]),
                                         (255, True, []), (255, False, [4])):
            with self.subTest(threshold=threshold, bright=bright):
                objects = image.detect_defects(gray, threshold, bright=bright)
                self.assertEqual([obj['area_px'] for obj in objects], areas)

    def test_polarity_reversal_detects_background_not_empty_result(self):
        for bright in (True, False):
            with self.subTest(bright=bright):
                gray = np.full((12, 14), 0 if bright else 255, np.uint8)
                gray[4:7, 5:9] = 255 if bright else 0
                block = image.detect_defects(gray, 127, bright=bright)
                background = image.detect_defects(gray, 127, bright=not bright)
                self.assertEqual(len(block), 1)
                self.assertEqual(len(background), 1)
                self.assertEqual(block[0]['area_px'], 12)
                self.assertEqual(background[0]['area_px'], 156)
                self.assertEqual(background[0]['rect'], (0, 0, 14, 12))
                self.assertFalse(background[0]['mask'][4:7, 5:9].any())

    def test_rectangle_roi_clips_pixels_and_excludes_outside_components(self):
        for bright in (True, False):
            with self.subTest(bright=bright):
                gray = np.zeros((35, 45), np.uint8)
                gray[5:15, 6:26] = 255
                gray[25:28, 35:38] = 255
                if not bright:
                    gray = 255 - gray
                roi = np.zeros_like(gray)
                roi[7:13, 10:20] = 255
                objects = image.detect_defects(gray, 127, bright=bright, roi_mask=roi)
                self.assertEqual(len(objects), 1)
                obj = objects[0]
                self.assertEqual(obj['area_px'], 60)
                self.assertEqual(obj['rect'], (10, 7, 10, 6))
                self.assertEqual((obj['cx'], obj['cy']), (14.5, 9.5))
                np.testing.assert_array_equal(obj['mask'], np.full((6, 10), 255, np.uint8))

    def test_polygon_roi_preserves_triangle_shape(self):
        gray = np.zeros((16, 18), np.uint8)
        gray[3:9, 4:10] = 255
        gray[12:14, 14:16] = 255
        roi = image.polygon_to_mask([(4, 3), (9, 3), (4, 8)], gray.shape)
        objects = image.detect_defects(gray, 127, roi_mask=roi)
        self.assertEqual(len(objects), 1)
        obj = objects[0]
        self.assertEqual(obj['area_px'], 21)
        self.assertEqual(obj['rect'], (4, 3, 6, 6))
        self.assertAlmostEqual(obj['cx'], 4 + 5 / 3)
        self.assertAlmostEqual(obj['cy'], 3 + 5 / 3)
        self.assertEqual({tuple(p) for p in obj['points']}, {(4, 3), (9, 3), (4, 8)})
        expected = np.array([[255] * n + [0] * (6 - n) for n in range(6, 0, -1)], np.uint8)
        np.testing.assert_array_equal(obj['mask'], expected)

    def test_min_area_is_inclusive_and_ids_restart_after_filtering(self):
        gray = np.zeros((35, 45), np.uint8)
        gray[1:3, 1:3] = 255
        gray[10:20, 10:30] = 255
        for minimum, areas in ((0, [4, 200]), (4, [4, 200]), (4.5, [200]),
                               (50, [200]), (200, [200]), (201, [])):
            with self.subTest(min_area=minimum):
                objects = image.detect_defects(gray, 127, min_area=minimum)
                self.assertEqual(sorted(obj['area_px'] for obj in objects), areas)
                self.assertEqual([obj['id'] for obj in objects], list(range(1, len(areas) + 1)))

    def test_inputs_are_unchanged_and_output_masks_are_independent(self):
        gray = np.zeros((15, 18), np.uint8)
        gray[4:10, 6:12] = 255
        roi = np.zeros_like(gray)
        roi[2:12, 3:15] = 255
        before_gray, before_roi = gray.copy(), roi.copy()
        for bright in (True, False):
            with self.subTest(bright=bright):
                objects = image.detect_defects(gray, 127, bright=bright, roi_mask=roi)
                self.assertEqual(len(objects), 1)
                self.assertFalse(np.shares_memory(objects[0]['mask'], gray))
                self.assertFalse(np.shares_memory(objects[0]['mask'], roi))
                objects[0]['mask'][:] = 0
                np.testing.assert_array_equal(gray, before_gray)
                np.testing.assert_array_equal(roi, before_roi)

    def test_read_only_noncontiguous_inputs_are_supported(self):
        gray = np.zeros((20, 30), np.uint8)[::-2, ::2]
        gray[2:6, 3:8] = 255
        roi = np.full((20, 30), 255, np.uint8)[::-2, ::2]
        gray.setflags(write=False)
        roi.setflags(write=False)
        objects = image.detect_defects(gray, 127, roi_mask=roi)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]['area_px'], 20)
        self.assertEqual(objects[0]['rect'], (3, 2, 5, 4))
        np.testing.assert_array_equal(objects[0]['mask'], np.full((4, 5), 255, np.uint8))

    def test_invalid_gray_raises_value_error(self):
        invalid = (None, [[0]], np.array(0, np.uint8), np.zeros(3, np.uint8),
                   np.zeros((2, 3, 1), np.uint8), np.zeros((0, 3), np.uint8),
                   np.zeros((3, 0), np.uint8), np.zeros((2, 3), np.uint16),
                   np.zeros((2, 3), np.float32), np.zeros((2, 3), bool))
        for gray in invalid:
            with self.subTest(gray=repr(gray)):
                with self.assertRaises(ValueError):
                    image.detect_defects(gray, 127)

    def test_invalid_roi_raises_value_error(self):
        gray = np.zeros((2, 3), np.uint8)
        invalid = ([[0, 0, 0], [0, 0, 0]], np.zeros((3, 2), np.uint8),
                   np.zeros((2, 3, 1), np.uint8), np.zeros((2, 3), bool),
                   np.zeros((2, 3), np.float32), np.zeros((2, 3), np.uint16),
                   np.full((2, 3), 1, np.uint8), np.full((2, 3), 254, np.uint8))
        for roi in invalid:
            with self.subTest(roi=repr(roi)):
                with self.assertRaises(ValueError):
                    image.detect_defects(gray, 127, roi_mask=roi)

    def test_invalid_threshold_raises_value_error(self):
        gray = np.zeros((2, 3), np.uint8)
        for threshold in (-1, 256, float('nan'), float('inf'), -float('inf'),
                          None, '127', True, 1j, [127], np.array([127])):
            with self.subTest(threshold=repr(threshold)):
                with self.assertRaises(ValueError):
                    image.detect_defects(gray, threshold)

    def test_invalid_bright_raises_value_error(self):
        gray = np.zeros((2, 3), np.uint8)
        for bright in (None, 0, 1, 'False', [], np.array([True])):
            with self.subTest(bright=repr(bright)):
                with self.assertRaises(ValueError):
                    image.detect_defects(gray, 127, bright=bright)

    def test_invalid_min_area_raises_value_error(self):
        gray = np.zeros((2, 3), np.uint8)
        for minimum in (-1, float('nan'), float('inf'), -float('inf'),
                        None, '1', True, 1j, [1], np.array([1])):
            with self.subTest(min_area=repr(minimum)):
                with self.assertRaises(ValueError):
                    image.detect_defects(gray, 127, min_area=minimum)

    def test_numpy_scalar_and_fractional_threshold_inputs(self):
        gray = np.array([[99, 100, 101]], np.uint8)
        for threshold in (np.int64(100), np.float32(100.5)):
            with self.subTest(threshold=threshold):
                objects = image.detect_defects(gray, threshold, bright=np.bool_(False),
                                               min_area=np.int64(2))
                self.assertEqual(len(objects), 1)
                self.assertEqual(objects[0]['area_px'], 2)
                self.assertEqual(objects[0]['rect'], (0, 0, 2, 1))


    def test_detect_defects_pumps_events_during_long_runs(self):
        from unittest.mock import patch
        gray = np.zeros((30, 1500), np.uint8)
        for index in range(120):
            gray[2:8, index * 12:(index * 12) + 5] = 255
        with patch('image._pump_events', wraps=image._pump_events) as pump:
            objects = image.detect_defects(gray, 127)
        self.assertEqual(len(objects), 120)
        self.assertGreater(pump.call_count, 0, '长检测必须周期性让出事件循环')


# UI tests deliberately use the real detector and Qt event loop. All fixtures
# and recipe discovery for the main-window smoke test are isolated in this repo.
import csv
import importlib.util
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import cv2
import tifffile
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QAbstractItemView


class AreaFormattingTests(unittest.TestCase):
    def test_real_area_and_bidirectional_units(self):
        self.assertIsNotNone(importlib.util.find_spec('area_tab'), '缺少缺陷面积 UI 模块')
        from area_tab import compute_real_area, fmt_area
        self.assertIsNone(compute_real_area(200, None))
        self.assertEqual(compute_real_area(200, .5), 50.)
        for value, unit, expected in (
                (2e6, 'µm', '2.00 mm²'), (1e6, 'nm', '1.00 µm²'),
                (5e-5, 'mm', '50.00 µm²'), (0, 'µm', '0.00 µm²'),
                (-1, 'mm', '0.00 mm²'), (1e6, 'mm', '10000.00 cm²'),
                (1e6, 'cm', '100.00 m²'), (.0001, 'm', '1.00 cm²'),
                (.0001, 'cm', '0.01 mm²'), (.0001, 'µm', '100.00 nm²')):
            with self.subTest(value=value, unit=unit):
                self.assertEqual(fmt_area(value, unit), expected)


class AreaUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('area_tab'), '缺少缺陷面积 UI 模块')
        from area_tab import DefectAreaTab
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tab = DefectAreaTab()
        self.tab.resize(1000, 600)
        self.tab.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)
        self.gray = np.zeros((160, 240), np.uint8)
        self.gray[60:70, 100:120] = 200

    def dispose(self):
        self.tab._detect_timer.stop()
        self.tab.close()
        self.tab.deleteLater()
        self.app.processEvents()

    def load(self, array=None, name='中文图片.png'):
        path = self.root / name
        array = self.gray if array is None else array
        if path.suffix.lower() in ('.tif', '.tiff'):
            tifffile.imwrite(path, array)
        else:
            cv2.imencode(path.suffix, array)[1].tofile(str(path))
        self.assertTrue(self.tab.load_image(str(path)))
        return path

    def point(self, x, y):
        return self.tab.canvas.img_to_widget(QPointF(x, y)).toPoint()

    def click(self, x, y):
        QTest.mouseClick(self.tab.canvas, Qt.MouseButton.LeftButton, pos=self.point(x, y))

    def grab_text(self):
        canvas = self.tab.canvas
        drawn_text = []
        original_text = canvas._text

        def record_text(painter, pos, text):
            drawn_text.append(text)
            original_text(painter, pos, text)

        canvas._text = record_text
        try:
            canvas.grab()
        finally:
            canvas._text = original_text
        return drawn_text

    def drag(self, x1, y1, x2, y2, button=Qt.MouseButton.LeftButton):
        canvas = self.tab.canvas
        QTest.mousePress(canvas, button, pos=self.point(x1, y1))
        QTest.mouseMove(canvas, self.point(x2, y2))
        QTest.mouseRelease(canvas, button, pos=self.point(x2, y2))

    def total(self):
        return sum(o['area_px'] for o in self.tab.objects)

    def detect(self, rect=None):
        if rect is None:
            height, width = self.tab.gray.shape
            rect = (0, 0, width, height)
        self.assertTrue(self.tab.set_roi_rect(rect))
        self.assertTrue(self.tab._analysis_active, '画完 ROI 应立即自动检测')

    def drain_batch(self):
        for _ in range(200):
            if not self.tab._batch_queue:
                self.app.processEvents()
                return
            QTest.qWait(10)
        self.fail('批量 ROI 检测未在 2 秒内完成')

    def empty_active_roi(self):
        if self.tab.rois:
            self.tab.clear_roi()
        self.assertTrue(self.tab.set_roi_rect((90, 50, 40, 40)))
        self.assertEqual(self.total(), 200)
        self.assertTrue(self.tab.delete_at(110, 65))
        self.assertEqual(self.total(), 0)

    def test_import_roi_auto_detects_and_button_stops_or_rejects(self):
        self.assertTrue(hasattr(self.tab, 'btn_detect'), '需要明确的开始检测按钮')
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.load()
            self.assertEqual(detector.call_count, 0)
            self.assertEqual(self.tab.objects, [])
            self.assertEqual(self.tab.canvas.objects, [])
            self.assertTrue(self.tab.set_roi_rect((90, 50, 40, 40)))
            self.assertEqual(detector.call_count, 1, '画完 ROI 应自动检测一次')
            self.assertEqual(self.total(), 200)
            self.tab.slider_thresh.setValue(150)
            QTest.qWait(190)
            self.assertEqual(detector.call_count, 2, '调参应防抖重跑当前框')
            QTest.mouseClick(self.tab.btn_otsu, Qt.MouseButton.LeftButton)
            self.assertEqual(detector.call_count, 3, 'Otsu 对已检测框立即重跑')
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.assertEqual(detector.call_count, 3, '全部已检测时按钮为停止，不再检测')
            self.assertEqual(self.total(), 0)
            self.tab.set_roi_rect((0, 0, 50, 50))
            self.assertEqual(detector.call_count, 4, '只自动检测新画的那一框')
            self.assertEqual([roi['status'] for roi in self.tab.rois], ['pending', 'active'])
            self.tab.clear_roi()
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.assertEqual(detector.call_count, 4, '无 ROI 不允许默认全图检测')
            self.assertIn('ROI', self.tab.lbl_status.text())

    def test_canvas_draws_only_roi_labels_and_emits_roi_pick(self):
        self.load()
        canvas = self.tab.canvas
        objects = image.detect_defects(self.gray, 127)
        canvas.set_rois([
            {'id': 1, 'roi': ('rect', (90, 50, 40, 40)), 'label': 'ROI 1 200px²'},
            {'id': 2, 'roi': ('rect', (10, 10, 30, 30)), 'label': 'ROI 2 待检测'},
        ], 1)
        canvas.set_objects(objects, '全部 ROI 总面积（重叠去重）: 200px²')
        self.assertEqual(len(self.grab_text()), 2)
        self.assertFalse(hasattr(canvas, 'labels'))
        picked = []
        canvas.roi_pick.connect(lambda x, y: picked.append((x, y)))
        canvas.set_mode('none')
        self.click(100, 60)
        self.assertEqual(len(picked), 1)

    def test_tool_button_and_escape_return_to_roi_pick_mode(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((0, 0, 50, 50))
        QTest.mouseClick(self.tab.btn_roi_rect, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'rect')
        QTest.mouseClick(self.tab.btn_roi_rect, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'none')
        self.assertFalse(self.tab.btn_roi_rect.isChecked())
        self.click(110, 65)
        self.assertEqual(self.tab.selected_roi_id, 1)
        QTest.mouseClick(self.tab.btn_roi_poly, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'poly')
        QTest.keyClick(self.tab.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.tab.canvas.mode, 'none')
        self.assertFalse(self.tab.btn_roi_poly.isChecked())

    def test_area_snap_matches_measure_canvas_seven_degree_rule(self):
        import math
        from area_canvas import snap_endpoint
        from measure_canvas import MeasureCanvas
        reference = MeasureCanvas()
        p1 = QPointF(10, 20)
        cases = [(100, 0), (100, 12), (100, 13), (13, 100), (12, 100),
                 (0, 100), (1, 1), (100, 100 * math.tan(math.radians(7))),
                 (100 * math.tan(math.radians(7)), 100)]
        for dx, dy in cases:
            with self.subTest(dx=dx, dy=dy):
                p2 = QPointF(10 + dx, 20 + dy)
                expected, kind = reference._snap_endpoint(p1, p2)
                actual, constraint = snap_endpoint(p1, p2)
                self.assertAlmostEqual(actual.x(), expected.x())
                self.assertAlmostEqual(actual.y(), expected.y())
                self.assertEqual(constraint, kind or '')

    def test_calibration_drag_snaps_preview_and_commit(self):
        self.load()
        QTest.mouseClick(self.tab.btn_calib, Qt.MouseButton.LeftButton)
        canvas = self.tab.canvas
        canvas.scale, canvas.offset = 2, QPointF(0, 0)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self.point(10, 20))
        QTest.mouseMove(canvas, self.point(110, 24))
        self.assertAlmostEqual(canvas._drag_end.y(), 20)
        with patch.object(self.tab, '_ask_calibration', return_value=(50., 'µm')):
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self.point(110, 24))
        self.assertEqual(canvas.calib_line, ((10., 20.), (110., 20.)))
        self.assertEqual(self.tab.unit_per_px, .5)

    def test_canvas_distance_measurement_uses_shared_calibration(self):
        self.load()
        self.assertTrue(self.tab.calibrate((0, 0), (100, 0), 50, 'mm'))
        QTest.mouseClick(self.tab.btn_measure, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 23)
        self.click(200, 20)
        self.click(203, 120)
        self.assertEqual(len(self.tab.measurements), 2)
        self.assertEqual([m['id'] for m in self.tab.measurements], [1, 2])
        self.assertEqual([m['constraint'] for m in self.tab.measurements], ['h', 'v'])
        self.assertEqual([m['dist_px'] for m in self.tab.measurements], [100., 100.])
        self.assertEqual([entry['label'] for entry in self.tab.canvas.distance_entries],
                         ['#1 50.00 mm', '#2 50.00 mm'])

    def test_distance_labels_update_on_recalibration_and_clear_with_calibration(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 20)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.assertTrue(self.tab.calibrate((0, 0), (100, 0), 100, 'mm'))
        self.assertEqual(detector.call_count, 0)
        self.assertEqual(self.tab.canvas.distance_entries[0]['label'], '#1 100.00 mm')
        QTest.mouseClick(self.tab.btn_clear_calib, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.measurements, [])
        self.assertEqual(self.tab.canvas.distance_entries, [])
        self.assertFalse(self.tab.btn_measure.isEnabled())
        self.assertEqual(self.tab.canvas.mode, 'none')
        self.assertIsNone(self.tab.canvas.pending_distance)
        self.load(np.zeros((31, 47), np.uint8), '新图.png')
        self.assertEqual(self.tab.measurements, [])
        self.assertEqual(self.tab.canvas.distance_entries, [])

    def test_distance_pending_cancels_on_escape_and_tool_switch(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        QTest.mouseClick(self.tab.btn_measure, Qt.MouseButton.LeftButton)
        self.click(10, 20)
        self.assertIsNotNone(self.tab.canvas.pending_distance)
        QTest.keyClick(self.tab.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.tab.canvas.pending_distance)
        self.assertEqual(self.tab.canvas.mode, 'none')
        QTest.mouseClick(self.tab.btn_measure, Qt.MouseButton.LeftButton)
        self.click(10, 20)
        QTest.mouseClick(self.tab.btn_roi_rect, Qt.MouseButton.LeftButton)
        self.assertIsNone(self.tab.canvas.pending_distance)
        self.assertEqual(self.tab.canvas.mode, 'rect')

    def test_clear_calibration_mid_distance_blocks_second_point(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        QTest.mouseClick(self.tab.btn_clear_calib, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'none')
        self.assertIsNone(self.tab.canvas.pending_distance)
        self.click(110, 20)
        self.assertEqual(self.tab.measurements, [])
        self.assertFalse(self.tab.add_distance(0, 0, 10, 0, 10, 'h'))
        self.assertEqual(self.tab.measurements, [])

    def test_snap_negative_directions_match_reference(self):
        from area_canvas import snap_endpoint
        from measure_canvas import MeasureCanvas
        reference = MeasureCanvas()
        p1 = QPointF(100, 100)
        for dx, dy in ((-100, -4), (-4, -100), (-100, 4), (4, -100)):
            with self.subTest(dx=dx, dy=dy):
                p2 = QPointF(100 + dx, 100 + dy)
                expected, kind = reference._snap_endpoint(p1, p2)
                actual, constraint = snap_endpoint(p1, p2)
                self.assertAlmostEqual(actual.x(), expected.x())
                self.assertAlmostEqual(actual.y(), expected.y())
                self.assertEqual(constraint, kind or '')

    def test_distance_labels_do_not_revive_defect_text(self):
        self.load()
        self.detect((90, 50, 40, 40))
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 20)
        texts = self.grab_text()
        self.assertEqual(len(texts), 3)
        self.assertTrue(any(text.startswith('ROI 1') for text in texts))
        self.assertTrue(any(text.startswith('#1') for text in texts))
        self.assertFalse(any('px²' in text for text in texts))

    def test_distance_hit_index_uses_segment_tolerance(self):
        from area_canvas import distance_hit_index
        entries = [
            {'p1': (0, 0), 'p2': (100, 0)},
            {'p1': (0, 20), 'p2': (100, 20)},
        ]
        self.assertEqual(distance_hit_index(entries, 50, 1), 0)
        self.assertEqual(distance_hit_index(entries, 50, 19), 1)
        self.assertEqual(distance_hit_index(entries, 50, 10), -1)
        self.assertEqual(distance_hit_index(entries, 101, 0), 0)
        self.assertEqual(distance_hit_index(entries, 103, 0), -1)

    def test_distance_delete_tool_removes_clicked_line_and_keeps_ids(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        for y in (20, 40, 60):
            self.click(10, y)
            self.click(110, y)
        QTest.mouseClick(self.tab.btn_distance_delete, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.canvas.mode, 'distance_delete')
        QTest.mouseMove(self.tab.canvas, self.point(60, 40))
        self.assertEqual(self.tab.canvas.hovered_distance_index, 1)
        self.click(60, 40)
        self.assertEqual([m['id'] for m in self.tab.measurements], [1, 3])
        self.assertEqual([entry['label'] for entry in self.tab.canvas.distance_entries],
                         ['#1 50.00 mm', '#3 50.00 mm'])
        QTest.keyClick(self.tab.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.tab.canvas.mode, 'none')

    def test_clear_distances_removes_all_resets_id_and_keeps_defects(self):
        self.load()
        self.detect((90, 50, 40, 40))
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 20)
        self.click(10, 40)
        self.click(110, 40)
        QTest.mouseClick(self.tab.btn_clear_distances, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.measurements, [])
        self.assertEqual(self.tab.canvas.distance_entries, [])
        self.assertEqual(self.total(), 200)
        self.assertEqual(len(self.tab.rois), 1)
        self.tab.set_mode('measure')
        self.click(10, 20)
        self.click(110, 20)
        self.assertEqual(self.tab.measurements[0]['id'], 1)

    def test_new_roi_detects_automatically_on_draw(self):
        self.load()
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.assertTrue(self.tab.set_roi_rect((90, 50, 40, 40)))
            self.assertEqual(detector.call_count, 1, '画完 ROI 应立即自动检测')
        roi = self.tab.rois[0]
        self.assertEqual(roi['status'], 'active')
        self.assertEqual(self.tab.roi_area_px(1), 200)
        first_objects = roi['objects']
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.tab.set_roi_rect((0, 0, 50, 50))
            self.assertEqual(detector.call_count, 1, '只检测新画的那一框')
        self.assertIs(self.tab.rois[0]['objects'], first_objects)
        self.assertEqual(self.tab.rois[1]['status'], 'active')

    def test_multiple_rois_detect_all_with_independent_thresholds(self):
        gray = np.zeros((80, 180), np.uint8)
        gray[10:20, 10:30] = 150
        gray[10:20, 80:100] = 180
        self.load(gray)
        self.assertTrue(self.tab.set_roi_rect((5, 5, 40, 40)))
        self.tab.slider_thresh.setValue(100)
        self.assertTrue(self.tab.set_roi_rect((75, 5, 40, 40)))
        self.assertEqual(self.tab.slider_thresh.value(), 100)
        self.tab.slider_thresh.setValue(160)
        QTest.qWait(190)
        self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [0, 200])
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        self.drain_batch()
        self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [200, 200])
        first_objects = self.tab.rois[0]['objects']
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.tab.select_roi(2)
            self.tab.slider_thresh.setValue(140)
            QTest.qWait(190)
        self.assertEqual(detector.call_count, 1)
        self.assertIs(self.tab.rois[0]['objects'], first_objects)
        self.assertEqual(self.tab.roi_area_px(2), 200)

    def test_overlapping_rois_keep_independent_areas_and_union_total(self):
        gray = np.zeros((40, 60), np.uint8)
        gray[10:20, 10:45] = 255
        self.load(gray)
        self.tab.set_roi_rect((10, 10, 20, 10))
        self.tab.set_roi_rect((25, 10, 20, 10))
        self.assertEqual(self.tab.roi_area_px(1), 200)
        self.assertEqual(self.tab.roi_area_px(2), 200)
        self.assertEqual(self.tab.union_area_px(), 350)
        self.assertIn('350px²', self.tab.lbl_total.text())

    def test_union_preserves_holes_when_rois_are_identical(self):
        gray = np.zeros((40, 50), np.uint8)
        gray[10:30, 10:30] = 255
        gray[15:25, 15:25] = 0
        self.load(gray)
        self.tab.set_roi_rect((10, 10, 20, 20))
        self.tab.set_roi_rect((10, 10, 20, 20))
        self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [300, 300])
        self.assertEqual(self.tab.union_area_px(), 300)

    def test_manual_delete_and_add_only_change_current_overlapping_roi(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((90, 50, 40, 40))
        other_objects = self.tab.rois[1]['objects']
        self.tab.select_roi(1)
        self.assertTrue(self.tab.delete_at(110, 65))
        self.assertEqual(self.tab.roi_area_px(1), 0)
        self.assertEqual(self.tab.roi_area_px(2), 200)
        self.assertIs(self.tab.rois[1]['objects'], other_objects)
        self.assertEqual(self.tab.union_area_px(), 200)
        self.assertTrue(self.tab.preview_add(110, 65))
        self.assertTrue(self.tab.confirm_add())
        self.assertEqual(self.tab.roi_area_px(1), 200)
        self.assertTrue(self.tab.rois[0]['manual_changed'])
        self.assertFalse(self.tab.rois[1]['manual_changed'])
        self.assertIs(self.tab.rois[1]['objects'], other_objects)
        self.assertEqual(self.tab.union_area_px(), 200)
        self.assertEqual({obj['roi_id'] for obj in self.tab.rois[0]['objects']}, {1})

    def test_csv_contains_roi_id_for_each_roi(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((90, 50, 40, 40))
        path = self.root / 'multi-roi.csv'
        self.assertTrue(self.tab.export_csv(str(path)))
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, [
                'ROI编号', '缺陷编号', '像素面积', '实际面积', '面积单位',
                '质心x_px', '质心y_px', '来源'])
            rows = list(reader)
        self.assertEqual([row['ROI编号'] for row in rows], ['1', '2'])
        self.assertEqual([row['像素面积'] for row in rows], ['200', '200'])

    def test_pending_roi_makes_detect_button_run_whole_batch_again(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        self.assertEqual([roi['status'] for roi in self.tab.rois], ['pending'] * 2)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.drain_batch()
        self.assertEqual(detector.call_count, 2)
        self.assertEqual([roi['status'] for roi in self.tab.rois], ['active', 'active'])

    def test_stop_during_batch_invalidates_queued_results(self):
        self.load()
        for _ in range(3):
            self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.assertEqual(detector.call_count, 1)
            self.assertEqual(self.tab._batch_queue, [2, 3])
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            QTest.qWait(50)
        self.assertEqual(detector.call_count, 1, '停止后不得继续检测排队 ROI')
        self.assertFalse(self.tab._batch_active)
        self.assertEqual(self.tab._batch_queue, [])
        self.assertEqual(self.tab.objects, [])
        self.assertEqual([roi['status'] for roi in self.tab.rois], ['pending'] * 3)

    def test_new_image_invalidates_queued_results(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.assertEqual(self.tab._batch_queue, [2])
            self.load(np.zeros((31, 47), np.uint8), '换图.png')
            QTest.qWait(50)
        self.assertEqual(detector.call_count, 1)
        self.assertEqual(self.tab.rois, [])
        self.assertEqual(self.tab.objects, [])
        self.assertFalse(self.tab._batch_active)
        self.assertFalse(self.tab._batch_timer.isActive())

    def test_one_roi_error_does_not_interrupt_remaining_batch(self):
        self.load()
        for _ in range(3):
            self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise cv2.error('synthetic ROI failure')
            return image.detect_defects(*args, **kwargs)

        with patch('area_tab.detect_defects', side_effect=fail_second):
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.drain_batch()
        self.assertEqual(calls, 3)
        self.assertEqual([roi['status'] for roi in self.tab.rois],
                         ['active', 'error', 'active'])
        self.assertEqual([self.tab.roi_area_px(roi_id) for roi_id in (1, 2, 3)],
                         [200, 0, 200])
        self.assertEqual(self.tab.union_area_px(), 200)

    def test_identical_rois_select_object_by_identity_not_dict_equality(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.select_roi(2)
        self.tab.table.blockSignals(True)
        self.tab.table.selectRow(0)
        self.tab.table.blockSignals(False)
        self.tab.select_object()
        self.app.processEvents()
        self.assertEqual(self.tab.canvas.selected_index, 1)
        self.assertIs(self.tab.canvas.objects[self.tab.canvas.selected_index],
                      self.tab.rois[1]['objects'][0])

    def test_full_rerun_from_active_roi_leaves_no_debounce_timer(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        self.drain_batch()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.select_roi(1)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
            self.drain_batch()
            QTest.qWait(190)
        self.assertEqual(detector.call_count, 2)
        self.assertFalse(self.tab._detect_timer.isActive())

    def test_switching_roi_during_debounce_marks_old_results_pending(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((0, 0, 50, 50))
        self.tab.select_roi(1)
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            self.tab.slider_thresh.setValue(210)
            self.assertTrue(self.tab._detect_timer.isActive())
            self.tab.select_roi(2)
            QTest.qWait(190)
        self.assertEqual(detector.call_count, 0, '选择本身不得触发检测')
        self.assertEqual(self.tab.rois[0]['status'], 'pending')
        self.assertEqual(self.tab.rois[0]['objects'], [])
        self.assertEqual(self.tab.roi_area_px(1), 0)
        self.assertEqual(self.tab.rois[0]['params']['threshold'], 210)
        self.assertEqual(self.tab.rois[1]['status'], 'active')
        self.assertEqual(self.tab.roi_area_px(2), 0)

    def test_dense_results_never_draw_object_text(self):
        gray = np.zeros((160, 240), np.uint8)
        for row in range(10):
            for col in range(12):
                gray[5 + row * 15, 5 + col * 19] = 255
        self.load(gray)
        self.tab.set_roi_rect((0, 0, 240, 160))
        self.assertFalse(hasattr(self.tab, 'chk_show_labels'))
        self.assertEqual(len(self.tab.objects), 120)
        self.assertFalse(hasattr(self.tab.canvas, 'labels'))
        self.assertEqual(len(self.grab_text()), 1, '只应绘制当前图像唯一 ROI 的面积标签')
        self.tab.table.selectRow(5)
        self.app.processEvents()
        self.assertEqual(self.tab.canvas.selected_index, 5)
        self.tab.canvas.scale = 2
        self.assertEqual(len(self.grab_text()), 1, '选择缺陷和缩放后仍不得出现逐缺陷文字')

    def test_load_calibrate_roi_chain_via_real_controls(self):
        path = self.load()
        with patch('area_tab.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            QTest.mouseClick(self.tab.btn_load, Qt.MouseButton.LeftButton)
        self.assertEqual(self.total(), 0)
        QTest.mouseClick(self.tab.btn_calib, Qt.MouseButton.LeftButton)
        with patch.object(self.tab, '_ask_calibration', return_value=(50., 'µm')):
            # Exact screen mapping keeps this a 100-pixel calibration line.
            self.tab.canvas.scale = 2
            self.tab.canvas.offset = QPointF(0, 0)
            self.drag(10, 20, 110, 20)
        self.assertEqual(self.tab.unit_per_px, .5)
        QTest.mouseClick(self.tab.btn_roi_rect, Qt.MouseButton.LeftButton)
        self.drag(90, 50, 130, 80)
        self.assertEqual(self.total(), 200, '画完 ROI 应自动检测')
        self.assertIn('50.00 µm²', self.tab.lbl_total.text())
        self.assertEqual(self.tab.table.item(0, 2).text(), '50.00 µm²')
        self.assertEqual(self.tab.table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertFalse(self.tab.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)

    def test_recalibration_unit_change_and_clear_keep_manual_edits(self):
        self.load()
        self.empty_active_roi()
        self.tab.preview_add(110, 65)
        self.assertTrue(self.tab.confirm_add())
        original = self.tab.objects
        from area_tab import compute_real_area
        for length, unit, expected in ((50000., 'nm', 5e7), (50., 'µm', 50.),
                                       (.05, 'mm', 5e-5), (.005, 'cm', 5e-7),
                                       (.00005, 'm', 5e-11)):
            self.assertTrue(self.tab.calibrate((0, 0), (100, 0), length, unit))
            self.assertAlmostEqual(compute_real_area(200, self.tab.unit_per_px) / expected, 1.)
            self.assertIs(self.tab.objects, original)
            self.assertEqual(self.total(), 200)
            self.assertEqual(self.tab.objects[0]['source'], '手动')
            self.assertIn(unit, self.tab.lbl_calib.text())
        QTest.mouseClick(self.tab.btn_clear_calib, Qt.MouseButton.LeftButton)
        self.assertIs(self.tab.objects, original)
        self.assertIsNone(self.tab.unit_per_px)
        self.assertIn('200px²', self.tab.lbl_total.text())
        self.assertIn('未标定', self.tab.canvas.summary)

    def test_invalid_or_cancelled_calibration_preserves_valid_line(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'µm')
        for end, length in (((9, 0), 10), ((100, 0), 0), ((100, 0), -2)):
            self.assertFalse(self.tab.calibrate((0, 0), end, length, 'mm'))
            self.assertEqual(self.tab.unit_per_px, .5)
            self.assertEqual(self.tab.unit, 'µm')
        with patch.object(self.tab, '_ask_calibration', return_value=None):
            self.assertFalse(self.tab.calibrate((0, 0), (200, 0)))
        self.assertEqual(self.tab.unit_per_px, .5)

    def test_clear_all_rois_resets_count_and_next_number(self):
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((0, 0, 50, 50))
        self.assertIn('ROI 数量: 2', self.tab.lbl_count.text())
        QTest.mouseClick(self.tab.btn_clear_roi, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.rois, [])
        self.assertEqual(self.tab.roi_table.rowCount(), 0)
        self.assertEqual(self.tab.canvas.roi_entries, [])
        self.assertIn('ROI 数量: 0', self.tab.lbl_count.text())
        self.assertEqual(self.tab.selected_roi_id, -1)
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.assertEqual(self.tab.current_roi()['id'], 1)
        self.assertIn('ROI 数量: 1', self.tab.lbl_count.text())
        self.assertTrue(self.tab.canvas.roi_entries[0]['label'].startswith('ROI 1 '))

    def test_roi_append_is_transactional_and_escape_cancels_draft(self):
        self.load()
        self.empty_active_roi()
        old = self.tab.current_roi()['mask'].copy()
        QTest.mouseClick(self.tab.btn_roi_rect, Qt.MouseButton.LeftButton)
        self.drag(100, 60, 102, 62)
        np.testing.assert_array_equal(self.tab.current_roi()['mask'], old)
        QTest.mouseClick(self.tab.btn_roi_poly, Qt.MouseButton.LeftButton)
        self.click(90, 50)
        self.click(130, 50)
        np.testing.assert_array_equal(self.tab.current_roi()['mask'], old)
        QTest.keyClick(self.tab.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.tab.canvas.poly_drawing, [])
        np.testing.assert_array_equal(self.tab.current_roi()['mask'], old)
        QTest.mouseClick(self.tab.btn_roi_poly, Qt.MouseButton.LeftButton)
        self.click(90, 50)
        self.click(130, 50)
        self.click(130, 80)
        QTest.mouseDClick(self.tab.canvas, Qt.MouseButton.LeftButton, pos=self.point(90, 80))
        self.assertEqual(self.total(), 200)
        self.assertEqual(self.tab.union_area_px(), 200)
        self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [0, 200])
        QTest.mouseClick(self.tab.btn_clear_roi, Qt.MouseButton.LeftButton)
        self.assertIsNone(self.tab.current_roi())
        self.assertEqual(self.tab.canvas.roi_entries, [])
        self.assertEqual(self.total(), 0)

    def test_new_image_clears_calibration_roi_preview_and_old_results(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.empty_active_roi()
        self.tab.preview_add(110, 65)
        self.tab.slider_thresh.setValue(140)
        self.load(np.zeros((31, 47), np.uint8), '新图.png')
        self.assertEqual(self.tab.gray.shape, (31, 47))
        self.assertIsNone(self.tab.unit_per_px)
        self.assertIsNone(self.tab.current_roi())
        self.assertIsNone(self.tab.canvas.preview)
        self.assertEqual(self.tab.objects, [])
        self.assertFalse(self.tab._detect_timer.isActive())
        self.assertEqual(self.tab.slider_thresh.value(), 140)
        QTest.qWait(190)
        self.assertEqual(self.tab.objects, [])

    def test_16bit_tiff_rgb_rgba_and_chinese_path_keep_source_dimensions(self):
        for dtype in (np.uint8, np.uint16):
            gray = np.zeros((23, 31), dtype)
            gray[3:8, 4:14] = 200 if dtype == np.uint8 else 40000
            self.load(gray, '灰度.tif')
            self.detect()
            self.assertEqual(self.tab.gray.dtype, np.uint8)
            self.assertEqual(self.tab.gray.shape, (23, 31))
            self.assertEqual(self.total(), 50)
            for channels in (3, 4):
                rgb = np.zeros((23, 31, channels), dtype)
                rgb[3:8, 4:14, 0] = np.iinfo(dtype).max
                if channels == 4:
                    rgb[:, :, 3] = np.iinfo(dtype).max
                self.load(rgb, '彩色.tiff')
                self.detect()
                self.assertEqual(self.tab.gray.shape, (23, 31))
                self.assertEqual(int(self.tab.gray[4, 5]), 76)
                self.assertEqual(tuple(self.tab.img_cv[4, 5, :3]), (0, 0, 255))
        bgra = np.zeros((23, 31, 4), np.uint8)
        bgra[3:8, 4:14, :3] = 255
        bgra[:, :, 3] = 255
        self.load(bgra, '透明.png')
        self.detect()
        self.assertEqual(self.total(), 50)

    def test_failed_image_and_unsupported_scientific_stack_keep_valid_state(self):
        self.load()
        self.detect()
        old = self.tab.img_cv
        self.tab.calibrate((0, 0), (100, 0), 50, 'µm')
        broken = self.root / '坏图.png'
        broken.write_bytes(b'not an image')
        stack = self.root / '多页.tif'
        tifffile.imwrite(stack, np.zeros((5, 20, 30), np.uint16), photometric='minisblack')
        volume = self.root / '体积.tif'
        tifffile.imwrite(volume, np.zeros((3, 20, 30), np.uint16),
                         photometric='minisblack', volumetric=True)
        for path in (broken, stack, volume, self.root / '不存在.png'):
            self.assertFalse(self.tab.load_image(str(path)))
            self.assertIs(self.tab.img_cv, old)
            self.assertEqual(self.total(), 200)
            self.assertEqual(self.tab.unit_per_px, .5)
            self.assertIn('失败', self.tab.lbl_status.text())

    def test_corrupt_deflate_tiff_reports_error_and_preserves_valid_state(self):
        import io
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'µm')
        self.tab.set_roi_rect((90, 50, 40, 30))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        old_image, old_objects = self.tab.img_cv, self.tab.objects
        old_roi = self.tab.current_roi()['mask']
        stream = io.BytesIO()
        tifffile.imwrite(stream, self.gray, compression='deflate')
        with tifffile.TiffFile(io.BytesIO(stream.getvalue())) as tif:
            offset = tif.pages[0].dataoffsets[0]
        data = bytearray(stream.getvalue())
        data[offset:offset + 2] = b'\x00\x00'
        path = self.root / '损坏压缩.tif'
        path.write_bytes(data)
        self.assertFalse(self.tab.load_image(str(path)))
        self.assertIs(self.tab.img_cv, old_image)
        self.assertIs(self.tab.objects, old_objects)
        self.assertIs(self.tab.current_roi()['mask'], old_roi)
        self.assertEqual(self.tab.unit_per_px, .5)
        self.assertIn('图片加载失败', self.tab.lbl_status.text())

    def test_minimum_area_keyboard_entry_and_slider_stay_synchronized(self):
        self.gray[10:12, 10:12] = 200
        self.load()
        self.detect()
        self.assertTrue(hasattr(self.tab, 'spin_min_area'), '最小面积需要精确数值输入')
        spin = self.tab.spin_min_area
        self.tab.sidebar_scroll.ensureWidgetVisible(spin)
        spin.setFocus()
        spin.selectAll()
        QTest.keyClicks(spin, '50')
        QTest.keyClick(spin, Qt.Key.Key_Enter)
        self.assertEqual(self.tab.slider_min_area.value(), 50)
        QTest.qWait(190)
        self.assertEqual(self.total(), 200)
        self.tab.slider_min_area.setValue(201)
        self.assertEqual(spin.value(), 201)
        QTest.qWait(190)
        self.assertEqual(self.total(), 0)
        spin.setValue(1)
        QTest.qWait(190)
        self.assertEqual(self.total(), 204)
        self.assertEqual((spin.minimum(), spin.maximum()), (1, 100000))

    def test_threshold_slider_drag_only_detects_on_release(self):
        self.load()
        self.detect()
        slider = self.tab.slider_thresh
        with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
            slider.setSliderDown(True)
            self.assertTrue(self.tab._slider_dragging)
            slider.setValue(30)
            slider.setValue(200)
            self.app.processEvents()
            self.assertEqual(detector.call_count, 0, '拖动中不得检测')
            self.assertFalse(self.tab._detect_timer.isActive(), '拖动中不得启动防抖')
            slider.setSliderDown(False)
        self.assertEqual(detector.call_count, 1, '松手立即重跑一次')
        self.assertFalse(self.tab._slider_dragging)

    def test_threshold_and_minimum_debounce_polarity_and_otsu(self):
        self.load()
        self.detect()
        self.assertTrue(self.tab._detect_timer.isSingleShot())
        self.assertEqual(self.tab._detect_timer.interval(), 150)
        self.tab.slider_thresh.setValue(210)
        QTest.qWait(65)
        self.assertEqual(self.total(), 200)
        self.tab.slider_thresh.setValue(220)
        QTest.qWait(65)
        self.assertEqual(self.total(), 200)
        QTest.qWait(120)
        self.assertEqual(self.total(), 0)
        self.tab.slider_thresh.setValue(127)
        QTest.qWait(190)
        QTest.mouseClick(self.tab.chk_bright, Qt.MouseButton.LeftButton,
                         pos=QPoint(6, self.tab.chk_bright.height() // 2))
        QTest.qWait(190)
        self.assertEqual(self.total(), 38200)
        QTest.mouseClick(self.tab.chk_bright, Qt.MouseButton.LeftButton,
                         pos=QPoint(6, self.tab.chk_bright.height() // 2))
        self.tab.slider_min_area.setValue(201)
        QTest.qWait(65)
        self.assertEqual(self.total(), 38200)
        QTest.qWait(120)
        self.assertEqual(self.total(), 0)
        self.tab.slider_min_area.setValue(1)
        QTest.mouseClick(self.tab.btn_otsu, Qt.MouseButton.LeftButton)
        QTest.qWait(190)
        self.assertEqual(self.tab.slider_thresh.value(), 0)
        self.assertEqual(self.total(), 200)

    def test_manual_add_is_clipped_to_current_roi(self):
        gray = np.zeros((20, 20), np.uint8)
        gray[2:18, 2:18] = 255
        self.load(gray)
        self.tab.set_roi_rect((5, 5, 10, 10))
        self.assertEqual(self.tab.roi_area_px(1), 100)
        self.assertTrue(self.tab.delete_at(6, 6))
        self.assertEqual(self.tab.roi_area_px(1), 0)
        self.assertTrue(self.tab.preview_add(6, 6))
        self.assertEqual(self.tab.canvas.preview['area_px'], 100)
        self.assertTrue(self.tab.confirm_add())
        obj = self.tab.rois[0]['objects'][0]
        self.assertEqual(obj['rect'], (5, 5, 10, 10))
        self.assertEqual(obj['mask'].shape, (10, 10))
        self.assertEqual(self.tab.roi_area_px(1), 100)
        self.assertEqual(self.tab.union_area_px(), 100)

    def test_add_preview_double_click_confirm_escape_and_duplicate_rejection(self):
        self.load()
        self.empty_active_roi()
        QTest.mouseClick(self.tab.btn_add, Qt.MouseButton.LeftButton)
        self.click(110, 65)
        self.assertEqual(self.total(), 0)
        self.assertEqual(self.tab.canvas.preview['area_px'], 200)
        QTest.keyClick(self.tab.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.tab.canvas.preview)
        QTest.mouseClick(self.tab.btn_add, Qt.MouseButton.LeftButton)
        self.click(110, 65)
        QTest.mouseDClick(self.tab.canvas, Qt.MouseButton.LeftButton, pos=self.point(110, 65))
        self.assertEqual(self.total(), 200)
        obj = self.tab.objects[0]
        self.assertEqual(obj['source'], '手动')
        self.assertEqual(obj['rect'], (100, 60, 20, 10))
        self.assertEqual((obj['cx'], obj['cy']), (109.5, 64.5))
        self.assertEqual(obj['mask'].shape, (10, 20))
        self.click(110, 65)
        QTest.mouseDClick(self.tab.canvas, Qt.MouseButton.LeftButton, pos=self.point(110, 65))
        self.assertEqual(self.total(), 200)
        self.assertIsNone(self.tab.canvas.preview)
        self.assertIn('重叠', self.tab.lbl_status.text())

    def test_add_nearest_centroid_fallback_and_uniform_window_rejection(self):
        self.load()
        self.empty_active_roi()
        self.assertTrue(self.tab.preview_add(125, 65))
        self.assertEqual(self.tab.canvas.preview['area_px'], 200)
        self.assertFalse(self.tab.preview_add(140, 65))
        self.assertIsNone(self.tab.canvas.preview)
        self.assertFalse(self.tab.preview_add(5, 5))
        self.assertFalse(self.tab.preview_add(-1, 5))
        self.assertEqual(self.total(), 0)
        self.load(np.full((160, 240), 255, np.uint8))
        self.detect((0, 0, 50, 50))
        self.assertEqual(self.total(), 2500)
        self.assertFalse(self.tab.preview_add(110, 65))
        self.assertEqual(self.total(), 2500)

    def test_overlap_is_rechecked_when_confirming_and_partial_overlap_is_refused(self):
        self.load()
        self.empty_active_roi()
        self.tab.preview_add(110, 65)
        # Simulate an intervening real detection result arriving at confirmation.
        candidate = self.tab.canvas.preview
        self.tab._run_roi(self.tab.current_roi())
        self.tab.canvas.set_preview(candidate)
        self.assertFalse(self.tab.confirm_add())
        self.assertEqual(self.total(), 200)
        self.tab.set_roi_rect((100, 60, 10, 10))
        self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [200, 100])
        self.assertFalse(self.tab.preview_add(115, 65))
        self.assertEqual(self.total(), 300)

    def test_parameter_changes_cancel_preview_and_rerun_discards_manual_edits(self):
        self.load()
        self.empty_active_roi()
        self.tab.preview_add(110, 65)
        self.tab.confirm_add()
        self.tab.slider_thresh.setValue(150)
        QTest.qWait(190)
        self.assertEqual(self.total(), 200)
        self.assertFalse(self.tab.current_roi()['manual_changed'])
        self.assertEqual(self.tab.objects[0]['source'], '自动')
        self.assertIn('手动', self.tab.lbl_status.text())
        for change in (lambda: self.tab.slider_thresh.setValue(151),
                       lambda: self.tab.chk_bright.setChecked(False),
                       lambda: self.tab.slider_min_area.setValue(2),
                       self.tab.clear_roi):
            self.tab.chk_bright.setChecked(True)
            self.tab.slider_min_area.setValue(1)
            self.empty_active_roi()
            self.tab.preview_add(110, 65)
            self.assertIsNotNone(self.tab.canvas.preview)
            change()
            self.assertIsNone(self.tab.canvas.preview)

    def test_delete_hover_only_highlights_current_roi(self):
        self.gray[10:20, 10:30] = 200
        self.load()
        self.tab.set_roi_rect((90, 50, 40, 40))
        self.tab.set_roi_rect((0, 0, 50, 50))
        self.tab.select_roi(1)
        QTest.mouseClick(self.tab.btn_del, Qt.MouseButton.LeftButton)
        QTest.mouseMove(self.tab.canvas, self.point(15, 15))
        self.assertEqual(self.tab.canvas.hovered_index, -1)
        QTest.mouseMove(self.tab.canvas, self.point(110, 65))
        self.assertEqual(self.tab.canvas.hovered_index, 0)

    def test_ring_hole_not_deleted_and_crack_hit_matches_hover(self):
        gray = np.zeros((160, 240), np.uint8)
        gray[50:100, 40:90] = 255
        gray[55:95, 45:85] = 0
        gray[60:90, 150] = 255
        self.load(gray)
        self.detect()
        QTest.mouseClick(self.tab.btn_del, Qt.MouseButton.LeftButton)
        self.click(65, 75)
        self.assertEqual(len(self.tab.objects), 2)
        QTest.mouseMove(self.tab.canvas, self.point(151, 75))
        self.assertGreaterEqual(self.tab.canvas.hovered_index, 0)
        self.click(151, 75)
        self.assertEqual(self.total(), 900)
        self.assertEqual(self.tab.objects[0]['id'], 1)
        self.click(42, 75)
        self.assertEqual(self.total(), 0)

    def test_mask_rendering_keeps_holes_transparent_and_owns_memory(self):
        from area_canvas import mask_to_qimage
        mask = np.full((30, 30), 255, np.uint8)
        mask[5:25, 5:25] = 0
        overlay = mask_to_qimage(mask)
        self.assertEqual(overlay.pixelColor(2, 2).getRgb(), (0, 200, 120, 100))
        self.assertEqual(overlay.pixelColor(15, 15).alpha(), 0)
        mask[:] = 0
        self.assertEqual(overlay.pixelColor(2, 2).alpha(), 100)
        gray = np.zeros((160, 240), np.uint8)
        gray[60:90, 100:130] = 255
        gray[65:85, 105:125] = 0
        self.load(gray)
        self.detect()
        canvas = self.tab.canvas
        canvas.scale, canvas.offset = 2, QPointF(0, 0)
        rendered = canvas.grab().toImage()
        self.assertEqual(rendered.pixelColor(230, 150).getRgb(), (0, 0, 0, 255))
        color = rendered.pixelColor(204, 150)
        self.assertGreater(color.green(), color.red())
        self.assertEqual(canvas.label_font.pixelSize(), 12)

    def test_tools_exclusive_panning_does_not_finish_or_change_roi(self):
        self.load()
        self.empty_active_roi()
        old = self.tab.current_roi()['mask'].copy()
        QTest.mouseClick(self.tab.btn_roi_poly, Qt.MouseButton.LeftButton)
        self.click(90, 50)
        points = list(self.tab.canvas.poly_drawing)
        self.drag(150, 90, 160, 100, Qt.MouseButton.RightButton)
        self.assertEqual(self.tab.canvas.poly_drawing, points)
        np.testing.assert_array_equal(self.tab.current_roi()['mask'], old)
        QTest.mouseClick(self.tab.btn_add, Qt.MouseButton.LeftButton)
        self.assertFalse(self.tab.btn_roi_poly.isChecked())
        self.assertEqual(self.tab.canvas.poly_drawing, [])
        self.assertEqual(self.tab.canvas.mode, 'add')

    def test_zoom_both_axes_stays_anchored_at_scale_limits(self):
        self.load()
        canvas = self.tab.canvas
        for scale, delta, expected in ((49., 120, 50.), (50., 120, 50.),
                                       (.0101, -120, .01), (.01, -120, .01)):
            canvas.scale, canvas.offset = scale, QPointF(17, 39)
            position = QPointF(212, 143)
            before = canvas.widget_to_img(position)
            event = QWheelEvent(position, position, QPoint(), QPoint(0, delta),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(canvas, event)
            after = canvas.widget_to_img(position)
            self.assertEqual(canvas.scale, expected)
            self.assertAlmostEqual(before.x(), after.x())
            self.assertAlmostEqual(before.y(), after.y())

    def test_sidebar_scroll_and_splitter_work_at_1000_by_600(self):
        from styles import STYLESHEET
        self.tab.setStyleSheet(STYLESHEET)
        self.app.processEvents()
        self.tab.sections['测量结果'].toggle_btn.click()
        self.app.processEvents()
        scroll = self.tab.sidebar_scroll
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(self.tab.btn_export.isVisible())
        splitter = self.tab.splitter
        old = splitter.sizes()[0]
        handle = splitter.handle(1)
        center = handle.rect().center()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(handle, center + QPoint(60, 0))
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=center + QPoint(60, 0))
        self.assertGreater(splitter.sizes()[0], old)

    def test_csv_export_rejects_partial_batch_results(self):
        self.load()
        for _ in range(3):
            self.tab.set_roi_rect((90, 50, 40, 40))
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab._batch_queue, [2, 3])
        self.assertEqual(self.tab.btn_detect.text(), '停止并清空')
        output = self.root / 'partial.csv'
        result = self.tab.export_csv(str(output))
        exists = output.exists()
        status = self.tab.lbl_status.text()
        self.tab.toggle_detection()
        self.assertFalse(result)
        self.assertFalse(exists)
        self.assertIn('批量', status)

    def test_csv_bom_unscaled_small_precision_and_ui_export(self):
        self.load()
        self.detect()
        output = self.root / '面积.csv'
        with patch('area_tab.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            QTest.mouseClick(self.tab.btn_export, Qt.MouseButton.LeftButton)
        self.assertTrue(output.read_bytes().startswith(b'\xef\xbb\xbf'))
        with output.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[0], ['ROI编号', '缺陷编号', '像素面积', '实际面积', '面积单位',
                                   '质心x_px', '质心y_px', '来源'])
        self.assertEqual(rows[1], ['1', '1', '200', '', '未标定', '109.5', '64.5', '自动'])
        self.tab.calibrate((0, 0), (100, 0), .05, 'mm')
        self.assertTrue(self.tab.export_csv(str(output)))
        with output.open(encoding='utf-8-sig', newline='') as stream:
            row = list(csv.DictReader(stream))[0]
        self.assertEqual(float(row['实际面积']), .00005)
        self.assertEqual(row['面积单位'], 'mm²')
        self.assertEqual(row['像素面积'], '200')

    def test_csv_flushes_pending_threshold_and_no_data_creates_nothing(self):
        self.load()
        self.detect()
        output = self.root / '不应存在.csv'
        self.tab.slider_thresh.setValue(220)
        self.assertEqual(self.total(), 200)
        self.assertFalse(self.tab.export_csv(str(output)))
        self.assertEqual(self.total(), 0)
        self.assertFalse(output.exists())
        self.assertIn('无数据', self.tab.lbl_status.text())
        self.assertFalse(self.tab._detect_timer.isActive())

    def test_csv_io_error_keeps_results_and_existing_destination(self):
        self.load()
        self.detect()
        previous = self.tab.objects
        self.assertFalse(self.tab.export_csv(str(self.root / 'missing' / '面积.csv')))
        self.assertIs(self.tab.objects, previous)
        self.assertIn('失败', self.tab.lbl_status.text())
        destination = self.root / 'folder.csv'
        destination.mkdir()
        sentinel = destination / 'keep.txt'
        sentinel.write_text('keep', encoding='utf-8')
        self.assertFalse(self.tab.export_csv(str(destination)))
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'keep')
        self.assertEqual(self.total(), 200)

    def test_pan_during_rectangle_drag_cannot_commit_accidental_roi(self):
        self.load()
        self.empty_active_roi()
        old = self.tab.current_roi()['mask'].copy()
        self.tab.set_mode('rect')
        canvas = self.tab.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self.point(90, 50))
        QTest.mouseMove(canvas, self.point(130, 90))
        QTest.mousePress(canvas, Qt.MouseButton.RightButton, pos=self.point(130, 90))
        end = self.point(150, 110)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, pos=end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        np.testing.assert_array_equal(self.tab.current_roi()['mask'], old)
        self.assertEqual(self.total(), 0)

    def test_calibration_length_accepts_direct_typing_without_clearing(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialogButtonBox, QDoubleSpinBox
        self.load()

        def enter_length():
            dialog = QApplication.activeModalWidget()
            spin = dialog.findChild(QDoubleSpinBox, 'calibrationLength')
            spin.setFocus()
            QTest.keyClicks(spin, '12')
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()

        QTimer.singleShot(0, enter_length)
        self.assertTrue(self.tab.calibrate((0, 0), (100, 0)))
        self.assertAlmostEqual(self.tab.unit_per_px, .12)

    def test_calibration_dialog_rejects_zero_and_accepts_unit_with_keyboard(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QComboBox, QDialogButtonBox, QDoubleSpinBox
        self.load()
        self.detect()
        errors = []

        def enter_calibration():
            dialog = QApplication.activeModalWidget()
            try:
                spin = dialog.findChild(QDoubleSpinBox, 'calibrationLength')
                combo = dialog.findChild(QComboBox, 'calibrationUnit')
                buttons = dialog.findChild(QDialogButtonBox)
                spin.setFocus()
                QTest.keyClick(spin, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                QTest.keyClicks(spin, '0')
                self.assertFalse(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
                QTest.keyClick(spin, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                QTest.keyClicks(spin, '0.05')
                combo.setFocus()
                QTest.keyClick(combo, Qt.Key.Key_Down)  # µm → mm
                QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok),
                                 Qt.MouseButton.LeftButton)
            except (AssertionError, AttributeError) as exc:
                errors.append(exc)
                dialog.reject()

        QTimer.singleShot(0, enter_calibration)
        self.assertTrue(self.tab.calibrate((0, 0), (100, 0)))
        self.assertEqual(errors, [])
        self.assertEqual(self.tab.unit, 'mm')
        self.assertEqual(self.tab.unit_per_px, .0005)
        self.assertIn('50.00 µm²', self.tab.lbl_total.text())

    def test_manual_dark_add_and_delete_restore_total_without_renumbering(self):
        gray = np.full((160, 240), 255, np.uint8)
        gray[50:60, 60:80] = 0
        gray[80:90, 100:110] = 0
        self.load(gray)
        self.tab.chk_bright.setChecked(False)
        self.tab.slider_min_area.setValue(150)
        self.tab.set_roi_rect((50, 40, 80, 60))
        self.assertEqual(self.total(), 200)
        self.tab.set_mode('add')
        self.click(105, 85)
        QTest.mouseDClick(self.tab.canvas, Qt.MouseButton.LeftButton, pos=self.point(105, 85))
        self.assertEqual(self.total(), 300)
        self.assertEqual([o['id'] for o in self.tab.objects], [1, 2])
        self.tab.set_mode('delete')
        self.click(65, 55)
        self.assertEqual([o['id'] for o in self.tab.objects], [2])
        output = self.root / '手动.csv'
        self.assertTrue(self.tab.export_csv(str(output)))
        with output.open(encoding='utf-8-sig', newline='') as stream:
            row = list(csv.DictReader(stream))[0]
        self.assertEqual((row['缺陷编号'], row['来源'], row['像素面积']), ('2', '手动', '100'))
        self.click(105, 85)
        self.assertEqual(self.total(), 0)
        self.tab.detect_now()
        self.assertEqual(self.total(), 200)
        self.assertEqual(self.tab.objects[0]['id'], 1)

    def test_otsu_uses_roi_not_full_image(self):
        gray = np.full((160, 240), 250, np.uint8)
        gray[30:50, 30:50] = 20
        gray[35:40, 35:45] = 60
        self.load(gray)
        self.tab.set_roi_rect((30, 30, 20, 20))
        QTest.mouseClick(self.tab.btn_otsu, Qt.MouseButton.LeftButton)
        self.assertEqual(self.tab.slider_thresh.value(), 20)
        self.assertEqual(self.total(), 50)

    def test_tiff_planar_rgb_supported_but_float_images_rejected(self):
        planar = np.zeros((3, 20, 30), np.uint16)
        planar[0, 5:10, 8:18] = 40000
        path = self.root / '通道前置.tif'
        tifffile.imwrite(path, planar, photometric='rgb', planarconfig='separate')
        self.assertTrue(self.tab.load_image(str(path)))
        self.assertEqual(self.tab.gray.shape, (20, 30))
        self.assertEqual(self.tab.gray[6, 9], 76)
        old = self.tab.img_cv
        path = self.root / '不支持浮点.tif'
        tifffile.imwrite(path, np.ones((20, 30), np.float32))
        self.assertFalse(self.tab.load_image(str(path)))
        self.assertIs(self.tab.img_cv, old)
        self.assertIn('float32', self.tab.lbl_status.text())

    def test_distance_stats_table_and_csv_are_merged(self):
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 20)
        self.click(10, 40)
        self.click(210, 40)
        self.assertIn('测量数量: 2', self.tab.lbl_distance_count.text())
        self.assertIn('50.00 mm', self.tab.lbl_distance_min.text())
        self.assertIn('100.00 mm', self.tab.lbl_distance_max.text())
        self.assertIn('75.00 mm', self.tab.lbl_distance_mean.text())
        self.assertIn('150.00 mm', self.tab.lbl_distance_total.text())
        self.assertEqual(self.tab.distance_table.rowCount(), 2)
        self.assertEqual(self.tab.distance_table.item(0, 0).text(), '1')
        self.assertEqual(self.tab.distance_table.item(0, 1).text(), '50.00')
        self.assertEqual(self.tab.distance_table.item(0, 2).text(), '100.0')
        output = self.root / '距离.csv'
        self.assertTrue(self.tab.export_distance_csv(str(output)))
        self.assertTrue(output.read_bytes().startswith(b'\xef\xbb\xbf'))
        with output.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[0], ['序号', '距离(mm)', '距离(px)', '起点X', '起点Y',
                                   '终点X', '终点Y', '约束'])
        self.assertEqual(rows[1][0], '1')
        self.assertEqual(rows[1][1], '50.0')
        self.assertEqual(rows[1][2], '100.0')
        self.assertEqual(rows[1][-1], '水平')
        QTest.mouseClick(self.tab.btn_clear_distances, Qt.MouseButton.LeftButton)
        self.assertIn('测量数量: 0', self.tab.lbl_distance_count.text())
        self.assertEqual(self.tab.distance_table.rowCount(), 0)

    def test_sidebar_sections_collapsible_with_core_expanded(self):
        sections = self.tab.sections
        for title in ('比例尺标定', '检测区域', '阈值检测'):
            self.assertTrue(sections[title].container.isVisible(), title)
        for title in ('距离测量', '手动修正', '测量结果'):
            self.assertFalse(sections[title].container.isVisible(), title)
        distance = sections['距离测量']
        self.assertFalse(distance.toggle_btn.isCheckable())
        self.assertTrue(distance.toggle_btn.text().startswith('▲'))
        distance.toggle_btn.click()
        self.assertTrue(distance.container.isVisible())
        self.assertTrue(distance.toggle_btn.text().startswith('▼'))
        distance.toggle_btn.click()
        self.assertFalse(distance.container.isVisible())
        self.assertTrue(distance.toggle_btn.text().startswith('▲'))

    def test_distance_delete_tolerance_uses_screen_pixels_and_leave_clears(self):
        from PyQt6.QtCore import QEvent
        self.load()
        self.tab.calibrate((0, 0), (100, 0), 50, 'mm')
        self.tab.set_mode('measure')
        self.tab.canvas.scale, self.tab.canvas.offset = 2, QPointF(0, 0)
        self.click(10, 20)
        self.click(110, 20)
        self.tab.set_mode('distance_delete')
        self.tab.canvas.scale, self.tab.canvas.offset = .5, QPointF(0, 0)
        QTest.mouseMove(self.tab.canvas, self.point(50, 23))
        self.assertEqual(self.tab.canvas.hovered_distance_index, 0)
        self.tab.canvas.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertEqual(self.tab.canvas.hovered_distance_index, -1)

    def test_roi_action_buttons_are_two_by_two(self):
        self.app.processEvents()
        rect, poly = self.tab.btn_roi_rect, self.tab.btn_roi_poly
        delete, clear = self.tab.btn_delete_roi, self.tab.btn_clear_roi
        self.assertEqual(rect.y(), poly.y(), '矩形/多边形应在同一行')
        self.assertLess(rect.x(), poly.x())
        self.assertEqual(delete.y(), clear.y(), '删除/清空应在同一行')
        self.assertLess(delete.x(), clear.x())
        self.assertLess(rect.y(), delete.y(), '两行上下排列')
        self.assertAlmostEqual(rect.width(), poly.width(), delta=2)

    def test_main_window_has_six_tabs_with_roi_combined(self):
        with patch.dict(os.environ, {'AURASCOPE_RECIPE_DIR': str(self.root / 'recipes')}):
            from main_window import MainWindow
            window = MainWindow()
            try:
                tabs = window.tab_widget
                self.assertEqual(tabs.count(), 6)
                self.assertEqual([tabs.tabText(i).strip() for i in range(6)],
                                 ['空洞分析', '示教/批量', '剪切力计算',
                                  '物料计数', 'ROI', '图像拼接'])
                self.assertIs(tabs.widget(4), window.area_tab)
                self.assertFalse(hasattr(window, 'measure_tab'))
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
