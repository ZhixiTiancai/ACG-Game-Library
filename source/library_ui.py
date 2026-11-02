from pathlib import Path
import os
import unicodedata
from collections import Counter
from functools import lru_cache
from pypinyin import lazy_pinyin, Style

from PySide6.QtCore import Qt, QSize, Signal, QRectF, QTimer, QEvent
from PySide6.QtGui import QPixmap, QImageReader, QPainter, QPainterPath, QColor, QPen
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QScrollArea, QLineEdit, QInputDialog, QFileDialog, QComboBox, QSizePolicy)

from acg_core import GAMES
from library_store import UNCATEGORIZED
from appearance import theme_palette


def text(value, style='', wrap=False):
    widget = QLabel(value); widget.setWordWrap(wrap)
    if style: widget.setObjectName(style)
    return widget


def line():
    layout = QHBoxLayout(); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(12)
    return layout


@lru_cache(maxsize=2048)
def category_spelling(name):
    return (''.join(lazy_pinyin(name)).casefold(),
            ''.join(lazy_pinyin(name, style=Style.FIRST_LETTER)).casefold())


def category_sort_key(category):
    name = category['name'].strip()
    first = name[:1]
    # Symbols/digits first, then Latin names, then Han names (pinyin within Han).
    is_han = bool(first and ('\u3400' <= first <= '\u9fff' or '\U00020000' <= first <= '\U000323af'))
    group = 2 if is_han else 1 if first and unicodedata.category(first).startswith('L') else 0
    return (category['id'] != UNCATEGORIZED, group, category_spelling(name)[0], name.casefold())


