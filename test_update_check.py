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

    def test_should_show_update_respects_skipped_version(self):
        info = {'version': '6.3.0', 'tag': 'v6.3.0', 'url': '', 'notes': ''}
        self.assertTrue(update_check.should_show_update(info, None))
        self.assertTrue(update_check.should_show_update(info, ''))
        self.assertTrue(update_check.should_show_update(info, '6.2.0'))
        self.assertTrue(update_check.should_show_update(info, 'v6.2.0'))
        self.assertFalse(update_check.should_show_update(info, '6.3.0'))
        self.assertFalse(update_check.should_show_update(info, 'v6.3.0'))
        self.assertFalse(update_check.should_show_update(info, '6.3.0+meta'))

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

    def test_pick_update_asset_takes_first_zip(self):
        payload = {'assets': [
            {'name': 'notes.txt', 'browser_download_url': 'https://x/notes.txt',
             'size': 10},
            {'name': 'AurascopeV6.3.1.zip',
             'browser_download_url': 'https://x/app.zip', 'size': 95},
        ]}
        asset = update_check.pick_update_asset(payload)
        self.assertEqual(asset['name'], 'AurascopeV6.3.1.zip')
        self.assertEqual(asset['url'], 'https://x/app.zip')
        self.assertEqual(asset['size'], 95)

    def test_pick_update_asset_returns_none_without_zip(self):
        self.assertIsNone(update_check.pick_update_asset({'assets': []}))
        self.assertIsNone(update_check.pick_update_asset({}))
        self.assertIsNone(update_check.pick_update_asset(
            {'assets': [{'name': 'app.exe',
                         'browser_download_url': 'https://x/app.exe'}]}))

    def test_parse_latest_release_carries_asset(self):
        info = update_check.parse_latest_release({
            'tag_name': 'v6.3.1', 'html_url': 'https://x', 'body': '',
            'draft': False, 'prerelease': False,
            'assets': [{'name': 'AurascopeV6.3.1.zip',
                        'browser_download_url': 'https://x/app.zip',
                        'size': 1}]})
        self.assertEqual(info['asset']['url'], 'https://x/app.zip')
        self.assertIsNone(update_check.parse_latest_release({
            'tag_name': 'v6.3.1', 'html_url': 'https://x', 'body': '',
            'draft': False, 'prerelease': False})['asset'])

    def test_parse_feed_reads_static_json(self):
        info = update_check.parse_feed({
            'version': '6.3.7',
            'url': 'https://gitee.com/x/Aurascope/releases/download/v6.3.7/app.zip',
            'page': 'https://gitee.com/x/Aurascope/releases/tag/v6.3.7',
            'notes': '修复自更新',
            'size': 123,
        })
        self.assertEqual(info['version'], '6.3.7')
        self.assertEqual(info['tag'], '6.3.7')
        self.assertEqual(info['url'],
                         'https://gitee.com/x/Aurascope/releases/tag/v6.3.7')
        self.assertEqual(info['notes'], '修复自更新')
        self.assertEqual(info['asset']['url'],
                         'https://gitee.com/x/Aurascope/releases/download/v6.3.7/app.zip')
        self.assertEqual(info['asset']['size'], 123)

    def test_parse_feed_accepts_github_shape(self):
        info = update_check.parse_feed({
            'tag_name': 'v6.3.7', 'html_url': 'https://x', 'body': 'note',
            'draft': False, 'prerelease': False,
            'assets': [{'name': 'a.zip', 'browser_download_url': 'https://x/a.zip'}]})
        self.assertEqual(info['version'], '6.3.7')
        self.assertEqual(info['asset']['url'], 'https://x/a.zip')

    def test_parse_feed_rejects_invalid_payload(self):
        for payload in (None, {}, {'version': 'latest'}, 'x'):
            with self.subTest(payload=payload):
                self.assertIsNone(update_check.parse_feed(payload))


if __name__ == '__main__':
    unittest.main()
