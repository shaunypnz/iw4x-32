#!/usr/bin/env python3
"""IW4x-32: dependency bootstrap controls; no network or game process."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import fetch_vulkan_headers as headers


def fixture(extra=None):
    data = io.BytesIO()
    names = ['include/vulkan/vulkan.h', 'include/vulkan/vulkan_core.h',
             'include/vulkan/vk_platform.h', 'include/vulkan/vulkan_win32.h',
             'include/vk_video/vulkan_video_codecs_common.h', 'LICENSE.md']
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name in names + ([extra] if extra else []):
            body = ('fixture: ' + name).encode()
            entry = tarfile.TarInfo(f'Vulkan-Headers-{headers.VERSION}/{name}')
            entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body))
    return data.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_bad_checksum_installs_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / 'vulkan'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                headers.install(fixture(), dest)
            self.assertFalse(dest.exists())

    def test_complete_headers_install_and_repeat_without_changes(self):
        blob = fixture()
        with tempfile.TemporaryDirectory() as root, patch.object(headers, 'SHA256', hashlib.sha256(blob).hexdigest()):
            dest = Path(root) / 'vulkan'
            self.assertEqual(headers.install(blob, dest), 6)
            self.assertEqual(headers.install(blob, dest), 6)
            core = dest / 'include/vulkan/vulkan_core.h'
            core.write_text('damaged')
            with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                headers.install(blob, dest)
            self.assertEqual(core.read_text(), 'damaged')

    def test_archive_cannot_escape_destination(self):
        blob = fixture('../escape.h')
        with tempfile.TemporaryDirectory() as root, patch.object(headers, 'SHA256', hashlib.sha256(blob).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                headers.install(blob, Path(root) / 'vulkan')
            self.assertFalse((Path(root) / 'escape.h').exists())


if __name__ == '__main__':
    unittest.main()
