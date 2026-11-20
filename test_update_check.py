"""GitHub Releases 更新检查：纯解析与比较逻辑的单元测试。"""

import unittest

from packaging.version import Version

import update_check


class UpdateCheckLogicTests(unittest.TestCase):
    def test_parse_release_tag_accepts_optional_v_prefix(self):
        self.assertEqual(update_check.parse_release_tag('v6.2.0'), Version('6.2.0'))
        self.assertEqual(update_check.parse_release_tag('6.2.0'), Version('6.2.0'))

    def test_parse_release_tag_rejects_invalid_values(self):
        for tag in ('', 'latest', 'v', None):
            with self.subTest(tag=tag):
                self.assertIsNone(update_check.parse_release_tag(tag))

    def test_release_is_newer_uses_semantic_comparison(self):
        self.assertTrue(update_check.release_is_newer('v6.2.0', current='6.1.0'))
        self.assertTrue(update_check.release_is_newer('v6.10.0', current='6.9.0'))
        self.assertFalse(update_check.release_is_newer('v6.1.0', current='6.1.0'))
        self.assertFalse(update_check.release_is_newer('v6.0.9', current='6.1.0'))
        self.assertFalse(update_check.release_is_newer('v6.1.0-beta', current='6.1.0'))
        self.assertFalse(update_check.release_is_newer('not-a-version', current='6.1.0'))

    def test_parse_latest_release_extracts_fields(self):
        info = update_check.parse_latest_release({
            'tag_name': 'v6.2.0',
            'html_url': 'https://github.com/lingyue1932/Aurascope/releases/tag/v6.2.0',
            'body': '修复阈值拖动卡顿',
            'draft': False,
            'prerelease': False,
        })
        self.assertEqual(info['version'], '6.2.0')
        self.assertEqual(info['tag'], 'v6.2.0')
        self.assertEqual(info['url'],
                         'https://github.com/lingyue1932/Aurascope/releases/tag/v6.2.0')
        self.assertIn('阈值', info['notes'])

    def test_parse_latest_release_skips_draft_prerelease_and_missing_tag(self):
        base = {'tag_name': 'v6.2.0', 'html_url': 'https://x', 'body': '',
                'draft': False, 'prerelease': False}
        self.assertIsNone(update_check.parse_latest_release({**base, 'draft': True}))
        self.assertIsNone(update_check.parse_latest_release({**base, 'prerelease': True}))
        self.assertIsNone(update_check.parse_latest_release({**base, 'tag_name': ''}))


if __name__ == '__main__':
    unittest.main()
