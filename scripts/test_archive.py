"""Isolated checks: no clipboard access, real chat data, or network."""
import base64
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from archive import allowed_source, atomic_json, ingest, read_json, sha256, unique_rename, monitor_clipboard, is_running, lock_runtime
from naming import make_filename, metadata

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def ocr_rows(*texts):
    return {'width': 800, 'height': 1600, 'lines': [
        {'text': text, 'words': [{'text': text, 'x': 200, 'y': 160 + i * 60, 'width': 400, 'height': 25}]}
        for i, text in enumerate(texts)]}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wechat-archive-test-')
        self.root = Path(self.temp.name)
        self.exports = self.root / 'account' / 'temp' / 'RWTemp'
        self.source = self.exports / '2026-01' / 'export' / 'sample.PNG'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(PNG)
        self.target = self.root / 'destination'
        self.config = self.root / 'runtime' / 'config.json'
        atomic_json(self.config, dict(enabled=True, source_root=str(self.exports), target_folder=str(self.target)))
        self.state = {'processed': {}}

    def tearDown(self):
        self.temp.cleanup()

    def save(self, ocr_fn=None):
        return ingest(self.source, self.config, self.state, ocr_fn or (lambda *_: {}))

    def image(self):
        return next(self.target.glob('*.PNG'))

    def test_copy_is_exact_and_keeps_extension_and_source(self):
        self.assertEqual(self.save(), 'local_ocr_unverified')
        self.assertEqual(self.image().read_bytes(), PNG)
        self.assertEqual(self.source.read_bytes(), PNG)
        record = next((self.config.parent / 'records').glob('*.json'))
        self.assertEqual(read_json(record)['sha256'], sha256(self.image()))
        self.assertTrue(self.image().name.startswith('待核对_'))

    def test_ocr_failure_still_saves_image(self):
        def fail(*_):
            self.assertEqual(self.image().read_bytes(), PNG)
            raise TimeoutError('Synthetic OCR failure')
        self.assertEqual(self.save(fail), 'ocr_failed')
        self.assertEqual(self.image().read_bytes(), PNG)

    def test_duplicate_and_user_rename_preserved(self):
        self.save()
        renamed = self.target / 'my-own-name.PNG'
        self.image().rename(renamed)
        self.assertEqual(self.save(), 'duplicate')
        self.assertEqual(list(self.target.iterdir()), [renamed])

    def test_only_clipboard_export_paths_are_accepted(self):
        self.assertTrue(allowed_source(self.source, self.exports))
        for path in (self.root / 'elsewhere.PNG', self.exports / 'sample.PNG',
                     self.exports / '2026-13' / 'x.PNG',
                     self.exports / '2026-01' / '..' / '..' / 'x.PNG', self.source.with_suffix('.txt')):
            self.assertFalse(allowed_source(path, self.exports), str(path))
        outside = self.root / 'outside.PNG'
        outside.write_bytes(PNG)
        self.assertEqual(ingest(outside, self.config, self.state), 'rejected_source')
        self.assertFalse(self.target.exists())

    def test_disabled_saves_nothing(self):
        config = read_json(self.config)
        config['enabled'] = False
        atomic_json(self.config, config)
        self.assertEqual(self.save(), 'disabled')
        self.assertFalse(self.target.exists())

    def test_name_collision_does_not_overwrite(self):
        self.target.mkdir()
        existing = self.target / 'same.PNG'
        existing.write_bytes(b'existing')
        temporary = self.target / 'new.part'
        temporary.write_bytes(PNG)
        result = unique_rename(temporary, existing)
        self.assertNotEqual(result, existing)
        self.assertEqual(existing.read_bytes(), b'existing')
        self.assertEqual(result.read_bytes(), PNG)

    def test_user_edit_during_ocr_wins(self):
        def edit(path, _):
            path.write_bytes(PNG + b'user-edit')
            return {}
        self.assertEqual(self.save(edit), 'skipped_user_changed')
        self.assertEqual(self.image().read_bytes(), PNG + b'user-edit')

    def test_user_rename_during_ocr_wins(self):
        def rename(path, _):
            path.rename(path.with_name('user-renamed.PNG'))
            return {}
        self.assertEqual(self.save(rename), 'skipped_user_changed')
        self.assertTrue((self.target / 'user-renamed.PNG').exists())

    def test_stop_during_ocr_defers_rename(self):
        def stop(*_):
            config = read_json(self.config)
            config['enabled'] = False
            atomic_json(self.config, config)
            return {}
        self.assertEqual(self.save(stop), 'saved_review_deferred')
        self.assertIn('识别中', self.image().name)

    def test_ocr_amount_and_coupon_date_never_become_facts(self):
        fields = metadata(ocr_rows('淘宝订单详情', '共减 50.00 元', '有效期至2026-01-20', '实付款 99.00'))
        self.assertIsNone(fields['date'])
        self.assertIsNone(fields['amount'])
        fields.update(amount='50', amount_verified=True)
        name = make_filename(fields, '.PNG', 'a' * 64)
        self.assertNotIn('实付50', name)
        self.assertNotIn('99', name)
        self.assertNotIn('2026-01-20', name)

    def test_labelled_order_date_and_tail_are_hints(self):
        fields = metadata(ocr_rows('天猫订单详情', '纯棉长袖宽松衬衫', '创建时间2026-01-02', '订单编号1234567890123456'))
        self.assertEqual(fields['date'], '2026-01-02')
        self.assertEqual(fields['platform'], '天猫')
        self.assertIn('尾号123456', make_filename(fields, '.PNG', 'b' * 64))

    def test_wrong_file_signature_is_rejected(self):
        self.source.write_bytes(b'not-an-image')
        self.assertEqual(self.save(), 'rejected_format')
        self.assertFalse(self.target.exists())

    def test_ocr_dash_variation_is_a_provisional_date(self):
        fields = metadata(ocr_rows('天猫订单详情', '创建时间2026一01一02'))
        self.assertEqual(fields['date'], '2026-01-02')
        self.assertTrue(fields['needs_review'])

    def test_clipboard_monitor_queues_copies_independently(self):
        events, stop = queue.Queue(), threading.Event()
        second = self.source.with_name('second.PNG')
        calls = []
        def fake_clipboard(previous):
            calls.append(previous)
            if len(calls) == 1:
                return 1, [self.source]
            return 2, [second] if previous != 2 else []
        with patch('archive.clipboard_files', side_effect=fake_clipboard):
            thread = threading.Thread(target=monitor_clipboard,
                args=(self.config, self.exports, events, stop))
            thread.start()
            try:
                self.assertEqual(events.get(timeout=2), self.source)
                self.assertEqual(events.get(timeout=2), second)
            finally:
                stop.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_runtime_lock_prevents_a_second_collector(self):
        runtime = self.config.parent
        self.assertFalse(is_running(runtime))
        lock = lock_runtime(runtime)
        try:
            self.assertTrue(is_running(runtime))
            self.assertIsNone(lock_runtime(runtime))
        finally:
            lock.close()
        self.assertFalse(is_running(runtime))


if __name__ == '__main__':
    unittest.main(verbosity=2)
