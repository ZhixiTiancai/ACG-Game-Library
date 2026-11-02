"""Local appearance settings, muted accents and a background beneath clear text."""
from pathlib import Path
import re
from functools import lru_cache

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


THEMES = {
    'purple': ('雾紫', '#ad9dce', '#1b1822'),
    'red': ('柔红', '#c59298', '#251b1d'),
    'green': ('灰绿', '#91b6a4', '#18231e'),
    'yellow': ('浅金', '#c7b585', '#272318'),
    'blue': ('雾蓝', '#91abc8', '#19212b'),
    'black': ('墨黑', '#454a54', '#f0f1f5'),
    'white': ('月白', '#d2d5dc', '#20232b'),
}

# Page, sidebar, panel, MOD card, input, button, border: each theme supplies
# actual surfaces as well as an accent. White is a full light palette.
SURFACES = {
    'purple': ('#211a2d','#292136','#30273c','#342b42','#211a2c','#3b314a','#55475f'),
    'red': ('#2d1d22','#35242a','#3d2b31','#423036','#2b1d22','#4a343b','#65474f'),
    'green': ('#192b24','#20352b','#263d32','#2c4337','#192b23','#314b3e','#476653'),
    'yellow': ('#2c281d','#353024','#3f392b','#453e2f','#2c271c','#4d4634','#6a6046'),
    'blue': ('#1b2533','#222e3d','#293748','#2e3c4e','#1b2635','#34475b','#4c6177'),
    'black': ('#101113','#17191c','#1e2125','#24272c','#131518','#30343a','#484d55'),
    'white': ('#eef0f3','#e1e5eb','#f9fafc','#ffffff','#edf0f4','#e2e6ec','#c5ccd6'),
}


def blend(color, other, amount):
    a, b = QColor(color), QColor(other)
    return QColor(*(round(x * (1-amount) + y * amount) for x,y in zip(a.getRgb()[:3],b.getRgb()[:3]))).name()


def rgba(color, alpha):
    value = QColor(color)
    return f'rgba({value.red()},{value.green()},{value.blue()},{round(alpha * 255)})'


@lru_cache(maxsize=7)
def theme_palette(theme='purple'):
    if theme not in THEMES: theme = 'purple'
    name, accent, foreground = THEMES[theme]
    roles = dict(zip(('background','sidebar','panel','card','input','button','border'),SURFACES[theme]))
    light = theme == 'white'
    roles.update(accent=accent, foreground=foreground, text='#26303c' if light else '#eceaf1',
        muted='#526175' if light else '#aaa8b9', tiny='#626f81' if light else '#9493a7',
        focus='#687b95' if light else accent, soft='#34465e' if light else '#c7cbd3' if theme=='black' else blend(accent,'#f2f3f7',.32),
        positive='#316b50' if light else '#a0cbb1', error='#98423d' if light else '#e7b0a2',
        positive_bg='#deeee4' if light else '#294238', disabled_text='#788392' if light else '#8b8999')
    roles['hover'] = blend(roles['button'],'#000000' if light else '#ffffff',.07)
    roles['pressed'] = blend(roles['button'],'#000000' if light else '#ffffff',.13)
    roles['selected'] = '#d4dce6' if light else blend(roles['sidebar'],accent,.23)
    roles['accent_hover'] = blend(accent,'#000000' if light else '#ffffff',.12)
    return roles


