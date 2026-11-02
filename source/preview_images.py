from pathlib import Path
from PySide6.QtCore import QSize, QRect, Qt
from PySide6.QtGui import QImageReader, QImage, QPainter, QColor


def save_portrait(source: Path, destination: Path):
    """Apply EXIF orientation and center-crop to a 900x1200 portrait."""
    if source.stat().st_size > 40 * 1024**2:
        raise ValueError('请选择小于 40 MB 的图片。')
    reader = QImageReader(str(source)); reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        size.scale(QSize(3000, 3000), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    if image.isNull():
        raise ValueError('图片无法读取，请选择 PNG、JPEG、WebP 或 BMP。')
    width, height = image.width(), image.height()
    if width * 4 > height * 3:
        crop_w, crop_h = max(1, height * 3 // 4), height
    else:
        crop_w, crop_h = width, max(1, width * 4 // 3)
    image = image.copy(QRect((width - crop_w) // 2, (height - crop_h) // 2, crop_w, crop_h))
    image = image.scaled(900, 1200, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.casefold() in {'.jpg', '.jpeg'}:
        canvas = QImage(900, 1200, QImage.Format.Format_RGB32)
        canvas.fill(QColor('#131722'))
        painter = QPainter(canvas); painter.drawImage(0, 0, image); painter.end()
        image = canvas
    if not image.save(str(destination), 'JPEG' if destination.suffix.casefold() in {'.jpg', '.jpeg'} else 'PNG', 95):
        raise OSError('无法保存裁剪后的预览图。')
