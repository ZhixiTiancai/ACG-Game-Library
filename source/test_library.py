import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from PySide6.QtGui import QImage, QColor

from library_store import LibraryStore, UNCATEGORIZED


def archive(path, entries=None):
    with zipfile.ZipFile(path, 'w') as out:
        for name, content in (entries or {'Robin/Robin.ini': '[Constants]\nglobal persist $x=1', 'Robin/model.buf': b'fixture'}).items():
            out.writestr(name, content)
    return path


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = LibraryStore(self.root / 'library')

    def tearDown(self): self.temp.cleanup()

    def test_default_and_custom_categories_are_per_game(self):
        self.assertEqual(self.store.categories('EFMI'), [{'id': UNCATEGORIZED, 'name': '未分类'}])
        self.store.add_category('SRMI', '知更鸟')
        self.assertEqual(len(self.store.categories('ZZMI')), 1)
        with self.assertRaises(ValueError): self.store.add_category('SRMI', '知更鸟')
        self.assertEqual(len(LibraryStore(self.store.base).categories('SRMI')), 2)

    def test_zip_import_copy_and_metadata_persistence(self):
        source = archive(self.root / 'sample.zip'); before = hashlib.sha256(source.read_bytes()).hexdigest()
        record = self.store.import_zip('SRMI', source)
        self.assertEqual(record['name'], 'Robin')
        self.assertTrue((self.store.absolute('SRMI', record['folder']) / 'Robin.ini').exists())
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        category = self.store.add_category('SRMI', '角色')
        self.store.update('SRMI', record['id'], name='新的名称', favorite=True, category_id=category['id'])
        recovered = LibraryStore(self.store.base)
        self.assertEqual(len(recovered.mods('SRMI', category['id'], True, '新')), 1)
        self.assertEqual(recovered.get('SRMI', record['id'])['name'], '新的名称')
        self.assertEqual(len(recovered.mods('ZZMI')), 0)

    def test_zip_slip_and_windows_alias_rejected(self):
        for i, name in enumerate(['../outside.ini', 'C:/outside.ini', 'folder/../outside.ini', 'folder /a.ini']):
            with self.assertRaises(ValueError): self.store.import_zip('SRMI', archive(self.root / f'bad{i}.zip', {name: 'x'}))
        self.assertFalse((self.root / 'outside.ini').exists())
        self.assertEqual(self.store.mods('SRMI'), [])

    def test_invalid_mod_and_corrupt_index_preserved(self):
        with self.assertRaises(ValueError): self.store.import_zip('SRMI', archive(self.root / 'empty.zip', {'only.txt': 'x'}))
        path = self.store.game_path('ZZMI') / '.acg-library.json'; path.parent.mkdir(parents=True)
        path.write_text('{corrupt', encoding='utf8')
        self.store.load('ZZMI')
        with self.assertRaises(ValueError): self.store.add_category('ZZMI', 'test')
        self.assertEqual(path.read_text(encoding='utf8'), '{corrupt')

    def test_invalid_metadata_cannot_damage_record(self):
        record = self.store.import_zip('SRMI', archive(self.root / 'a.zip'))
        with self.assertRaises(ValueError): self.store.update('SRMI', record['id'], name='')
        with self.assertRaises(ValueError): self.store.update('SRMI', record['id'], category_id='missing')
        self.assertEqual(record, self.store.get('SRMI', record['id']))

    def test_preview_is_an_independent_copy(self):
        record = self.store.import_zip('SRMI', archive(self.root / 'a.zip'))
        original = self.root / 'preview.png'
        image = QImage(1200, 400, QImage.Format.Format_RGB32); image.fill(QColor('red'))
        for x in range(400,800):
            for y in range(400): image.setPixelColor(x, y, QColor('blue'))
        image.save(str(original)); before = original.read_bytes()
        self.store.set_preview('SRMI', record['id'], original)
        preview = self.store.absolute('SRMI', self.store.get('SRMI', record['id'])['preview'])
        self.assertNotEqual(original, preview); self.assertEqual(before, original.read_bytes())
        cropped = QImage(str(preview)); self.assertEqual((cropped.width(),cropped.height()), (900,1200))
        self.assertEqual(preview.name, 'preview.jpg')
        self.assertEqual(preview.parent, self.store.absolute('SRMI', record['folder']))
        self.assertTrue(preview.read_bytes().startswith(b'\xff\xd8'))
        for x, y in [(0,0), (899,1199)]:
            color = cropped.pixelColor(x, y)
            self.assertGreater(color.blue(), 250); self.assertLess(color.red(), 5)

    def test_preview_replacement_has_one_jpeg_and_save_failure_restores_it(self):
        mod = self.store.import_zip('SRMI', archive(self.root/'a.zip'))
        folder = self.store.absolute('SRMI', mod['folder'])
        image = QImage(400, 600, QImage.Format.Format_ARGB32); image.fill(QColor('red'))
        source = self.root/'new.png'; image.save(str(source))
        image.save(str(folder/'preview.webp')); image.save(str(folder/'preview.png'))
        self.store.set_preview('SRMI', mod['id'], source)
        self.assertEqual(sorted(p.name for p in folder.glob('preview.*')), ['preview.jpg'])
        old = (folder/'preview.jpg').read_bytes()
        image.fill(QColor('blue')); image.save(str(source))
        with patch.object(self.store, 'save', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): self.store.set_preview('SRMI', mod['id'], source)
        self.assertEqual((folder/'preview.jpg').read_bytes(), old)
        self.store.set_preview('SRMI', mod['id'], source)
        self.assertNotEqual((folder/'preview.jpg').read_bytes(), old)
        self.assertEqual(sorted(p.name for p in folder.glob('preview.*')), ['preview.jpg'])

    def test_refresh_discovers_manual_folders_preserves_choices_and_removes_missing(self):
        mod = self.store.import_zip('SRMI', archive(self.root/'a.zip'))
        category = self.store.add_category('SRMI', '知更鸟')
        self.store.update('SRMI', mod['id'], favorite=True, category_id=category['id'])
        target = self.target(); self.store.set_enabled('SRMI', mod['id'], True, target)
        manual = self.store.game_path('SRMI')/'Mods'/'手动放入'; (manual/'nested').mkdir(parents=True)
        (manual/'nested'/'test.INI').write_text('[Constants]')
        image = QImage(90,120,QImage.Format.Format_RGB32); image.fill(QColor('green')); image.save(str(manual/'preview.jpg'))
        unrelated = manual.parent/'普通文件夹'; unrelated.mkdir(); (unrelated/'notes.txt').write_text('keep')
        result = self.store.refresh_from_disk('SRMI')
        self.assertEqual(result['added'], 1)
        current = self.store.get('SRMI', mod['id'])
        self.assertEqual(current['category_id'], category['id']); self.assertTrue(current['favorite'])
        self.assertTrue(self.store.is_enabled('SRMI', mod['id']))
        found = self.store.mods('SRMI', UNCATEGORIZED)[0]
        self.assertEqual(found['name'], '手动放入')
        self.assertEqual(self.store.absolute('SRMI',found['preview']), manual/'preview.jpg')
        self.assertEqual(self.store.mods('ZZMI'), [])
        self.assertEqual(self.store.refresh_from_disk('SRMI')['added'], 0)
        # Simulate a folder moved out by the user; never delete its files.
        self.store.absolute('SRMI',mod['folder']).rename(self.root/'moved')
        result = self.store.refresh_from_disk('SRMI')
        self.assertEqual(result['removed'], 1); self.assertIsNone(self.store.get('SRMI',mod['id']))
        self.assertFalse(__import__('deployment').is_link(target/'Robin'))
        self.assertTrue((self.root/'moved'/'Robin.ini').is_file())

    def test_import_detects_jpeg_and_migrates_legacy_preview(self):
        image = QImage(90,120,QImage.Format.Format_RGB32); image.fill(QColor('red'))
        source = self.root/'cover.jpg'; image.save(str(source))
        mod = self.store.import_zip('SRMI', archive(self.root/'with-preview.zip', {
            'Robin/Robin.ini': '[Constants]', 'Robin/preview.jpg': source.read_bytes(),
            'Robin/preview.png': b'obsolete'}))
        folder = self.store.absolute('SRMI',mod['folder'])
        self.assertEqual(self.store.absolute('SRMI',mod['preview']),folder/'preview.jpg')
        self.assertFalse((folder/'preview.png').exists())
        legacy = self.store.game_path('SRMI')/'.previews'/'old.png'; legacy.parent.mkdir()
        image.save(str(legacy)); (folder/'preview.jpg').unlink()
        self.store.update('SRMI',mod['id'],preview='.previews/old.png')
        self.store.refresh_from_disk('SRMI')
        self.assertTrue((folder/'preview.jpg').is_file()); self.assertFalse(legacy.exists())
        (folder/'preview.jpg').unlink()
        self.store.refresh_from_disk('SRMI')
        self.assertEqual(self.store.get('SRMI',mod['id'])['preview'], '')

    def target(self):
        target = self.root / 'XXMI' / 'SRMI' / 'Mods'
        target.parent.mkdir(parents=True, exist_ok=True)
        (target.parent/'d3dx.ini').write_text('[Include]')
        return target

    def test_multiple_mods_same_category_and_independent_stop(self):
        one = self.store.import_zip('SRMI', archive(self.root/'a.zip'))
        two = self.store.import_zip('SRMI', archive(self.root/'b.zip'))
        self.assertEqual(Path(one['folder']).name, 'Robin')
        self.assertEqual(Path(two['folder']).name, 'Robin (2)')
        target = self.target()
        for mod in [one,two]: self.store.set_enabled('SRMI', mod['id'], True, target)
        recovered = LibraryStore(self.store.base)
        self.assertTrue(recovered.is_enabled('SRMI', one['id']))
        self.assertTrue(recovered.is_enabled('SRMI', two['id']))
        recovered.set_enabled('SRMI', one['id'], False)
        self.assertFalse(recovered.is_enabled('SRMI', one['id']))
        self.assertTrue(recovered.is_enabled('SRMI', two['id']))
        self.assertTrue(self.store.absolute('SRMI',one['folder']).is_dir())
        recovered.set_enabled('SRMI', two['id'], False)

    def test_foreign_real_directory_is_never_replaced_or_removed(self):
        mod = self.store.import_zip('SRMI', archive(self.root/'a.zip'))
        target = self.target(); existing = target/'Robin'; existing.mkdir(parents=True); (existing/'keep.txt').write_text('foreign')
        with self.assertRaises(ValueError): self.store.set_enabled('SRMI',mod['id'],True,target)
        self.assertEqual((existing/'keep.txt').read_text(),'foreign')
        self.assertFalse(self.store.is_enabled('SRMI',mod['id']))

    def test_rename_active_mod_updates_folder_and_link_without_editing_ini(self):
        mod = self.store.import_zip('SRMI',archive(self.root/'a.zip'))
        original = self.store.absolute('SRMI',mod['folder'])/'Robin.ini'; content=original.read_bytes()
        target = self.target(); self.store.set_enabled('SRMI',mod['id'],True,target)
        updated = self.store.update('SRMI',mod['id'],name='知更鸟: 赛服')
        self.assertEqual(Path(updated['folder']).name,'知更鸟_ 赛服')
        self.assertFalse((target/'Robin').exists())
        self.assertTrue((target/'知更鸟_ 赛服'/'Robin.ini').is_file())
        self.assertTrue(self.store.is_enabled('SRMI',mod['id']))
        self.assertEqual((self.store.absolute('SRMI',updated['folder'])/'Robin.ini').read_bytes(),content)
        self.store.set_enabled('SRMI',mod['id'],False)

    def test_save_failure_rolls_back_enable_and_active_rename(self):
        mod=self.store.import_zip('SRMI',archive(self.root/'a.zip'));target=self.target()
        with patch.object(self.store,'save',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): self.store.set_enabled('SRMI',mod['id'],True,target)
        self.assertFalse((target/'Robin').exists());self.assertFalse(self.store.is_enabled('SRMI',mod['id']))
        self.store.set_enabled('SRMI',mod['id'],True,target)
        with patch.object(self.store,'save',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): self.store.update('SRMI',mod['id'],name='Other')
        self.assertTrue(self.store.is_enabled('SRMI',mod['id']));self.assertTrue((target/'Robin').is_dir())
        self.assertEqual(self.store.get('SRMI',mod['id'])['name'],'Robin')
        self.assertFalse((target/'Other').exists());self.store.set_enabled('SRMI',mod['id'],False)

    def test_legacy_folder_migration_is_idempotent(self):
        mod=self.store.import_zip('SRMI',archive(self.root/'a.zip'))
        folder=self.store.absolute('SRMI',mod['folder']);old=folder.parent/mod['id'];folder.rename(old)
        self.store.load('SRMI')['mods'][0]['folder']=old.relative_to(self.store.game_path('SRMI')).as_posix();self.store.save('SRMI')
        fresh=LibraryStore(self.store.base);fresh.normalize_library('SRMI');first=fresh.get('SRMI',mod['id'])
        fresh.normalize_library('SRMI');self.assertEqual(first,fresh.get('SRMI',mod['id']))
        self.assertEqual(Path(first['folder']).name,'Robin')


if __name__ == '__main__': unittest.main(verbosity=2)