def theme_style(base, theme='purple', transparency=0):
    p = theme_palette(theme)
    accent, foreground, soft = p['accent'], p['foreground'], p['soft']
    hover, selected, border = p['accent_hover'], p['selected'], p['border']
    replacements = {
        '#aa96f4':accent, '#171320':foreground, '#beadff':hover,
        '#333047':p['button'], '#7e748e':p['disabled_text'], '#39354b':border,
        '#2b263e':selected, '#433855':border, '#c8b4ff':soft,
        '#c4b1ff':soft, '#b39af8':accent, '#baa8ef':soft,
        '#59477d':border, '#a48bdf':accent, '#b09af7':accent,
        '#c0abff':soft, '#ab95ef':accent, '#1e1830':foreground,
        '#c2adff':hover, '#46395d':selected, '#a18cdb':accent,
        '#dce0eb':p['text'], '#101218':p['background'], '#14161e':p['sidebar'], '#262a35':border,
        '#171a23':p['panel'], '#292e3a':border, '#858da2':p['muted'], '#697288':p['tiny'],
        '#f0f1f8':p['text'], '#e9ebf5':p['text'], '#777f96':p['tiny'], '#202530':p['button'],
        '#33394a':border, '#2a3040':p['hover'], '#555572':p['focus'], '#333950':p['pressed'],
        '#1d202a':p['input'], '#626a7e':p['disabled_text'], '#2b303d':border,
        '#929bb1':p['muted'], '#202330':p['hover'], '#e0e3ed':p['text'], '#7d879d':p['muted'],
        '#12151d':p['input'], '#2b3140':border, '#d6dbea':p['text'], '#a0a9be':p['muted'],
        '#c1c8d9':p['text'], '#53576c':border, '#171b25':p['input'], '#343b4c':border,
        '#282d3c':p['panel'], '#e2e5ee':p['text'], '#4b5267':border, '#191d27':p['card'],
        '#30374a':border, '#202535':p['hover'], '#263e37':p['positive_bg'],
        '#9bd8bf':p['positive'], '#405f53':p['positive'], '#353c4f':border,
        '#202532':p['panel'], '#2c3343':border,
    }
    style = re.sub(r'#[0-9a-fA-F]{6}', lambda m: replacements.get(m[0].lower(),m[0]),base)
    opacity = max(.16, 1 - max(0,min(100,transparency)) / 100)
    brightness = max(0,min(100,transparency)) / 100 * .6
    readable = '#39485c' if theme == 'white' else '#d1d3df'
    style += f'''
QWidget#root {{background:transparent;}}
QLabel#muted {{color:{blend(p['muted'],readable,brightness)};}}
QLabel#tiny {{color:{blend(p['tiny'],readable,brightness)};}}
QLabel#eyebrow {{color:{blend(p['tiny'],readable,brightness)};}}
QLabel#activeStatus, QLabel#localTag {{color:{p['positive']};font-size:11px;}}
QWidget#sidebar {{background:{rgba(p['sidebar'],opacity)};}}
QFrame#panel, QFrame#emptyPanel {{background:{rgba(p['panel'],opacity)};}}
QFrame#modCard {{background:{rgba(p['card'],opacity)};}}
QFrame#divider {{background:{border};}}
QLineEdit, QComboBox {{background:{rgba(p['input'],max(.5,opacity))};}}
QPushButton#categoryButton {{text-align:left;background:{rgba(p['card'],opacity)};border:1px solid {border};border-radius:12px;padding:0;}}
QPushButton#categoryButton:checked {{background:{rgba(selected,max(.55,opacity))};border-color:{accent};}}
QPushButton#categoryButton:hover {{border-color:{accent};}}
QLabel#accentGlyph {{font-size:46px;color:{soft};}}
QSlider::groove:horizontal {{height:5px;background:{border};border-radius:2px;}}
QSlider::sub-page:horizontal {{background:{accent};border-radius:2px;}}
QSlider::handle:horizontal {{width:16px;margin:-6px 0;background:{accent};border:1px solid {soft};border-radius:8px;}}
QPushButton#colorSwatch {{padding:5px;border:2px solid transparent;border-radius:9px;}}
QPushButton#colorSwatch:checked {{border-color:{p['focus']};}}
QProgressBar {{border:1px solid {border};border-radius:5px;background:{p['input']};text-align:center;min-height:18px;}}
QProgressBar::chunk {{background:{accent};border-radius:4px;}}
'''
    return style


def read_background(path):
    path = Path(path)
    if path.stat().st_size > 40 * 1024**2:
        raise ValueError('请选择小于 40 MB 的背景图片。')
    reader = QImageReader(str(path)); reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(),size.height()) > 2560:
        size.scale(QSize(2560,2560),Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    if image.isNull(): raise ValueError('无法读取背景，请选择 PNG、JPEG、WebP 或 BMP 图片。')
    return image


class BackgroundSurface(QWidget):
    def __init__(self):
        super().__init__(); self.setObjectName('root')
        self.path = ''; self.transparency = 0
        self.theme = 'purple'
        self.image = QPixmap(); self.cover = QPixmap()

    def set_appearance(self, path, transparency, theme='purple'):
        if path != self.path:
            loaded = QPixmap.fromImage(read_background(path)) if path and Path(path).is_file() else QPixmap()
            self.path, self.image, self.cover = path, loaded, QPixmap()
        self.transparency = transparency; self.theme = theme; self.update()

    def paintEvent(self, event):
        color = theme_palette(self.theme)['background']
        painter = QPainter(self); painter.fillRect(self.rect(), QColor(color))
        if not self.image.isNull():
            if self.cover.isNull():
                self.cover = self.image.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width()-self.cover.width())//2,(self.height()-self.cover.height())//2,self.cover)
            shade = QColor(color); shade.setAlpha(round(255*(1 - .75*self.transparency/100)))
            painter.fillRect(self.rect(),shade)

    def resizeEvent(self, event):
        self.cover = QPixmap(); super().resizeEvent(event)
