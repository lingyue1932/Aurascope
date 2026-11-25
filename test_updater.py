"""自更新工具（staging 复制 / 更新提示标记）的单元测试。"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import updater


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='aurascope_upd_')
        self.source = os.path.join(self.root, 'src')
        os.makedirs(os.path.join(self.source, '_internal'))
        with open(os.path.join(self.source, 'Aurascope.exe'), 'wb') as f:
            f.write(b'NEW-EXE')
        with open(os.path.join(self.source, '_internal', 'lib.dll'), 'wb') as f:
            f.write(b'x' * 64)
        self.staging = os.path.join(self.root, 'app_new')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_staging_dir_is_sibling_of_install_dir(self):
        self.assertEqual(updater.staging_dir(os.path.join(self.root, 'app')),
                         os.path.join(self.root, 'app_new'))

    def test_stage_files_copies_tree_and_reports_progress(self):
        seen = []
        copied = updater.stage_files(
            self.source, self.staging, lambda done, total: seen.append((done, total)))
        self.assertEqual(copied, updater.tree_size(self.source))
        self.assertTrue(os.path.isfile(os.path.join(self.staging, 'Aurascope.exe')))
        self.assertTrue(os.path.isfile(
            os.path.join(self.staging, '_internal', 'lib.dll')))
        self.assertEqual(seen[-1][0], seen[-1][1])      # 结束时进度满格

    def test_stage_files_cancel_returns_negative(self):
        copied = updater.stage_files(
            self.source, self.staging, None, lambda: True)
        self.assertEqual(copied, -1)
        self.assertTrue(os.path.isdir(self.staging))    # 清理交给调用方


class UpdateNoticeTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='aurascope_notice_')
        self.patcher = patch.object(updater, 'updates_root', lambda: self.root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_notice_consumed_only_for_current_version(self):
        updater.write_update_notice('9.9.9')
        self.assertFalse(updater.consume_update_notice())
        # 版本对不上时标记也会被删除，避免下次误报
        self.assertFalse(os.path.exists(
            os.path.join(self.root, updater.PENDING_NOTICE)))

    def test_notice_matches_running_version(self):
        from app_version import APP_VERSION
        updater.write_update_notice(APP_VERSION)
        self.assertTrue(updater.consume_update_notice())
        self.assertFalse(updater.consume_update_notice())

    def test_missing_notice_returns_false(self):
        self.assertFalse(updater.consume_update_notice())


if __name__ == '__main__':
    unittest.main()
