from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import uuid
import json

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QFrame, QStackedWidget, QLineEdit,
                              QCheckBox, QFileDialog, QScrollArea, QSizePolicy, QSlider, QButtonGroup)

from acg_core import VERSION, GAMES, Settings, app_root, inspect_installation, discover_installations, open_xxmi, LaunchCancelled
from library_store import LibraryStore
from library_ui import LibraryView, ModDetailPage
from appearance import THEMES, theme_style, theme_palette, BackgroundSurface, read_background
from update_ui import UpdatePanel


STYLE = '''
* {font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #dce0eb;}
QMainWindow, QWidget#root {background:#101218;}
QWidget#sidebar {background:#14161e; border-right:1px solid #262a35;}
QFrame#panel, QFrame#emptyPanel {background:#171a23; border:1px solid #292e3a; border-radius:14px;}
QLabel {background:transparent; border:0;}
QLabel#muted {color:#858da2; font-size:12px;}
QLabel#tiny {color:#697288; font-size:11px;}
QLabel#title {font-size:27px; font-weight:700; color:#f0f1f8;}
QLabel#sectionTitle {font-size:16px; font-weight:600; color:#e9ebf5;}
QLabel#eyebrow {font-size:10px; font-weight:600; color:#777f96; letter-spacing:2px;}
QPushButton {background:#202530; border:1px solid #33394a; padding:10px 16px; border-radius:8px; font-weight:500;}
QPushButton:hover {background:#2a3040; border-color:#555572;}
QPushButton:pressed {background:#333950;}
QPushButton:disabled {background:#1d202a; color:#626a7e; border-color:#2b303d;}
QPushButton#primary {background:#aa96f4; color:#171320; border:1px solid #aa96f4; font-weight:700;}
QPushButton#primary:hover {background:#beadff;}
QPushButton#primary:disabled {background:#333047; color:#7e748e; border-color:#39354b;}
QPushButton#nav {text-align:left; background:transparent; border:1px solid transparent; padding:13px 17px; color:#929bb1; font-weight:500;}
QPushButton#nav:hover {background:#202330; color:#e0e3ed;}
QPushButton#nav:checked {background:#2b263e; border-color:#433855; color:#c8b4ff;}
QPushButton#filter {background:transparent; border:0; border-radius:0; color:#7d879d; padding:10px 2px;}
QPushButton#filter:checked {color:#c4b1ff; border-bottom:2px solid #b39af8;}
QPushButton#link {background:transparent; color:#baa8ef; border:0; padding:4px 0; text-align:left;}
QLineEdit {background:#12151d; border:1px solid #2b3140; border-radius:8px; padding:10px 12px; color:#d6dbea; selection-background-color:#59477d;}
QLineEdit:focus {border-color:#a48bdf;}
QLineEdit:read-only {color:#a0a9be;}
QCheckBox {spacing:9px; color:#c1c8d9;}
QCheckBox::indicator {width:17px; height:17px; border:1px solid #53576c; background:#171b25; border-radius:4px;}
QCheckBox::indicator:checked {background:#b09af7; border-color:#c0abff; image:none;}
QScrollArea {border:0; background:transparent;}
QScrollArea > QWidget > QWidget {background:transparent;}
QScrollBar:vertical {width:6px; background:transparent; margin:0;}
QScrollBar::handle:vertical {background:#343b4c; border-radius:3px; min-height:30px;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
QToolTip {background:#282d3c; color:#e2e5ee; border:1px solid #4b5267; padding:6px;}
QFrame#modCard {background:#191d27;border:1px solid #30374a;border-radius:12px;}
QPushButton#modOpen {background:transparent;border:0;padding:0;text-align:left;}
QPushButton#modOpen:hover {background:#202535;}
QPushButton#useMod {background:#ab95ef;color:#1e1830;border:0;padding:3px 8px;font-weight:600;}
QPushButton#useMod:hover {background:#c2adff;}
QPushButton#useActive {background:#263e37;color:#9bd8bf;border:1px solid #405f53;padding:3px 8px;}
QDialog {background:#171a23;}
QComboBox {background:#12151d;border:1px solid #353c4f;border-radius:8px;padding:10px;}
QComboBox QAbstractItemView {background:#202532;color:#dce0eb;selection-background-color:#46395d;}
QPushButton#modCard {background:#191d27;border:1px solid #2c3343;border-radius:12px;padding:0;text-align:left;}
QPushButton#modCard:hover {background:#222535;border-color:#a18cdb;}
'''


