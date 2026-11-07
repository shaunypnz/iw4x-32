#!/usr/bin/env python3
"""IW4x-32: install the pinned public Vulkan C headers for a clean build."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import urllib.request

VERSION = '1.3.290'
SHA256 = 'f38a653bf93cab7a2a229a53d2d53b1cba9a2819e4c0a7de13c54085bde9bcf5'
URL = f'https://codeload.github.com/KhronosGroup/Vulkan-Headers/tar.gz/refs/tags/v{VERSION}'
ROOT = Path(__file__).resolve().parents[2]


def install(blob, destination):
    if hashlib.sha256(blob).hexdigest() != SHA256:
        raise ValueError('Vulkan archive checksum mismatch; nothing installed')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != f'Vulkan-Headers-{VERSION}':
                raise ValueError('unexpected archive root')
            relative = PurePosixPath(*parts[1:])
            if '..' in relative.parts:
                raise ValueError('unsafe archive path')
            header = (len(relative.parts) == 3 and relative.parts[0] == 'include'
                      and relative.parts[1] in ('vulkan', 'vk_video') and relative.suffix == '.h')
            license_file = str(relative) == 'LICENSE.md' or relative.parts[:1] == ('LICENSES',)
            if (header or license_file) and member.isfile():
                files[relative] = archive.extractfile(member).read()
    required = ['include/vulkan/vulkan.h', 'include/vulkan/vulkan_core.h',
                'include/vulkan/vk_platform.h', 'include/vulkan/vulkan_win32.h',
                'include/vk_video/vulkan_video_codecs_common.h', 'LICENSE.md']
    if any(PurePosixPath(name) not in files for name in required):
        raise ValueError('pinned Vulkan header set is incomplete')
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        if (not destination.is_symlink() and all(not (destination / name).is_symlink()
                and (destination / name).is_file() and (destination / name).read_bytes() == data
                for name, data in files.items())):
            return len(files)
        raise ValueError('existing Vulkan directory differs; refusing to overwrite it')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vulkan-', dir=destination.parent) as scratch:
        stage = Path(scratch) / 'headers'
        stage.mkdir()
        for relative, data in files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        stage.rename(destination)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='use an already downloaded pinned archive')
    parser.add_argument('--dest', type=Path, default=ROOT / 'deps' / 'vulkan')
    args = parser.parse_args()
    blob = args.archive.read_bytes() if args.archive else urllib.request.urlopen(URL, timeout=60).read()
    count = install(blob, args.dest)
    print(f'Verified Vulkan-Headers {VERSION}: {count} C header/license files, sha256 {SHA256}')


if __name__ == '__main__':
    main()