class Photo(QLabel):
    def __init__(self, large=False):
        super().__init__()
        self.original = QPixmap()
        self.large = large
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(80, 150 if large else 100)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setObjectName('previewPhoto')
        self.setText('◇\n\n尚未设置预览图' if large else '◇\n无预览图')

    def load(self, path):
        self.original = QPixmap()
        if path and Path(path).is_file():
            reader = QImageReader(str(path)); reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                limit = 1800 if self.large else 560
                if max(size.width(), size.height()) > limit:
                    size.scale(QSize(limit, limit), Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            self.original = QPixmap.fromImage(reader.read())
        self.redraw()

    def redraw(self):
        self.update()

    def paintEvent(self, event):
        palette = theme_palette(self.window().property('themeColor') or 'purple')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        shape = QPainterPath(); shape.addRoundedRect(rect, 10, 10)
        painter.fillPath(shape, QColor(palette['input']))
        painter.save(); painter.setClipPath(shape)
        if not self.original.isNull():
            scaled = self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            painter.setPen(QColor(palette['muted']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '◇\n\n尚未设置预览图' if self.large else '◇\n暂无封面')
        painter.restore(); painter.setPen(QPen(QColor(palette['border']), 1)); painter.drawPath(shape)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.update()


class PortraitArea(QWidget):
    def __init__(self, photo):
        super().__init__(); self.photo = photo; photo.setParent(self)
        self.setMinimumSize(180, 240)

    def resizeEvent(self, event):
        width = max(3, min(self.width(), self.height() * 3 // 4))
        height = width * 4 // 3
        self.photo.setGeometry((self.width()-width)//2, (self.height()-height)//2, width, height)
        super().resizeEvent(event)


class LibraryView(QWidget):
    open_detail = Signal(str)
    refresh_requested = Signal()
    usage_requested = Signal(str)
    message = Signal(str, bool)

    def __init__(self, store, game, open_library):
        super().__init__()
        self.store, self.game = store, game
        self.category = UNCATEGORIZED
        self.only_favorites = False
        self.columns = 1
        self.open_library = open_library
        outer = QVBoxLayout(self); outer.setContentsMargins(34, 24, 34, 12); outer.setSpacing(12)
        header = line(); titles = QVBoxLayout(); titles.setSpacing(7)
        self.kicker = text('', 'eyebrow'); titles.addWidget(self.kicker)
        self.heading = text('', 'title'); titles.addWidget(self.heading)
        self.subtitle = text('', 'muted'); titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.refresh_button = QPushButton('↻  刷新'); self.refresh_button.setObjectName('primary')
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.refresh_button.setToolTip('重新扫描当前游戏的 Mods 文件夹，并读取 preview.jpg。')
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignVCenter); outer.addLayout(header)

        split = QHBoxLayout(); split.setSpacing(22); outer.addLayout(split, 1)
        self.category_pane = QWidget(); self.category_pane.setFixedWidth(204)
        sidebar = QVBoxLayout(self.category_pane); sidebar.setContentsMargins(0, 0, 0, 0); sidebar.setSpacing(12)
        top = line(); top.addWidget(text('我的分类', 'sectionTitle')); top.addStretch()
        self.add_category_button = QPushButton('＋'); self.add_category_button.setFixedSize(34, 34)
        self.add_category_button.setStyleSheet('padding:0;font-size:20px;')
        self.add_category_button.setToolTip('新建分类'); self.add_category_button.setAccessibleName('新建分类')
        self.add_category_button.clicked.connect(self.add_category); top.addWidget(self.add_category_button)
        sidebar.addLayout(top)
        self.category_search = QLineEdit(); self.category_search.setPlaceholderText('搜索分类')
        self.category_search.setClearButtonEnabled(True)
        self.category_search.setToolTip('支持分类名称、拼音和拼音首字母。')
        self.category_search.textChanged.connect(self.render_categories); sidebar.addWidget(self.category_search)
        self.categories_scroll = QScrollArea(); self.categories_scroll.setWidgetResizable(True)
        self.categories_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories_widget = QWidget(); self.categories_row = QVBoxLayout(self.categories_widget)
        self.categories_row.setContentsMargins(0, 0, 8, 0); self.categories_row.setSpacing(8)
        self.categories_scroll.setWidget(self.categories_widget); sidebar.addWidget(self.categories_scroll, 1)
        split.addWidget(self.category_pane)
        divider = QFrame(); divider.setObjectName('divider'); divider.setFixedWidth(1)
        split.addWidget(divider)
        self.preview_pane = QWidget(); preview = QVBoxLayout(self.preview_pane)
        preview.setContentsMargins(0, 0, 0, 0); preview.setSpacing(12); split.addWidget(self.preview_pane, 1)

        bar = line(); self.category_title = text('', 'sectionTitle'); bar.addWidget(self.category_title, 1)
        self.category_title.setMinimumWidth(0); self.category_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.mod_count = text('', 'muted'); bar.addWidget(self.mod_count)
        folder = QPushButton('打开本地库'); folder.clicked.connect(self.open_library); bar.addWidget(folder)
        preview.addLayout(bar)
        tools = line()
        self.all_button = QPushButton('全部模组'); self.all_button.setObjectName('filter'); self.all_button.setCheckable(True)
        self.favorites_button = QPushButton('☆  只看收藏'); self.favorites_button.setObjectName('filter'); self.favorites_button.setCheckable(True)
        self.all_button.clicked.connect(lambda: self.set_favorites(False)); self.favorites_button.clicked.connect(lambda: self.set_favorites(True))
        tools.addWidget(self.all_button); tools.addWidget(self.favorites_button); tools.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText('搜索当前分类的模组'); self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.render_mods); tools.addWidget(self.search)
        self.import_button = QPushButton('＋  导入 ZIP'); self.import_button.clicked.connect(self.import_zip); tools.addWidget(self.import_button)
        preview.addLayout(tools)

        self.mod_scroll = QScrollArea(); self.mod_scroll.setWidgetResizable(True)
        self.mod_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mod_area = QWidget(); self.mod_grid = QGridLayout(self.mod_area)
        self.mod_grid.setContentsMargins(0, 0, 5, 0); self.mod_grid.setSpacing(16)
        self.mod_scroll.setWidget(self.mod_area); preview.addWidget(self.mod_scroll, 1)
        self.resize_timer = QTimer(self); self.resize_timer.setSingleShot(True); self.resize_timer.setInterval(40)
        self.resize_timer.timeout.connect(self.resize_grid)
        self.mod_scroll.viewport().installEventFilter(self)
        self.connection = text('', 'tiny'); outer.addWidget(self.connection)
        self.refresh()

    @staticmethod
    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def set_game(self, game):
        self.game, self.category = game, UNCATEGORIZED
        self.only_favorites = False; self.search.clear(); self.category_search.clear(); self.refresh()

    def refresh(self):
        self.kicker.setText(f'本地模组库  /  {self.game}')
        self.heading.setText(GAMES[self.game]['name'])
        mods = self.store.mods(self.game)
        active = sum(self.store.is_enabled(self.game, m['id']) for m in mods)
        self.subtitle.setText(f'{len(mods)} 个模组  ·  {active} 个使用中  ·  按你的分类，整理喜欢的内容。')
        valid = {c['id'] for c in self.store.categories(self.game)}
        if self.category not in valid: self.category = UNCATEGORIZED
        self.render_categories()
        self.render_mods()

    def render_categories(self, *_):
        self.clear(self.categories_row)
        self.category_buttons = {}
        counts = Counter(m['category_id'] for m in self.store.mods(self.game))
        query = self.category_search.text().strip().casefold()
        for cat in sorted(self.store.categories(self.game), key=category_sort_key):
            spelling, initials = category_spelling(cat['name'])
            if query and not any(query in value for value in (cat['name'].casefold(), spelling, initials)):
                continue
            count = counts[cat['id']]
            button = QPushButton(); button.setFixedHeight(68); button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCheckable(True); button.setChecked(cat['id'] == self.category); button.setToolTip(cat['name'])
            button.setObjectName('categoryButton')
            v = QVBoxLayout(button); v.setContentsMargins(14, 11, 14, 11); v.setSpacing(4)
            title = text('▱   ' + cat['name']); title.setStyleSheet('font-size:14px;font-weight:600;')
            title.setMinimumWidth(0); title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); v.addWidget(title)
            v.addWidget(text(f'{count} 个模组' + ('  ·  默认' if cat['id'] == UNCATEGORIZED else ''), 'muted'))
            for child in button.findChildren(QWidget): child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            button.clicked.connect(lambda _, key=cat['id']: self.select_category(key))
            self.category_buttons[cat['id']] = button; self.categories_row.addWidget(button)
        if not self.category_buttons:
            empty = text('没有匹配的分类', 'muted'); empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.categories_row.addWidget(empty)
        self.categories_row.addStretch()

    def select_category(self, category):
        self.category = category
        for key, button in self.category_buttons.items(): button.setChecked(key == category)
        self.search.clear(); self.mod_scroll.verticalScrollBar().setValue(0); self.render_mods()

    def set_favorites(self, value):
        self.only_favorites = value; self.render_mods()

    def render_mods(self, *_):
        self.clear(self.mod_grid)
        for index in range(self.mod_grid.rowCount() + 1): self.mod_grid.setRowStretch(index, 0)
        self.all_button.setChecked(not self.only_favorites); self.favorites_button.setChecked(self.only_favorites)
        self.category_title.setText(self.store.category_name(self.game, self.category))
        self.category_title.setToolTip(self.store.category_name(self.game, self.category))
        mods = self.store.mods(self.game, self.category, self.only_favorites, self.search.text())
        self.mod_count.setText(f'{len(mods)} 个模组')
        self.mod_buttons = {}
        self.use_buttons = {}
        for index in range(max(5, self.mod_grid.columnCount()+1)):
            self.mod_grid.setColumnStretch(index, 0); self.mod_grid.setColumnMinimumWidth(index, 0)
        if not mods:
            frame = QFrame(); frame.setObjectName('emptyPanel'); frame.setMinimumHeight(240)
            v = QVBoxLayout(frame); v.setContentsMargins(24, 28, 24, 28); v.addStretch()
            icon = text('▱', 'accentGlyph'); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(icon)
            title = text('当前筛选下没有模组' if self.search.text() or self.only_favorites else '这个分类，等待你的第一款模组', 'sectionTitle')
            title.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(title)
            desc = text('清空搜索或切回全部模组。' if self.search.text() or self.only_favorites else '导入本地 ZIP，点击模组即可设置大图、名称、收藏与分类。', 'muted', True)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(desc); v.addStretch()
            self.mod_grid.addWidget(frame, 0, 0, 1, self.columns + 1)
        else:
            for i, mod in enumerate(mods):
                active = self.store.is_enabled(self.game, mod['id'])
                frame = QFrame(); frame.setObjectName('modCard'); frame.setFixedSize(232, 386)
                outer = QVBoxLayout(frame); outer.setContentsMargins(10, 10, 10, 10); outer.setSpacing(8)
                button = QPushButton(); button.setObjectName('modOpen')
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                button.setMinimumHeight(326)
                v = QVBoxLayout(button); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
                photo = Photo(); photo.setFixedSize(210, 280)
                if mod['preview']: photo.load(self.store.absolute(self.game, mod['preview']))
                v.addWidget(photo)
                name = text(('★  ' if mod['favorite'] else '') + mod['name'], wrap=True)
                name.setStyleSheet('font-size:13px;font-weight:600;'); name.setFixedHeight(38); name.setToolTip(mod['name']); v.addWidget(name)
                for child in button.findChildren(QWidget): child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                button.clicked.connect(lambda _, key=mod['id']: self.open_detail.emit(key))
                outer.addWidget(button, 1)
                footer = line(); state = text('● 已使用' if active else '未使用', 'tiny')
                if active: state.setObjectName('activeStatus')
                footer.addWidget(state); footer.addStretch()
                use = QPushButton('停用' if active else '使用'); use.setFixedSize(68, 31)
                use.setObjectName('useActive' if active else 'useMod'); use.clicked.connect(lambda _, key=mod['id']: self.usage_requested.emit(key))
                footer.addWidget(use); outer.addLayout(footer)
                self.mod_buttons[mod['id']] = button; self.use_buttons[mod['id']] = use
                self.mod_grid.addWidget(frame, i // self.columns, i % self.columns, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.mod_grid.setRowStretch((len(mods) - 1) // self.columns + 1, 1)
        self.mod_grid.setColumnStretch(self.columns, 1)

    def eventFilter(self, watched, event):
        if watched is self.mod_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self.resize_timer.start()
        return super().eventFilter(watched, event)

    def resize_grid(self):
        columns = max(1, (self.mod_scroll.viewport().width() + 11) // 248)
        if columns != self.columns:
            self.columns = columns; self.render_mods()

    def add_category(self):
        name, accepted = QInputDialog.getText(self, '新建分类', f'为{GAMES[self.game]["short"]}添加分类：')
        if accepted:
            try:
                cat = self.store.add_category(self.game, name); self.category = cat['id']; self.category_search.clear(); self.refresh()
                self.message.emit('分类已创建。', False)
            except (OSError, ValueError) as exc: self.message.emit(str(exc), True)

    def import_zip(self):
        filename, _ = QFileDialog.getOpenFileName(self, '导入当前游戏的 MOD 副本', '', 'MOD ZIP (*.zip)')
        if filename:
            self.import_file(filename)

    def import_file(self, filename):
        try:
            record = self.store.import_zip(self.game, Path(filename), self.category)
            self.store.refresh_from_disk(self.game)
            self.refresh(); self.message.emit('MOD 副本已导入，点击卡片可编辑详情。', False)
            return record
        except Exception as exc:
            self.message.emit(f'导入失败：{exc}', True)
            return None


class ModDetailPage(QWidget):
    back_requested = Signal()
    changed = Signal()
    usage_requested = Signal(str)
    message = Signal(str, bool)

    def __init__(self, store):
        super().__init__(); self.store = store; self.game = 'SRMI'; self.mod_id = None
        outer = QVBoxLayout(self); outer.setContentsMargins(34, 28, 34, 18); outer.setSpacing(18)
        top = line(); back = QPushButton('←  返回分类'); back.clicked.connect(self.back_requested); top.addWidget(back)
        self.breadcrumb = text('', 'muted'); top.addWidget(self.breadcrumb); top.addStretch(); outer.addLayout(top)
        self.title = text('', 'title'); self.title.setWordWrap(True); outer.addWidget(self.title)
        middle = line(); middle.setSpacing(22)
        left = QVBoxLayout(); left.setSpacing(12); self.photo = Photo(large=True); self.portrait_area = PortraitArea(self.photo); left.addWidget(self.portrait_area, 1)
        image_tools = line(); image_tools.addWidget(text('模组预览', 'muted')); image_tools.addStretch()
        self.preview_button = QPushButton('选择大图'); self.preview_button.clicked.connect(self.choose_preview); image_tools.addWidget(self.preview_button)
        left.addLayout(image_tools); middle.addLayout(left, 1)
        right = QFrame(); right.setObjectName('panel'); right.setFixedWidth(310)
        form = QVBoxLayout(right); form.setContentsMargins(22, 23, 22, 23); form.setSpacing(14)
        form.addWidget(text('模组设置', 'sectionTitle')); form.addSpacing(5)
        form.addWidget(text('显示名称', 'muted')); self.name = QLineEdit(); self.name.setMaxLength(120); form.addWidget(self.name)
        self.save_name_button = QPushButton('保存名称'); self.save_name_button.clicked.connect(self.save_name); self.name.returnPressed.connect(self.save_name); form.addWidget(self.save_name_button)
        form.addWidget(text('库内文件夹同步改名；同名时自动加序号。', 'tiny', True))
        form.addSpacing(12); self.favorite = QPushButton('☆  收藏模组'); self.favorite.setCheckable(True); self.favorite.clicked.connect(self.set_favorite); form.addWidget(self.favorite)
        form.addSpacing(12); form.addWidget(text('所属分类', 'muted')); self.categories = QComboBox(); form.addWidget(self.categories); self.categories.currentIndexChanged.connect(self.set_category)
        form.addWidget(text('列出当前游戏的全部自定义分类。', 'tiny', True))
        form.addStretch(); self.use_button = QPushButton('使用此模组'); self.use_button.setObjectName('primary'); self.use_button.clicked.connect(lambda: self.usage_requested.emit(self.mod_id)); form.addWidget(self.use_button)
        self.info = text('', 'muted', True); form.addWidget(self.info)
        open_folder = QPushButton('打开模组文件夹'); open_folder.clicked.connect(self.open_folder); form.addWidget(open_folder)
        middle.addWidget(right); outer.addLayout(middle, 1)

    def show_mod(self, game, mod_id):
        self.game, self.mod_id = game, mod_id
        mod = self.store.get(game, mod_id)
        if not mod: return False
        self.name.setText(mod['name']); self.title.setText(mod['name'])
        self.favorite.setChecked(mod['favorite']); self.favorite.setText('★  已收藏' if mod['favorite'] else '☆  收藏模组')
        self.categories.blockSignals(True); self.categories.clear()
        for cat in sorted(self.store.categories(game), key=category_sort_key): self.categories.addItem(cat['name'], cat['id'])
        self.categories.setCurrentIndex(max(0, self.categories.findData(mod['category_id']))); self.categories.blockSignals(False)
        self.breadcrumb.setText(f'{GAMES[game]["short"]}  /  {self.store.category_name(game, mod["category_id"])}')
        active = self.store.is_enabled(game, mod_id)
        self.use_button.setText('停用此模组' if active else '使用此模组')
        self.info.setText(f'{game}  ·  本地副本\n' + ('正在外部 XXMI 中使用' if active else '尚未使用'))
        self.photo.load(self.store.absolute(game, mod['preview']) if mod['preview'] else '')
        return True

    def save_name(self):
        try:
            self.store.update(self.game, self.mod_id, name=self.name.text()); self.show_mod(self.game, self.mod_id)
            self.changed.emit(); self.message.emit('模组名称已保存。', False)
        except (OSError, ValueError) as exc: self.message.emit(str(exc), True)

    def set_favorite(self, value):
        try:
            self.store.update(self.game, self.mod_id, favorite=value); self.show_mod(self.game, self.mod_id)
            self.changed.emit(); self.message.emit('已加入收藏。' if value else '已取消收藏。', False)
        except (OSError, ValueError) as exc:
            self.show_mod(self.game, self.mod_id); self.message.emit(str(exc), True)

    def set_category(self, *_):
        if not self.mod_id: return
        try:
            self.store.update(self.game, self.mod_id, category_id=self.categories.currentData()); self.show_mod(self.game, self.mod_id)
            self.changed.emit(); self.message.emit('所属分类已保存。', False)
        except (OSError, ValueError) as exc: self.message.emit(str(exc), True)

    def choose_preview(self):
        filename, _ = QFileDialog.getOpenFileName(self, '设置模组大图', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if filename: self.set_preview_file(filename)

    def set_preview_file(self, filename):
        try:
            path = Path(filename)
            if path.stat().st_size > 40 * 1024**2 or not QImageReader(str(path)).canRead():
                raise ValueError('请选择可读取且小于 40 MB 的图片。')
            self.store.set_preview(self.game, self.mod_id, path)
            self.show_mod(self.game, self.mod_id); self.changed.emit(); self.message.emit('已按 3:4 保存到模组文件夹的 preview.jpg，并更新卡片。', False)
        except (OSError, ValueError) as exc: self.message.emit(str(exc), True)

    def open_folder(self):
        mod = self.store.get(self.game, self.mod_id)
        if mod:
            try: os.startfile(str(self.store.absolute(self.game, mod['folder'])))
            except OSError as exc: self.message.emit(str(exc), True)