def label(text='', name='', wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def row(spacing=12):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout


def column(spacing=12):
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout


class Mark(QWidget):
    def __init__(self, kind='logo', color='#b49af8', size=46):
        super().__init__()
        self.kind, self.color = kind, color
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 64, self.height() / 64)
        c = QColor(self.color)
        bg = QColor(c); bg.setAlpha(21)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg)
        p.drawRoundedRect(0, 0, 64, 64, 17, 17)
        p.setPen(QPen(c, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.kind == 'logo':
            p.drawPolyline(QPolygonF([QPointF(16, 45), QPointF(31, 17), QPointF(47, 45)]))
            p.drawLine(24, 35, 39, 35); p.drawLine(41, 19, 48, 19)
        elif self.kind == 'SRMI':
            p.drawEllipse(16, 16, 32, 32)
            p.drawLine(12, 46, 51, 17); p.drawLine(26, 31, 44, 31)
        elif self.kind == 'ZZMI':
            p.drawPolyline(QPolygonF([QPointF(20, 19), QPointF(44, 19), QPointF(20, 45), QPointF(44, 45)]))
            p.drawLine(38, 24, 26, 40)
        elif self.kind == 'EFMI':
            p.drawPolygon(QPolygonF([QPointF(32, 13), QPointF(49, 23), QPointF(49, 41), QPointF(32, 51), QPointF(15, 41), QPointF(15, 23)]))
            p.drawLine(25, 25, 39, 25); p.drawLine(25, 32, 36, 32); p.drawLine(25, 39, 39, 39)
        else:
            p.drawRoundedRect(13, 23, 38, 27, 4, 4)
            p.drawPolyline(QPolygonF([QPointF(14, 25), QPointF(14, 17), QPointF(28, 17), QPointF(34, 23)]))
            p.drawLine(32, 30, 32, 42); p.drawLine(26, 36, 38, 36)
        p.end()


class GameCard(QPushButton):
    def __init__(self, game, callback):
        super().__init__()
        self.game = game
        self.setCheckable(True)
        self.setMinimumHeight(134)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self); v.setContentsMargins(20, 17, 20, 16); v.setSpacing(7)
        h = row()
        h.addWidget(Mark(game, GAMES[game]['color'], 40)); h.addStretch()
        self.status = label('未连接', 'tiny'); h.addWidget(self.status)
        v.addLayout(h)
        self.title = label(GAMES[game]['name']); self.title.setStyleSheet('font-size:16px;font-weight:600;')
        v.addWidget(self.title)
        v.addWidget(label(f'{game}   ·   {GAMES[game]["en"]}', 'tiny'))
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(lambda: callback(game))
        self.restyle()

    def restyle(self):
        color = GAMES[self.game]['color']
        border = color if self.isChecked() else '#2d3240'
        background = '#242131' if self.isChecked() else '#191d26'
        self.setStyleSheet(f'GameCard {{background:{background};border:1px solid {border};border-radius:12px;padding:0;}} GameCard:hover {{border-color:{color};background:#242735;}}')


class Scanner(QThread):
    result = Signal(list, str)

    def run(self):
        try:
            self.result.emit(discover_installations(), '')
        except Exception as exc:
            self.result.emit([], str(exc))


class Window(QMainWindow):
    def __init__(self, settings: Settings, scan=True):
        super().__init__()
        self.settings = settings
        self.store = LibraryStore(Path(settings.values['library_root']))
        for game in GAMES:
            self.store.normalize_library(game)
            try: self.store.refresh_from_disk(game)
            except (OSError, ValueError) as exc: self.store.errors['refresh_' + game] = str(exc)
        self.game = settings.values['game']
        self.installation = inspect_installation(settings.values['xxmi_root']) if settings.values['xxmi_root'] else None
        self.candidates = []
        self.scanner = None
        self.setWindowTitle('ACG Game Library')
        self.resize(1320, 860); self.setMinimumSize(1120, 760)
        icon = Mark(size=64); icon.resize(64, 64)
        self.setWindowIcon(QIcon(icon.grab()))
        root = BackgroundSurface(); self.background_surface = root; self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        sidebar = QWidget(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar); side.setContentsMargins(22, 27, 22, 22); side.setSpacing(10)
        brand = row(12); self.brand_mark = Mark(size=43); brand.addWidget(self.brand_mark)
        brand.addWidget(label('ACG\nGame Library')); side.addLayout(brand)
        side.addSpacing(30); side.addWidget(label('WORKSPACE', 'eyebrow')); side.addSpacing(3)
        self.library_nav = QPushButton('▦    本地模组库'); self.library_nav.setObjectName('nav'); self.library_nav.setCheckable(True)
        self.settings_nav = QPushButton('⚙    设置'); self.settings_nav.setObjectName('nav'); self.settings_nav.setCheckable(True)
        self.library_nav.clicked.connect(lambda: self.navigate(0)); self.settings_nav.clicked.connect(lambda: self.navigate(1))
        side.addWidget(self.library_nav); side.addWidget(self.settings_nav)
        side.addSpacing(29); side.addWidget(label('支持的游戏', 'eyebrow')); side.addSpacing(6)
        self.game_buttons = {}
        for g in GAMES:
            button = QPushButton(GAMES[g]['short']); button.setObjectName('nav'); button.setCheckable(True)
            mark = Mark(g, GAMES[g]['color'], 32)
            button.setIcon(QIcon(mark.grab())); button.setIconSize(QSize(28, 28))
            button.setToolTip(f'{GAMES[g]["name"]} · {g}')
            button.clicked.connect(lambda _, key=g: self.select_game(key)); side.addWidget(button)
            self.game_buttons[g] = button
        side.addStretch()
        tag = label('●  LOCAL ONLY', 'localTag')
        side.addWidget(tag); side.addWidget(label(f'桌面预览版  v{VERSION}', 'tiny'))
        outer.addWidget(sidebar)
        body = column(0); outer.addLayout(body, 1)
        self.stack = QStackedWidget(); body.addWidget(self.stack, 1)
        self.make_library(); self.make_settings()
        self.detail = ModDetailPage(self.store); self.stack.addWidget(self.detail)
        self.detail.back_requested.connect(self.back_to_category)
        self.detail.changed.connect(self.library_view.refresh)
        self.detail.usage_requested.connect(self.toggle_usage)
        self.detail.message.connect(self.notify)
        footer = QWidget(); f = QHBoxLayout(footer); f.setContentsMargins(32, 9, 32, 12)
        self.notice_is_error = False
        self.notice = label('就绪 · 你的本地 MOD 工作空间', 'tiny'); f.addWidget(self.notice, 1)
        self.notice.setMinimumWidth(0); self.notice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.launch_button = QPushButton('↗  打开 XXMI'); self.launch_button.setObjectName('primary')
        self.launch_button.clicked.connect(self.launch); f.addWidget(self.launch_button)
        body.addWidget(footer)
        self.apply_appearance()
        self.navigate(0); self.refresh_connection()
        if settings.load_error:
            self.notify(settings.load_error, True)
        if scan and settings.values['scan_on_start']:
            QTimer.singleShot(350, self.scan)
        if scan and settings.values['check_updates_on_start']:
            QTimer.singleShot(2500,lambda:self.update_panel.start_check(automatic=True))
        report=settings.root/'data'/'update-result.json'
        if report.is_file():
            try:
                result=json.loads(report.read_text(encoding='utf8'))
                self.notify(f'已更新至 v{result["version"]}。' if result.get('ok') else '更新未完成，请查看 data/update-result-seen.json 中的恢复记录。',not result.get('ok'))
                report.replace(report.with_name('update-result-seen.json'))
            except (ValueError,OSError,KeyError): pass

    def page(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(34, 28, 34, 18); v.setSpacing(20)
        return w, v

    def panel(self):
        w = QFrame(); w.setObjectName('panel'); v = QVBoxLayout(w); v.setContentsMargins(24, 20, 24, 22); v.setSpacing(14)
        return w, v

    def make_library(self):
        self.library_view = LibraryView(self.store, self.game, self.open_library)
        self.library_view.open_detail.connect(self.show_detail)
        self.library_view.refresh_requested.connect(self.refresh_library)
        self.library_view.usage_requested.connect(self.toggle_usage)
        self.library_view.message.connect(self.notify)
        self.stack.addWidget(self.library_view)

    def refresh_library(self):
        try:
            result = self.store.refresh_from_disk(self.game)
            self.library_view.refresh()
            self.installation = inspect_installation(self.settings.values['xxmi_root']) if self.settings.values['xxmi_root'] else None
            self.refresh_connection()
            summary = f'刷新完成：{result["total"]} 个模组，新增 {result["added"]} 个，移除 {result["removed"]} 个。'
            if result['warnings']: summary += ' 部分预览图未更新：' + result['warnings'][0]
            self.notify(summary, bool(result['warnings']))
        except (OSError, ValueError) as exc:
            self.notify(f'刷新未完成：{exc}', True)

    def show_detail(self, mod_id):
        if self.detail.show_mod(self.game, mod_id):
            self.navigate(2)

    def toggle_usage(self, mod_id):
        try:
            active = self.store.is_enabled(self.game, mod_id)
            current = inspect_installation(self.settings.values['xxmi_root']) if not active else None
            if not active and (not current or self.game not in current.games):
                raise ValueError('请先在设置中连接 XXMI，并安装当前游戏组件。')
            self.store.set_enabled(self.game, mod_id, not active, current.target(self.game) if current else None)
            self.library_view.refresh()
            if self.detail.mod_id == mod_id and self.stack.currentIndex() == 2:
                self.detail.show_mod(self.game, mod_id)
            self.notify('已停用此模组，其他模组保持使用状态。' if active else '已使用此模组。同一分类可同时使用多个；游戏运行时可按 F10 刷新。')
        except (OSError, ValueError) as exc:
            self.notify(f'操作未完成：{exc}', True)

    def back_to_category(self):
        mod = self.store.get(self.game, self.detail.mod_id)
        if mod:
            self.library_view.category = mod['category_id']
        self.library_view.refresh()
        self.navigate(0)

    def make_settings(self):
        page, v = self.page(); self.stack.addWidget(page)
        v.addWidget(label('设置', 'title')); v.addWidget(label('连接你的加载器，定义自己的本地工作空间。', 'muted'))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); v.addWidget(scroll, 1)
        inside = QWidget(); contents = QVBoxLayout(inside); contents.setContentsMargins(0, 0, 8, 0); contents.setSpacing(18); scroll.setWidget(inside)
        panel, layout = self.panel(); contents.addWidget(panel)
        layout.addWidget(label('外观', 'sectionTitle'))
        layout.addWidget(label('低饱和度主题色', 'muted'))
        colors = row(8); self.theme_buttons = {}; self.theme_group = QButtonGroup(self)
        for key, (name, accent, _) in THEMES.items():
            button = QPushButton(name); button.setObjectName('colorSwatch'); button.setCheckable(True)
            swatch = QPixmap(22,22); swatch.fill(Qt.GlobalColor.transparent)
            painter = QPainter(swatch); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(accent)); painter.setPen(QPen(QColor('#737988'),1)); painter.drawEllipse(2,2,18,18); painter.end()
            button.setIcon(QIcon(swatch)); button.setIconSize(QSize(22,22))
            button.setChecked(key == self.settings.values['theme_color'])
            button.clicked.connect(lambda _, value=key: self.set_theme_color(value))
            self.theme_group.addButton(button); colors.addWidget(button,1); self.theme_buttons[key] = button
        layout.addLayout(colors)
        alpha = row(); alpha.addWidget(label('主题透明度', 'muted'))
        self.transparency_slider = QSlider(Qt.Orientation.Horizontal); self.transparency_slider.setRange(0,100)
        self.transparency_slider.setValue(self.settings.values['theme_transparency']); alpha.addWidget(self.transparency_slider,1)
        self.transparency_value = label(f'{self.transparency_slider.value()}%', 'muted'); self.transparency_value.setFixedWidth(45); alpha.addWidget(self.transparency_value)
        layout.addLayout(alpha)
        layout.addWidget(label('数值越高，背景透出越明显；文字和 MOD 封面保持清晰。', 'tiny'))
        self.appearance_timer = QTimer(self); self.appearance_timer.setSingleShot(True); self.appearance_timer.setInterval(140)
        self.appearance_timer.timeout.connect(self.save_transparency)
        self.transparency_slider.valueChanged.connect(self.preview_transparency)
        layout.addWidget(label('自定义背景', 'muted'))
        background_row = row(9); self.background_edit = QLineEdit(); self.background_edit.setReadOnly(True)
        self.background_edit.setPlaceholderText('未设置背景'); background_row.addWidget(self.background_edit,1)
        self.background_button = QPushButton('选择图片'); self.background_button.clicked.connect(self.choose_background); background_row.addWidget(self.background_button)
        self.clear_background_button = QPushButton('清除背景'); self.clear_background_button.clicked.connect(self.clear_background); background_row.addWidget(self.clear_background_button)
        layout.addLayout(background_row)
        layout.addWidget(label('支持 PNG、JPEG、WebP、BMP，最大 40 MB；自动居中填充。设置即时生效并自动保存。', 'tiny', True))
        self.update_panel=UpdatePanel(self.settings,self.persist)
        self.update_panel.message.connect(self.notify); self.update_panel.installing.connect(self.close)
        contents.addWidget(self.update_panel)
        panel, layout = self.panel(); contents.addWidget(panel)
        head = row(); head.addWidget(label('外部 XXMI', 'sectionTitle')); head.addStretch()
        self.scan_button = QPushButton('↻  自动查找'); self.scan_button.clicked.connect(self.scan); head.addWidget(self.scan_button); layout.addLayout(head)
        layout.addWidget(label('选择你已安装的 XXMI。ACG 不需要内置另一份加载器。', 'muted'))
        paths = row(9); self.path_edit = QLineEdit(); self.path_edit.setReadOnly(True); self.path_edit.setPlaceholderText('尚未连接 XXMI Launcher')
        paths.addWidget(self.path_edit, 1)
        choose = QPushButton('选择文件夹'); choose.clicked.connect(self.choose_folder); paths.addWidget(choose)
        choose_exe = QPushButton('选择 EXE'); choose_exe.clicked.connect(self.choose_exe); paths.addWidget(choose_exe)
        layout.addLayout(paths)
        self.install_summary = label('', 'muted', True); layout.addWidget(self.install_summary)
        self.target_rows = {}; self.target_names = {}
        for game in GAMES:
            line = row(16); name = label(game); name.setFixedWidth(48); name.setStyleSheet(f'color:{GAMES[game]["color"]};font-weight:600;')
            self.target_names[game] = name
            line.addWidget(name); path = label('', 'tiny'); path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); path.setWordWrap(True); line.addWidget(path, 1)
            self.target_rows[game] = path; layout.addLayout(line)
        self.scan_state = label('扫描常见安装位置、工具目录和注册表；也可手动选择任意位置。', 'tiny', True); layout.addWidget(self.scan_state)
        self.candidate_box = column(8); layout.addLayout(self.candidate_box)
        auto = QCheckBox('启动时自动查找 XXMI'); auto.setChecked(self.settings.values['scan_on_start']); auto.toggled.connect(self.set_auto_scan); layout.addWidget(auto)
        panel, layout = self.panel(); contents.addWidget(panel)
        layout.addWidget(label('本地模组库', 'sectionTitle')); layout.addWidget(label('SRMI、ZZMI、EFMI 各自保存独立分类、模组副本和预览图。', 'muted', True))
        paths = row(9); self.library_edit = QLineEdit(); self.library_edit.setReadOnly(True); paths.addWidget(self.library_edit, 1)
        pick = QPushButton('更改位置'); pick.clicked.connect(self.choose_library); paths.addWidget(pick); layout.addLayout(paths)
        layout.addWidget(label('切换库位置后读取该位置的索引，原库保留。使用模组时连接到外部 XXMI。', 'tiny'))
        panel, layout = self.panel(); contents.addWidget(panel)
        heading = row(); heading.addWidget(label('ACG Game Library', 'sectionTitle')); heading.addStretch(); heading.addWidget(label(f'v{VERSION} · 本地整理版', 'muted')); layout.addLayout(heading)
        layout.addWidget(label('本地 ZIP 导入、文件夹刷新、独立分类、3:4 封面、重命名与收藏。\n封面保存为模组文件夹里的 preview.jpg；各模组可独立使用或停用。', 'muted', True))
        contents.addStretch()

    def apply_appearance(self):
        values = self.settings.values
        palette = theme_palette(values['theme_color'])
        self.setProperty('themeColor',values['theme_color'])
        self.setStyleSheet(theme_style(STYLE, values['theme_color'], values['theme_transparency']))
        self.brand_mark.color = palette['soft'] if values['theme_color'] in {'black','white'} else palette['accent']
        self.brand_mark.update()
        for game, button in self.game_buttons.items():
            color = QColor(GAMES[game]['color'])
            if values['theme_color'] == 'white': color = color.darker(155)
            mark = Mark(game,color.name(),32); button.setIcon(QIcon(mark.grab()))
            self.target_names[game].setStyleSheet(f'color:{color.name()};font-weight:600;')
        self.notice.setStyleSheet(f'color:{palette["error" if self.notice_is_error else "muted"]};font-size:11px;')
        try: self.background_surface.set_appearance(values['background_path'],values['theme_transparency'],values['theme_color'])
        except (OSError,ValueError) as exc:
            self.background_surface.set_appearance('',values['theme_transparency'],values['theme_color'])
            self.notify(f'背景未能读取：{exc}',True)
        self.background_edit.setText(values['background_path']); self.background_edit.setToolTip(values['background_path'])
        self.clear_background_button.setEnabled(bool(values['background_path']))
        for key, button in self.theme_buttons.items(): button.setChecked(key == values['theme_color'])

    def set_theme_color(self, color):
        if color not in THEMES: return
        previous = self.settings.values['theme_color']; self.settings.values['theme_color'] = color
        if not self.persist(): self.settings.values['theme_color'] = previous
        self.apply_appearance()

    def preview_transparency(self, value):
        self.transparency_value.setText(f'{value}%'); self.appearance_timer.start()

    def save_transparency(self):
        self.appearance_timer.stop()
        previous = self.settings.values['theme_transparency']
        self.settings.values['theme_transparency'] = self.transparency_slider.value()
        if not self.persist():
            self.settings.values['theme_transparency'] = previous
            self.transparency_slider.blockSignals(True); self.transparency_slider.setValue(previous); self.transparency_slider.blockSignals(False)
            self.transparency_value.setText(f'{previous}%')
        self.apply_appearance()

    def choose_background(self):
        filename, _ = QFileDialog.getOpenFileName(self,'选择启动器背景','','图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if filename: self.set_background_file(filename)

    def set_background_file(self, filename):
        destination = None
        try:
            if self.appearance_timer.isActive(): self.save_transparency()
            image = read_background(filename)
            directory = self.settings.root / 'data' / 'backgrounds'; directory.mkdir(parents=True,exist_ok=True)
            destination = directory / f'{uuid.uuid4().hex}.png'
            if not image.save(str(destination),'PNG'): raise OSError('无法保存背景图片。')
            old = self.settings.values['background_path']; previous = self.settings.values['theme_transparency']
            self.settings.values['background_path'] = str(destination)
            if not old and previous == 0: self.settings.values['theme_transparency'] = 40
            if not self.persist():
                self.settings.values.update(background_path=old,theme_transparency=previous)
                destination.unlink(missing_ok=True); return False
            self.transparency_slider.blockSignals(True); self.transparency_slider.setValue(self.settings.values['theme_transparency']); self.transparency_slider.blockSignals(False)
            self.transparency_value.setText(f'{self.transparency_slider.value()}%')
            self.apply_appearance(); self.remove_old_background(old)
            self.notify('背景已保存；可调节主题透明度改变透出程度。')
            return True
        except (OSError,ValueError) as exc:
            if destination and str(destination) != self.settings.values['background_path']: destination.unlink(missing_ok=True)
            self.notify(f'背景设置未完成：{exc}',True); return False

    def remove_old_background(self, path):
        if not path: return
        old = Path(path); directory = self.settings.root / 'data' / 'backgrounds'
        if old.is_file() and not old.is_symlink() and old.resolve().parent == directory.resolve():
            try: old.unlink()
            except OSError: pass

    def clear_background(self):
        if self.appearance_timer.isActive(): self.save_transparency()
        previous = self.settings.values['background_path']; self.settings.values['background_path'] = ''
        if not self.persist(): self.settings.values['background_path'] = previous; return
        self.apply_appearance(); self.remove_old_background(previous); self.notify('背景已清除。')

    def navigate(self, index):
        self.stack.setCurrentIndex(index); self.library_nav.setChecked(index != 1); self.settings_nav.setChecked(index == 1)

    def persist(self):
        try:
            self.settings.save()
            return True
        except OSError as exc:
            self.notify(f'设置保存失败：{exc}', True)
            return False

    def select_game(self, game):
        self.game = game; self.settings.values['game'] = game; self.persist()
        self.library_view.set_game(game)
        self.navigate(0); self.refresh_connection()

    def refresh_connection(self):
        for g, button in self.game_buttons.items():
            button.setChecked(g == self.game)
        self.path_edit.setText(str(self.installation.root) if self.installation else self.settings.values['xxmi_root'])
        self.library_edit.setText(self.settings.values['library_root'])
        if self.installation:
            self.install_summary.setText(f'已连接  ·  XXMI {self.installation.version}  ·  {len(self.installation.games)} / 3 个组件可用')
            self.library_view.connection.setText(f'●  XXMI {self.installation.version} 已连接  ·  当前游戏 {self.game}  ·  可同时使用多个 MOD')
        else:
            self.install_summary.setText('未连接加载器。选择 XXMI 根目录或 Resources / Bin 中的 EXE。')
            self.library_view.connection.setText('○  尚未连接外部 XXMI，前往设置即可自动查找。')
        for g, widget in self.target_rows.items():
            widget.setText((str(self.installation.target(g)) + ('   ·   可用' if g in self.installation.games else '   ·   组件未安装')) if self.installation else '等待连接')
        available = bool(self.installation and self.game in self.installation.games)
        self.launch_button.setEnabled(available)
        self.launch_button.setToolTip('打开当前游戏的 XXMI 界面；如需权限，Windows 会显示确认提示。' if available else '请先连接 XXMI，并安装当前游戏的导入器组件。')

    def notify(self, message, error=False):
        self.notice_is_error = error
        color = theme_palette(self.settings.values['theme_color'])['error' if error else 'muted']
        self.notice.setText(message); self.notice.setToolTip(message); self.notice.setStyleSheet(f'color:{color};font-size:11px;')

    def scan(self):
        if self.scanner and self.scanner.isRunning():
            return
        self.scan_button.setEnabled(False); self.scan_button.setText('正在查找…')
        self.scan_state.setText('正在扫描常见位置，跳过 MOD 素材目录…')
        self.scanner = Scanner(self); self.scanner.result.connect(self.scanned); self.scanner.start()

    def scanned(self, candidates, error):
        self.candidates = candidates; self.scan_button.setEnabled(True); self.scan_button.setText('↻  重新查找')
        while self.candidate_box.count():
            item = self.candidate_box.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for installation in candidates:
            button = QPushButton(f'XXMI {installation.version}   ·   {" / ".join(installation.games) or "未安装组件"}\n{installation.root}')
            button.setStyleSheet('text-align:left;font-size:11px;padding:10px 12px;')
            button.setToolTip(str(installation.root)); button.clicked.connect(lambda _, candidate=installation: self.connect_installation(candidate))
            self.candidate_box.addWidget(button)
        self.scan_state.setText(f'找到 {len(candidates)} 个 XXMI 实例。点击下方实例可切换；未找到时可手动选择。' if not error else f'扫描未完成：{error}')
        if candidates and not self.installation and not self.settings.values['xxmi_root']:
            self.connect_installation(candidates[0], automatic=True)
        else:
            self.notify(f'扫描完成，发现 {len(candidates)} 个 XXMI 实例。' if not error else error, bool(error))

    def connect_installation(self, installation, automatic=False):
        self.installation = installation; self.settings.values['xxmi_root'] = str(installation.root)
        saved = self.persist(); self.refresh_connection()
        if saved:
            self.notify(('已自动连接' if automatic else '已连接') + f' XXMI {installation.version}，设置已保存。')

    def validate_choice(self, path):
        if not path:
            return
        installation = inspect_installation(path)
        if not installation:
            self.notify('未识别到有效 XXMI：请选择含 Resources\\Bin\\XXMI Launcher.exe 的根目录，或该 EXE。', True)
            return
        self.connect_installation(installation)

    def choose_folder(self):
        self.validate_choice(QFileDialog.getExistingDirectory(self, '选择外部 XXMI 根目录', str(self.installation.root) if self.installation else 'E:/game tool'))

    def choose_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 XXMI Launcher.exe', str(self.installation.exe.parent) if self.installation else 'E:/game tool', 'XXMI Launcher (XXMI Launcher.exe)')
        self.validate_choice(path)

    def choose_library(self):
        path = QFileDialog.getExistingDirectory(self, '选择本地 MOD 库根目录', self.settings.values['library_root'])
        if path:
            self.settings.values['library_root'] = path
            if self.persist(): self.notify('本地库位置已保存，原文件未迁移。')
            self.store = LibraryStore(Path(path))
            for game in GAMES:
                self.store.normalize_library(game)
                try: self.store.refresh_from_disk(game)
                except (OSError, ValueError) as exc: self.notify(str(exc), True)
            self.library_view.store = self.store; self.detail.store = self.store
            self.library_view.refresh()
            self.refresh_connection()

    def set_auto_scan(self, value):
        self.settings.values['scan_on_start'] = value
        if self.persist(): self.notify('启动扫描设置已保存。')

    def open_library(self):
        try:
            path = self.settings.library_path(self.game) / 'Mods'; path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except OSError as exc:
            self.notify(f'无法打开本地库：{exc}', True)

    def launch(self):
        try:
            current = inspect_installation(self.settings.values['xxmi_root'])
            if not current or self.game not in current.games:
                raise ValueError('当前 XXMI 或游戏组件不可用，请在设置中检查路径。')
            self.notify('正在打开 XXMI；如出现 Windows 权限提示，请确认后继续。')
            QApplication.processEvents()
            open_xxmi(current, self.game)
            self.notify(f'已请求打开 {self.game} 的 XXMI 启动界面。')
        except LaunchCancelled as exc:
            self.notify(str(exc))
        except (OSError, ValueError) as exc:
            self.notify(str(exc), True)

    def closeEvent(self, event):
        if self.appearance_timer.isActive(): self.save_transparency()
        if self.update_panel.busy():
            self.update_panel.cancel(); self.hide(); self.update_panel.worker.finished.connect(self.close)
            event.ignore(); return
        if self.scanner and self.scanner.isRunning():
            self.hide()
            self.scanner.finished.connect(self.close)
            event.ignore()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--page', choices=['library', 'settings'], default='library', help=argparse.SUPPRESS)
    parser.add_argument('--no-scan', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--detail-id', default='', help=argparse.SUPPRESS)
    parser.add_argument('--category-id', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName('ACG Game Library'); app.setApplicationVersion(VERSION)
    app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    settings = Settings(app_root())
    window = Window(settings, scan=not args.no_scan)
    window.navigate(1 if args.page == 'settings' else 0)
    if args.detail_id: window.show_detail(args.detail_id)
    if args.category_id in {c['id'] for c in window.store.categories(window.game)}:
        window.library_view.category = args.category_id; window.library_view.refresh()
    window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.screenshot))
            window.close(); app.quit()
        QTimer.singleShot(2200, capture)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
