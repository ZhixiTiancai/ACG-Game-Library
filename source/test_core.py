import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from acg_core import Settings, inspect_installation, discover_installations, open_xxmi
import acg_core


def fixture(root, version='2.4.9', games=('SRMI', 'ZZMI', 'EFMI')):
    exe = root / 'Resources' / 'Bin' / 'XXMI Launcher.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'test fixture, never executable')
    (root / 'XXMI Launcher Config.json').write_text(json.dumps({'Packages': {'packages': {'Launcher': {'deployed_version': version}}}}), encoding='utf8')
    for game in games:
        (root / game).mkdir()
        (root / game / 'd3dx.ini').write_text('[Include]', encoding='utf8')
    return exe


class CoreTests(unittest.TestCase):
    def test_appearance_preferences_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); settings = Settings(root)
            settings.values.update(theme_color='blue',theme_transparency=65,background_path=str(root/'background.png'))
            settings.save(); self.assertEqual(Settings(root).values,settings.values)
            settings.values.update(theme_color='invalid',theme_transparency=500); settings.save()
            recovered=Settings(root)
            self.assertEqual(recovered.values['theme_color'],'purple')
            self.assertEqual(recovered.values['theme_transparency'],100)

    def test_settings_survive_restart_and_paths_with_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / '测试 空间'
            settings = Settings(root)
            settings.values.update(game='EFMI', xxmi_root='E:/XXMI 测试', scan_on_start=False)
            settings.save()
            recovered = Settings(root)
            self.assertEqual(recovered.values, settings.values)
            self.assertEqual(recovered.library_path('EFMI'), root / 'Library' / 'EFMI')
            self.assertFalse(settings.path.with_suffix('.json.tmp').exists())

    def test_malformed_settings_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'data').mkdir()
            (root / 'data/settings.json').write_text('{invalid', encoding='utf8')
            settings = Settings(root)
            self.assertTrue(settings.load_error)
            self.assertEqual(settings.values['game'], 'SRMI')

    def test_invalid_types_do_not_replace_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'data').mkdir()
            (root / 'data/settings.json').write_text(json.dumps({'game': 'WWMI', 'scan_on_start': 'false', 'library_root': None}), encoding='utf8')
            settings = Settings(root)
            self.assertEqual(settings.values['game'], 'SRMI')
            self.assertTrue(settings.values['scan_on_start'])
            self.assertEqual(settings.library_path('ZZMI'), root / 'Library/ZZMI')

    def test_root_exe_and_bin_resolve_to_same_instance_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'XXMI 测试'; exe = fixture(root)
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for path in [root, exe, exe.parent]:
                instance = inspect_installation(path)
                self.assertEqual(instance.root, root)
                self.assertEqual(instance.games, ('SRMI', 'ZZMI', 'EFMI'))
                self.assertEqual(instance.target('EFMI'), root / 'EFMI/Mods')
            after = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((root / 'EFMI/Mods').exists())

    def test_unrelated_exe_and_incomplete_layout_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); exe = fixture(root)
            wrong = exe.parent / 'Other.exe'; wrong.write_bytes(b'')
            self.assertIsNone(inspect_installation(wrong))
            (root / 'XXMI Launcher Config.json').unlink()
            for g in ['SRMI', 'ZZMI', 'EFMI']:
                (root / g / 'd3dx.ini').unlink()
            self.assertIsNone(inspect_installation(root))

    def test_discovery_skips_mod_contents_and_orders_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture(base / 'Tool1/XXMI', version='2.2.1')
            fixture(base / 'Tool2/Portable', version='2.4.9')
            fixture(base / 'ModLibrary/Fake', version='99.0.0')
            found = discover_installations([base, base], max_depth=4)
            self.assertEqual(len(found), 2)
            self.assertEqual(found[0].version, '2.4.9')
            self.assertEqual(discover_installations([base], max_depth=0), [])

    def test_only_supported_importer_passed_without_shell_or_auto_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); exe = fixture(root)
            instance = inspect_installation(root)
            with patch.object(acg_core, 'shell_launch') as process:
                open_xxmi(instance, 'EFMI')
                process.assert_called_once_with(exe, ['--xxmi', 'EFMI'], exe.parent)
                with self.assertRaises(ValueError):
                    open_xxmi(instance, 'WWMI')
            exe.unlink()
            with self.assertRaises(ValueError):
                open_xxmi(instance, 'SRMI')


if __name__ == '__main__':
    unittest.main(verbosity=2)
