"""Public, synthetic archive-contract tests. No production imports or model assets."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import tarfile
import tempfile
import unittest

MANIFEST = 'native-proof-inventory.json'
FIELDS = ('path', 'sha256', 'sizeBytes', 'mode')

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def safe(name: str) -> str:
    if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))
            or PurePosixPath(name).as_posix() != name):
        raise ValueError(f'Unsafe archive path: {name!r}')
    return name

def source_inventory(root: Path) -> list[dict]:
    entries = []
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Source symlink forbidden')
        if path.is_file():
            name = safe(path.relative_to(root).as_posix())
            if name == MANIFEST:
                raise ValueError('Manifest filename reserved')
            st = path.stat()
            if st.st_mode & 0o7000:
                raise ValueError('Special-mode source file forbidden')
            blob = path.read_bytes()
            entries.append(dict(path=name, sha256=sha(blob), sizeBytes=len(blob), mode=st.st_mode & 0o777))
    return sorted(entries, key=lambda item: item['path'])

def make_archive(root: Path, archive: Path) -> dict:
    entries = source_inventory(root)
    index = {'schemaVersion': 1, 'platform': 'macos-x64', 'purpose': 'synthetic-archive-test', 'files': entries}
    raw = (json.dumps(index, indent=2, sort_keys=True) + '\n').encode()
    with archive.open('xb') as out, gzip.GzipFile(filename='', mode='wb', fileobj=out, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w|') as tar:
            for item in entries + [dict(path=MANIFEST, sizeBytes=len(raw), mode=0o644)]:
                ti = tarfile.TarInfo(item['path'])
                ti.size = item['sizeBytes']
                ti.mode = item['mode']
                ti.mtime = 0
                data = raw if item['path'] == MANIFEST else (root / item['path']).read_bytes()
                tar.addfile(ti, io.BytesIO(data))
    blob = archive.read_bytes()
    return {'sha256': sha(blob), 'sizeBytes': len(blob), 'inventorySha256': sha(raw)}

def diff(expected: list[dict], actual: list[dict]) -> None:
    by_path_expected = {safe(x['path']): x for x in expected}
    by_path_actual = {safe(x['path']): x for x in actual}
    if len(by_path_expected) != len(expected):
        raise ValueError('Duplicate manifest path')
    for name in sorted(set(by_path_expected) | set(by_path_actual)):
        if name not in by_path_expected:
            raise ValueError(f'Unexpected file: {name}')
        if name not in by_path_actual:
            raise ValueError(f'Missing file: {name}')
        for field in FIELDS[1:]:
            if by_path_expected[name].get(field) != by_path_actual[name].get(field):
                raise ValueError(f'File {name}: {field} mismatch expected={by_path_expected[name].get(field)!r} actual={by_path_actual[name].get(field)!r}')

def extract_archive(archive: Path, target: Path, receipt: dict, *, limits=(200, 16 * 1024 * 1024)) -> dict:
    if target.exists():
        raise ValueError('Destination already exists')
    blob = archive.read_bytes()
    if len(blob) != receipt['sizeBytes'] or sha(blob) != receipt['sha256']:
        raise ValueError('Archive digest/size mismatch')
    # Validate all members in memory before creating the destination. Fixture size is bounded.
    records = []
    folded = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        for member in tar:
            name = safe(member.name)
            if (not member.isfile() or member.mode & 0o7000 or member.mode & ~0o777
                    or name.casefold() in folded):
                raise ValueError('Unsafe, special-mode or duplicate archive member')
            folded.add(name.casefold())
            total += member.size
            if len(records) + 1 > limits[0] or total > limits[1]:
                raise ValueError('Fixture archive resource limit exceeded')
            data = tar.extractfile(member).read()
            if len(data) != member.size:
                raise ValueError('Truncated archive member')
            records.append((name, data, member.mode & 0o777))
    meta = [record for record in records if record[0] == MANIFEST]
    if len(meta) != 1 or sha(meta[0][1]) != receipt['inventorySha256']:
        raise ValueError('Manifest digest mismatch')
    index = json.loads(meta[0][1])
    if (index.get('schemaVersion') != 1 or index.get('platform') != 'macos-x64'
            or index.get('purpose') != 'synthetic-archive-test' or not isinstance(index.get('files'), list)):
        raise ValueError('Manifest schema mismatch')
    actual = [dict(path=name, sha256=sha(data), sizeBytes=len(data), mode=mode)
              for name, data, mode in records if name != MANIFEST]
    diff(index['files'], actual)
    target.mkdir(parents=True)
    for name, data, mode in records:
        if name == MANIFEST:
            continue
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as out:
            out.write(data)
        path.chmod(mode)
    diff(index['files'], source_inventory(target))
    return index

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / 'source'
        self.src.mkdir()
        self.fixture = {
            'runtime/python/macos-x64/bin/python': (b'#!/bin/sh\necho fixture\n', 0o755),
            'runtime/python/macos-x64/lib/a/config.py': (b'print(1)\n', 0o644),
            'runtime/python/macos-x64/lib/a.txt': (b'example\x00binary', 0o644),
            'runtime/python/macos-x64/lib/libtorch.dylib': (bytes(range(256)), 0o755),
            'library/whisper/macos-x64/bin/whisper-cli': (b'fake whisper fixture', 0o755),
            'proof-licenses/LICENSE.txt': (b'Synthetic license text\n', 0o644),
        }
        for name, (data, mode) in self.fixture.items():
            p = self.src / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            p.chmod(mode)
        self.archive = self.base / 'runtime.tar.gz'
        self.receipt = make_archive(self.src, self.archive)

    def test_roundtrip_nested_files_hash_and_modes(self):
        target = self.base / 'extracted'
        extract_archive(self.archive, target, self.receipt)
        self.assertEqual(source_inventory(target), source_inventory(self.src))
        self.assertTrue((target/'runtime/python/macos-x64/bin/python').stat().st_mode & 0o111)

    def test_canonical_sort_is_path_string_order(self):
        names = [x['path'] for x in source_inventory(self.src)]
        self.assertEqual(names, sorted(names))
        self.assertLess(names.index('runtime/python/macos-x64/lib/a.txt'), names.index('runtime/python/macos-x64/lib/a/config.py'))

    def test_order_independent_compare(self):
        entries = source_inventory(self.src)
        diff(entries, entries[::-1])

    def test_hash_field_diagnostic(self):
        entries = source_inventory(self.src)
        altered = [dict(x) for x in entries]
        altered[0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'sha256 mismatch'):
            diff(entries, altered)

    def test_mode_field_diagnostic(self):
        entries = source_inventory(self.src)
        altered = [dict(x) for x in entries]
        altered[0]['mode'] ^= 0o111
        with self.assertRaisesRegex(ValueError, 'mode mismatch'):
            diff(entries, altered)

    def test_size_field_diagnostic(self):
        entries = source_inventory(self.src)
        altered = [dict(x) for x in entries]
        altered[0]['sizeBytes'] += 1
        with self.assertRaisesRegex(ValueError, 'sizeBytes mismatch'):
            diff(entries, altered)

    def test_missing_and_extra_paths(self):
        entries = source_inventory(self.src)
        with self.assertRaisesRegex(ValueError, 'Missing file'):
            diff(entries, entries[:-1])
        with self.assertRaisesRegex(ValueError, 'Unexpected file'):
            diff(entries[:-1], entries)

    def test_archive_digest_rejects_tampering(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'X')
        with self.assertRaisesRegex(ValueError, 'Archive digest/size mismatch'):
            extract_archive(self.archive, self.base/'out', self.receipt)

    def test_path_traversal_rejected(self):
        for name in ('../escape', '/tmp/escape', 'a/../b', 'a\\b', 'C:/escape', 'a//b', 'a/./b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe(name)

    def test_symlink_and_special_mode_source_rejected(self):
        p = self.src/'link'
        try:
            p.symlink_to('proof-licenses/LICENSE.txt')
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on host')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            source_inventory(self.src)
        p.unlink()
        p = self.src/'runtime/python/macos-x64/bin/python'
        p.chmod(0o4755)
        with self.assertRaisesRegex(ValueError, 'Special-mode'):
            source_inventory(self.src)

    def test_duplicate_casefold_rejected(self):
        # Separate handcrafted archive to check member policy, with correct outer digest.
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as tar:
            for name in ('A/file', 'a/FILE'):
                data = b'x'
                m = tarfile.TarInfo(name)
                m.size = len(data)
                tar.addfile(m, io.BytesIO(data))
        self.archive.write_bytes(stream.getvalue())
        self.receipt = dict(sha256=sha(stream.getvalue()), sizeBytes=len(stream.getvalue()), inventorySha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            extract_archive(self.archive, self.base/'out', self.receipt)

    def test_no_overwrite(self):
        out = self.base/'out'
        out.mkdir()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            extract_archive(self.archive, out, self.receipt)

    def test_repeatable_archive_bytes(self):
        second = self.base/'again.tar.gz'
        make_archive(self.src, second)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())

if __name__ == '__main__':
    print('PUBLIC SYNTHETIC TEST HARNESS — no production assets')
    print('platform:', platform.platform(), 'machine:', platform.machine())
    unittest.main(verbosity=2)
