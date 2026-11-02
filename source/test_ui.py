import tempfile
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest

from acg_core import Settings, inspect_installation
from main import Window, STYLE
from test_library import archive
from test_core import fixture
from library_store import UNCATEGORIZED
from appearance import THEMES, theme_palette
from library_ui import category_sort_key
from updater import Release


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion'); cls.app.setStyleSheet(STYLE)

    def test_update_panel_check_download_and_install_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); w=Window(Settings(root),scan=False); w.show(); w.navigate(1)
            panel=w.update_panel
            def finished():
                for _ in range(100):
                    QTest.qWait(20)
                    if not panel.busy(): break
                self.app.processEvents(); self.assertFalse(panel.busy())
            with patch('update_ui.check_latest',return_value=None):
                panel.start_check(); finished()
            self.assertIn('暂未发布',panel.status.text()); self.assertFalse(panel.action_button.isEnabled())
            release=Release('9.0.0','https://github.com/ZhixiTiancai/ACG-Game-Library/releases/tag/v9.0.0','test.zip','',100,'a'*64,'','测试发行说明')
            with patch('update_ui.check_latest',return_value=release):
                QTest.mouseClick(panel.check_button,Qt.MouseButton.LeftButton); finished()
            self.assertTrue(panel.action_button.isEnabled()); self.assertIn('9.0.0',panel.status.text())
            self.assertEqual(panel.notes.text(),'测试发行说明')
            plan=root/'install-plan.json'; plan.write_text('{}')
            with patch('update_ui.download_release',return_value=plan):
                QTest.mouseClick(panel.action_button,Qt.MouseButton.LeftButton); finished()
            self.assertEqual(panel.action_button.text(),'安装并重启')
            self.assertEqual(panel.progress.value(),100)
            with patch.object(sys,'frozen',True,create=True), patch('update_ui.launch_installer') as install:
                QTest.mouseClick(panel.action_button,Qt.MouseButton.LeftButton)
                install.assert_called_once_with(plan)
            self.assertFalse(w.isVisible()); self.app.processEvents()

    def test_symbol_then_latin_then_han_category_sort(self):
        names = ['知更鸟','Alpha','三月七','UI','! 特别','[置顶]','NPC','beta']
        categories = [{'id':str(index),'name':name} for index,name in enumerate(names)]
        categories.append({'id':UNCATEGORIZED,'name':'未分类'})
        ordered = [cat['name'] for cat in sorted(categories,key=category_sort_key)]
        self.assertEqual(ordered,['未分类','! 特别','[置顶]','Alpha','beta','NPC','UI','三月七','知更鸟'])

    def test_theme_controls_background_transparency_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); w=Window(Settings(root),scan=False); w.show(); w.navigate(1); self.app.processEvents()
            backgrounds = []
            for key,(_,accent,_) in THEMES.items():
                QTest.mouseClick(w.theme_buttons[key],Qt.MouseButton.LeftButton); self.app.processEvents()
                self.assertEqual(w.settings.values['theme_color'],key)
                self.assertTrue(w.theme_buttons[key].isChecked())
                self.assertIn(accent,w.styleSheet())
                sample = w.library_view.refresh_button.grab().toImage().pixelColor(10,w.library_view.refresh_button.height()//2)
                self.assertEqual(sample.name(),accent)
                # This blank page margin must change with the full theme too.
                base = w.background_surface.grab().toImage().pixelColor(230,18)
                self.assertEqual(base.name(),theme_palette(key)['background'])
                backgrounds.append(base.name())
                if key == 'white': self.assertGreater(base.lightness(),230)
                if key == 'black': self.assertLess(base.lightness(),25)
            self.assertEqual(len(set(backgrounds)),7)
            w.set_theme_color('blue')
            image=QImage(700,400,QImage.Format.Format_RGB32); image.fill(QColor('#d8ac7a'))
            original=root/'original.png'; image.save(str(original)); original_bytes=original.read_bytes()
            self.assertTrue(w.set_background_file(original))
            copy=Path(w.settings.values['background_path'])
            self.assertNotEqual(copy,original); self.assertTrue(copy.is_file())
            self.assertEqual(original.read_bytes(),original_bytes)
            self.assertEqual(w.settings.values['theme_transparency'],40)
            self.assertFalse(w.background_surface.image.isNull())
            w.transparency_slider.setValue(75); QTest.qWait(200)
            self.assertEqual(w.background_surface.transparency,75)
            self.assertEqual(Settings(root).values['theme_transparency'],75)
            before=w.background_surface.grab().toImage().pixelColor(230,18)
            w.transparency_slider.setValue(0); QTest.qWait(200)
            opaque=w.background_surface.grab().toImage().pixelColor(230,18)
            self.assertGreater(before.lightness(),opaque.lightness())
            bad=root/'bad.png'; bad.write_bytes(b'bad image')
            self.assertFalse(w.set_background_file(bad)); self.assertEqual(w.settings.values['background_path'],str(copy))
            self.assertTrue(w.set_background_file(original)); replacement=Path(w.settings.values['background_path'])
            self.assertFalse(copy.exists()); self.assertTrue(replacement.exists())
            w.transparency_slider.setValue(55); w.close(); self.app.processEvents()
            restored=Window(Settings(root),scan=False)
            self.assertEqual(restored.settings.values['theme_color'],'blue')
            self.assertEqual(restored.background_surface.transparency,55)
            self.assertFalse(restored.background_surface.image.isNull())
            restored.clear_background()
            self.assertTrue(restored.background_surface.image.isNull()); self.assertFalse(replacement.exists())
            self.assertTrue(original.exists()); restored.close(); self.app.processEvents()

    def test_vertical_categories_pinyin_search_and_independent_mod_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Window(Settings(Path(tmp)), scan=False); view = w.library_view
            named = {}
            for name in ['知更鸟', 'UI', '三月七', 'Saber', 'NPC']:
                named[name] = w.store.add_category('SRMI', name)['id']
            for index in range(20): w.store.add_category('SRMI', f'Z 分类 {index:02}')
            data = w.store.load('SRMI')
            for index in range(30):
                data['mods'].append({'id':f'test{index}', 'name':f'MOD {index}', 'folder':f'Mods/Test{index}',
                    'category_id':UNCATEGORIZED, 'favorite':False, 'preview':'', 'deployment':None})
            w.store.save('SRMI'); view.refresh(); w.show(); QTest.qWait(150)
            # Check Chinese/Latin order directly without the extra scrolling fixtures.
            order = [key for key in view.category_buttons if key == UNCATEGORIZED or key in named.values()]
            self.assertEqual(order, [UNCATEGORIZED,named['NPC'],named['Saber'],named['UI'],named['三月七'],named['知更鸟']])
            buttons = list(view.category_buttons.values())
            self.assertTrue(all(a.x() == b.x() and a.y() < b.y() for a,b in zip(buttons,buttons[1:])))
            self.assertGreater(view.categories_scroll.verticalScrollBar().maximum(), 0)
            mod_scroll = view.mod_scroll.verticalScrollBar().value()
            view.categories_scroll.verticalScrollBar().setValue(200); self.app.processEvents()
            self.assertEqual(view.mod_scroll.verticalScrollBar().value(), mod_scroll)
            view.category_search.setText('zgn'); self.app.processEvents()
            self.assertEqual(list(view.category_buttons), [named['知更鸟']])
            self.assertEqual(len(view.mod_buttons), 30)
            QTest.mouseClick(view.category_buttons[named['知更鸟']],Qt.MouseButton.LeftButton)
            self.assertEqual(view.category, named['知更鸟']); self.assertEqual(len(view.mod_buttons), 0)
            self.app.processEvents(); self.assertGreater(view.category_title.width(),100)
            view.category_search.setText('no such category'); self.app.processEvents()
            self.assertEqual(view.category_buttons, {})
            self.assertEqual(view.category, named['知更鸟'])
            view.category_search.clear(); view.select_category(UNCATEGORIZED)
            for width, expected in [(1120,2),(1320,3)]:
                w.resize(width,860); QTest.qWait(180)
                self.assertEqual(view.columns,expected)
                for button in view.mod_buttons.values():
                    card=button.parentWidget()
                    self.assertGreaterEqual(card.x(),0)
                    self.assertLessEqual(card.x()+card.width(),view.mod_scroll.viewport().width())
                self.assertEqual(view.mod_scroll.horizontalScrollBar().maximum(),0)
            w.close(); self.app.processEvents()

    def test_refresh_button_discovers_and_reloads_cover_and_startup_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); settings = Settings(root)
            folder = Path(settings.values['library_root'])/'SRMI'/'Mods'/'手动模组'
            folder.mkdir(parents=True); (folder/'model.ini').write_text('[Constants]')
            w = Window(settings, scan=False); w.show(); self.app.processEvents()
            self.assertEqual(len(w.store.mods('SRMI')), 1)
            mod = w.store.mods('SRMI')[0]
            image = QImage(90,120,QImage.Format.Format_RGB32); image.fill(QColor('red')); image.save(str(folder/'preview.jpg'))
            QTest.mouseClick(w.library_view.refresh_button, Qt.MouseButton.LeftButton); self.app.processEvents()
            photo = w.library_view.mod_buttons[mod['id']].findChild(__import__('library_ui').Photo)
            self.assertGreater(photo.original.toImage().pixelColor(0,0).red(), 245)
            image.fill(QColor('blue')); image.save(str(folder/'preview.jpg'))
            QTest.mouseClick(w.library_view.refresh_button, Qt.MouseButton.LeftButton); self.app.processEvents()
            photo = w.library_view.mod_buttons[mod['id']].findChild(__import__('library_ui').Photo)
            self.assertGreater(photo.original.toImage().pixelColor(0,0).blue(), 245)
            # Footer launch stays at the bottom right, independently of the page.
            point = w.launch_button.mapTo(w, w.launch_button.rect().center())
            refresh_point = w.library_view.refresh_button.mapTo(w, w.library_view.refresh_button.rect().center())
            self.assertGreater(point.x(), w.width()-160); self.assertGreater(point.y(), w.height()-65)
            self.assertLess(refresh_point.y(), 150)
            w.close(); self.app.processEvents()

    def test_category_detail_round_trip_and_game_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); w = Window(Settings(root), scan=False)
            record = w.store.import_zip('SRMI', archive(root/'sample.zip'))
            w.library_view.refresh(); w.show(); self.app.processEvents()
            QTest.mouseClick(w.library_view.mod_buttons[record['id']], Qt.MouseButton.LeftButton)
            self.assertEqual(w.stack.currentIndex(), 2)
            w.detail.name.setText('知更鸟 · 测试名称'); QTest.mouseClick(w.detail.save_name_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(w.detail.favorite, Qt.MouseButton.LeftButton)
            category = w.store.add_category('SRMI', '角色测试')
            w.detail.show_mod('SRMI', record['id'])
            self.assertNotEqual(w.detail.categories.findData(category['id']), -1)
            w.detail.categories.setCurrentIndex(w.detail.categories.findData(category['id']))
            image = QImage(500, 300, QImage.Format.Format_RGB32); image.fill(QColor('#a29acb')); image_path=root/'test.png'; image.save(str(image_path))
            w.detail.set_preview_file(image_path)
            self.assertFalse(w.detail.photo.original.isNull())
            w.back_to_category()
            self.assertEqual(w.library_view.category, category['id'])
            stored = w.store.get('SRMI', record['id'])
            self.assertTrue(stored['favorite']); self.assertEqual(stored['name'], '知更鸟 · 测试名称')
            QTest.mouseClick(w.game_buttons['EFMI'], Qt.MouseButton.LeftButton)
            self.assertEqual(w.game, 'EFMI'); self.assertEqual(w.library_view.game, 'EFMI')
            self.assertEqual(w.store.mods('EFMI'), [])
            QTest.mouseClick(w.game_buttons['SRMI'], Qt.MouseButton.LeftButton)
            self.assertEqual(w.game, 'SRMI')
            self.assertFalse(w.game_buttons['SRMI'].icon().isNull())
            fixture(root / 'XXMI')
            w.settings.values['xxmi_root'] = str(root / 'XXMI')
            w.installation = inspect_installation(root / 'XXMI')
            for game in ['SRMI', 'ZZMI', 'EFMI']:
                w.select_game(game)
                with patch('main.open_xxmi') as launcher:
                    QTest.mouseClick(w.launch_button, Qt.MouseButton.LeftButton)
                    launcher.assert_called_once_with(w.installation, game)
            w.select_game('SRMI');w.library_view.category = category['id'];w.library_view.refresh()
            QTest.mouseClick(w.library_view.use_buttons[record['id']], Qt.MouseButton.LeftButton)
            self.assertEqual(w.stack.currentIndex(),0)
            self.assertTrue(w.store.is_enabled('SRMI',record['id']))
            self.assertEqual(w.library_view.use_buttons[record['id']].text(),'停用')
            photo=w.library_view.mod_buttons[record['id']].findChild(__import__('library_ui').Photo)
            self.assertEqual((photo.width(),photo.height()),(210,280))
            self.app.processEvents()
            self.assertGreaterEqual(w.library_view.mod_buttons[record['id']].height(),326)
            card = w.library_view.mod_buttons[record['id']].parentWidget()
            viewport = w.library_view.mod_scroll.viewport()
            self.assertLessEqual(card.mapTo(viewport,card.rect().bottomRight()).y(), viewport.height())
            QTest.mouseClick(w.library_view.use_buttons[record['id']], Qt.MouseButton.LeftButton)
            self.assertFalse(w.store.is_enabled('SRMI',record['id']))
            w.close(); self.app.processEvents()


if __name__ == '__main__': unittest.main(verbosity=2)
