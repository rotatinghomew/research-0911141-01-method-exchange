from pathlib import Path
import importlib
import json
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BrowserWorkflow(unittest.TestCase):
    def test_scope_archive_and_dataset_roundtrip(self):
        product = json.loads((ROOT / 'product.json').read_text())
        project = json.loads((ROOT / 'package.json').read_text())
        module_name = project['scripts']['start'].split()[2]
        server_module = importlib.import_module(module_name + '.server')
        with tempfile.TemporaryDirectory() as state:
            server = server_module.make_server(ROOT, state, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={'width': 1280, 'height': 900})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
                        page.locator('#status').filter(has_text='已更新比较').wait_for()
                        self.assertEqual(page.locator('h1').inner_text(), product['name'])
                        self.assertGreater(page.locator('#rows tr').count(), 0)
                        # 替换决策板块已渲染：偏差图、分箱剖面、适用范围、分组
                        self.assertEqual(page.locator('#profile-table tbody tr').count(), 6)
                        self.assertGreater(page.locator('#group-table tbody tr').count(), 0)
                        self.assertIn('误差约定', page.locator('#policy-echo').inner_text())
                        initial_bins = page.locator('#profile-table tbody tr td:first-child').all_inner_texts()
                        self.assertIn('合格', initial_bins)
                        # 点击分箱可追到支持它的样品
                        page.locator('#profile-table tbody tr').first.click()
                        self.assertIn('样品依据', page.locator('#details').inner_text())
                        # 样品行点击显示含复测与检出限信息的样品明细
                        page.locator('#rows tr').first.click()
                        self.assertIn('{', page.locator('#details').inner_text())
                        # 更严格的容许误差改变判定：合格箱数量下降
                        page.locator('#tolerance-absolute').fill('0.5')
                        page.locator('#tolerance-relative').fill('0.01')
                        page.locator('#inspect').click()
                        page.wait_for_function(
                            "text => document.querySelector('#policy-echo').textContent.startsWith(text)",
                            arg='当前误差约定 TEa(x) = 0.5000 + 0.0100')
                        strict_bins = page.locator('#profile-table tbody tr td:first-child').all_inner_texts()
                        self.assertLess(strict_bins.count('合格'), initial_bins.count('合格'))
                        # 非法相对误差由服务端拒绝并在页面提示，不产生静默结果
                        page.locator('#tolerance-relative').fill('5')
                        page.locator('#inspect').click()
                        page.locator('#status.error').wait_for()
                        page.locator('#tolerance-relative').fill('0.02')
                        page.locator('#raw').click()
                        table = next(iter(json.loads((ROOT / 'fixtures/data.json').read_text())))
                        page.wait_for_function(
                            "key => document.querySelector('#details').textContent.includes(JSON.stringify(key))",
                            arg=table)
                        page.locator('#title').fill('会议复核 α')
                        page.locator('#save').click()
                        page.locator('#status').filter(has_text='已保存记录').wait_for()
                        saved = json.loads(page.locator('#details').inner_text())
                        option = product['options'][1] if len(product['options']) > 1 else product['options'][0]
                        alternative = next(value for value in option[2]
                                           if value != product['selection'][option[0]])
                        page.locator('#select-' + option[0]).select_option(alternative)
                        page.locator('#inspect').click()
                        page.wait_for_function(
                            "([key, value]) => JSON.parse(document.querySelector('#details').textContent)"
                            ".selection[key] === value", arg=[option[0], alternative])
                        # 重新打开保存记录：数据版本、方法选择、误差约定全部恢复为冻结值
                        page.locator('#archive button').first.click()
                        page.locator('#status').filter(has_text='已读取保存的比较').wait_for()
                        reopened = json.loads(page.locator('#details').inner_text())
                        self.assertEqual(saved, reopened)
                        self.assertEqual(page.locator('#tolerance-absolute').input_value(), '0.5')
                        self.assertEqual(page.locator('#tolerance-relative').input_value(), '0.02')
                        with page.expect_download() as event:
                            page.locator('#export').click()
                        exported = json.loads(Path(event.value.path()).read_text())
                        self.assertEqual(exported['description']['revision'], saved['revision'])
                        self.assertTrue(exported['data'][table])
                        # 导出内容包含冻结的误差约定与分箱结论
                        self.assertEqual(
                            exported['description']['selection']['tolerance'],
                            {'absolute': 0.5, 'relative': 0.02})
                        self.assertTrue(exported['description']['view']['comparison']['profile']['bins'])
                        page.locator('#upload').set_input_files(str(ROOT / 'fixtures/data.json'))
                        page.locator('#status').filter(has_text='已导入独立数据版本').wait_for()
                        self.assertEqual(page.locator('#revision option').count(), 1)
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
