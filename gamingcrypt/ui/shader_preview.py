"""What the ticked shaders do, drawn on a picture of the game - the look of each one rebuilt with
QPainter (RetroArch's slang shaders only run in RetroArch): scanlines, color mask and glow, the
LCD grid, Scale2x smoothing, sharpen / blur, colors.

The picture: the newest screenshot of the game (or of the system's games), else a little scene.
"""

from __future__ import annotations

import re
from array import array
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QRadialGradient

from gamingcrypt.emulation import shaders

# the consoles' picture size (what a screenshot is brought back to)
NATIVE = {"nes": (256, 240), "snes": (256, 224), "n64": (320, 240), "gb": (160, 144), "gbc": (160, 144),
          "gba": (240, 160), "nds": (256, 192), "gc": (640, 480), "mastersystem": (256, 192),
          "megadrive": (320, 224), "gamegear": (160, 144), "segacd": (320, 224), "saturn": (320, 224),
          "dreamcast": (640, 480), "psx": (320, 240), "ps2": (640, 448), "psp": (480, 272), "pce": (256, 224),
          "atari2600": (160, 192), "arcade": (320, 240)}
MAX_WIDTH = 320  # bigger pictures (3D consoles) are drawn at this width - the preview is small
FORMAT = QImage.Format.Format_RGB32
GRID = 4  # canvas pixels per console pixel (the lines of a screen on an exact grid)


def native_size(system_id: str) -> QSize:
    w, h = NATIVE.get(system_id, (320, 240))
    if w > MAX_WIDTH:
        w, h = MAX_WIDTH, round(h * MAX_WIDTH / w)
    return QSize(w, h)


# --- the picture ------------------------------------------------------------------------------

def _file_key(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_").lower()


def find_screenshot(names: list[str], folders: list[Path]) -> Path | None:
    """The newest screenshot of one of these games: GamingCrypt's ("<name>_<date>.png") or
    RetroArch's ("<rom name>-<date>.png")."""
    keys = [k for k in (_file_key(n) for n in names) if k]
    found = []
    for folder in folders:
        try:
            files = list(Path(folder).rglob("*.png"))
        except OSError:
            continue
        for file in files:
            stem = _file_key(file.stem)
            if any(stem.startswith(k + "_") or stem.startswith(k + "-") for k in keys):
                try:
                    found.append((file.stat().st_mtime, file))
                except OSError:
                    pass
    return max(found)[1] if found else None


def crop_borders(image: QImage) -> QImage:
    """Without the black bars around the game (a full-screen screenshot)."""
    w, h = image.width(), image.height()
    small = image.scaled(min(w, 160), min(h, 100), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).convertToFormat(FORMAT)
    sw, sh = small.width(), small.height()

    def lit(x, y) -> bool:
        c = small.pixelColor(x, y)
        return c.red() + c.green() + c.blue() > 36

    cols = [x for x in range(sw) if any(lit(x, y) for y in range(0, sh, 2))]
    rows = [y for y in range(sh) if any(lit(x, y) for x in range(0, sw, 2))]
    if not cols or not rows:
        return image
    left, right = cols[0] * w // sw, (cols[-1] + 1) * w // sw
    top, bottom = rows[0] * h // sh, (rows[-1] + 1) * h // sh
    return image.copy(QRect(left, top, max(1, right - left), max(1, bottom - top)))


def sample(system_id: str, screenshot: Path | None = None) -> QImage:
    """The picture at the console's size."""
    size = native_size(system_id)
    if screenshot is not None:
        image = QImage(str(screenshot))
        if not image.isNull():
            image = crop_borders(image)
            return image.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation).convertToFormat(FORMAT)
    return scene(size.width(), size.height())


HERO = ["..rrrr..", ".rrrrrr.", ".sseses.", "sssssss.", "..ssss..", ".bbrbb..", "bbbrrbbb", "ssrrrrss",
        "..rr.rr.", ".bb...bb"]
HERO_COLORS = {"r": QColor(210, 40, 40), "s": QColor(250, 200, 150), "e": QColor(20, 20, 20), "b": QColor(40, 70, 200)}


def scene(w: int, h: int) -> QImage:
    """A little pixel-art scene: sky, sun, hills, bricks, a hero."""
    image = QImage(w, h, FORMAT)
    p = QPainter(image)
    bands = [QColor(70, 120, 230), QColor(95, 145, 240), QColor(125, 170, 248), QColor(160, 200, 252)]
    ground = h * 3 // 4
    for i, color in enumerate(bands):
        p.fillRect(0, ground * i // len(bands), w, ground // len(bands) + 1, color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 220, 80))
    p.drawEllipse(w * 3 // 4, h // 10, h // 7, h // 7)
    p.setBrush(QColor(60, 160, 70))
    p.drawEllipse(-w // 6, ground - h // 6, w // 2, h // 3)
    p.setBrush(QColor(40, 130, 55))
    p.drawEllipse(w // 3, ground - h // 9, w // 2, h // 4)
    tile = max(8, h // 14)
    for x in range(0, w, tile):
        for y in range(ground, h, tile):
            p.fillRect(x, y, tile, tile, QColor(180, 100, 50) if (x // tile + y // tile) % 2 else QColor(150, 80, 40))
            p.fillRect(x, y, tile, 1, QColor(230, 160, 100))
    bricks_y = ground - tile * 4
    for i in range(4):
        x = w // 2 + i * tile
        p.fillRect(x, bricks_y, tile, tile, QColor(250, 190, 40) if i == 1 else QColor(200, 90, 40))
        p.fillRect(x, bricks_y, tile, 1, QColor(255, 230, 160))
        p.fillRect(x + tile - 1, bricks_y, 1, tile, QColor(90, 40, 20))
    px = max(1, h // 90)
    left, top = w // 5, ground - len(HERO) * px
    for row, line in enumerate(HERO):
        for col, ch in enumerate(line):
            if ch in HERO_COLORS:
                p.fillRect(left + col * px, top + row * px, px, px, HERO_COLORS[ch])
    p.end()
    return image


# --- pixels ------------------------------------------------------------------------------------

def _channels(image: QImage) -> tuple[bytearray, int, int]:
    image = image.convertToFormat(FORMAT)
    return bytearray(bytes(image.constBits())[:image.bytesPerLine() * image.height()]), image.width(), image.height()


def _image(data: bytearray, w: int, h: int) -> QImage:
    return QImage(bytes(data), w, h, w * 4, FORMAT).copy()


def _blur(data: bytearray, w: int) -> bytearray:
    """3x3 (1 2 1) blur of every channel."""
    def shifted(values: bytearray, step: int) -> tuple[bytes, bytes]:
        return values[:step] + values[:-step], values[step:] + values[-step:]

    before, after = shifted(data, 4)
    horizontal = bytearray((a + 2 * b + c) >> 2 for a, b, c in zip(before, data, after))
    before, after = shifted(horizontal, w * 4)
    return bytearray((a + 2 * b + c) >> 2 for a, b, c in zip(before, horizontal, after))


def _clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else v


def handheld_colors(image: QImage) -> QImage:
    """Less saturated, a little darker - as an unlit GBA screen."""
    data, w, h = _channels(image)
    b, g, r = data[0::4], data[1::4], data[2::4]
    gray = [(rr * 77 + gg * 150 + bb * 29) >> 8 for rr, gg, bb in zip(r, g, b)]
    for offset, channel in ((0, b), (1, g), (2, r)):
        data[offset::4] = bytes((c * 150 + y * 70) >> 8 for c, y in zip(channel, gray))
    return _image(data, w, h)


def ntsc(image: QImage) -> QImage:
    """Colors bleeding sideways."""
    data, w, h = _channels(image)
    left, right = data[:8] + data[:-8], data[8:] + data[-8:]
    near_l, near_r = data[:4] + data[:-4], data[4:] + data[-4:]
    return _image(bytearray((a + 2 * b + 2 * c + 2 * d + e) // 8 for a, b, c, d, e in
                            zip(left, near_l, data, near_r, right)), w, h)


def fxaa(image: QImage) -> QImage:
    data, w, h = _channels(image)
    soft = _blur(data, w)
    return _image(bytearray((a + b) >> 1 for a, b in zip(data, soft)), w, h)


def sharpen(image: QImage) -> QImage:
    data, w, h = _channels(image)
    soft = _blur(data, w)
    return _image(bytearray(_clamp(a + (a - b) * 3 // 4) for a, b in zip(data, soft)), w, h)


def scale2x(image: QImage) -> QImage:
    """EPX / Scale2x: the pixel-art smoothing family xBRZ and ScaleFX belong to."""
    image = image.convertToFormat(FORMAT)
    w, h = image.width(), image.height()
    src = array("I")
    src.frombytes(bytes(image.constBits())[:w * h * 4])
    out = array("I", bytes(w * h * 16))
    ow = w * 2
    for y in range(h):
        row, up, down = y * w, max(y - 1, 0) * w, min(y + 1, h - 1) * w
        o = y * 2 * ow
        for x in range(w):
            p = src[row + x]
            a, d = src[up + x], src[down + x]
            c, b = src[row + max(x - 1, 0)], src[row + min(x + 1, w - 1)]
            i = o + x * 2
            if c == a and c != d and a != b:
                out[i] = a
            else:
                out[i] = p
            out[i + 1] = b if a == b and a != c and b != d else p
            out[i + ow] = c if d == c and d != b and c != a else p
            out[i + ow + 1] = d if b == d and b != a and d != c else p
    return QImage(out.tobytes(), ow, h * 2, ow * 4, FORMAT).copy()


GB_SHADES = [QColor(15, 56, 15), QColor(48, 98, 48), QColor(139, 172, 15), QColor(155, 188, 15)]


def gameboy_shades(image: QImage) -> QImage:
    data, w, h = _channels(image)
    shades = [(c.blue(), c.green(), c.red()) for c in GB_SHADES]
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        y = (data[i + 2] * 77 + data[i + 1] * 150 + data[i] * 29) >> 8
        out[i], out[i + 1], out[i + 2] = shades[min(3, y * 4 // 256)]
        out[i + 3] = 255
    return _image(out, w, h)


# --- the screen --------------------------------------------------------------------------------

def _fit(src: QSize, box: QSize) -> QRect:
    scale = min(box.width() / src.width(), box.height() / src.height())
    w, h = round(src.width() * scale), round(src.height() * scale)
    return QRect((box.width() - w) // 2, (box.height() - h) // 2, w, h)


def _rows(p: QPainter, area: QRect, rows: int, strength: int, part: float) -> None:
    """Dark lines over the lower part of every picture row."""
    height = area.height() / rows
    color = QColor(0, 0, 0, strength)
    for row in range(rows):
        top = area.top() + row * height
        p.fillRect(QRectF(area.left(), top + height * (1 - part), area.width(), height * part), color)


def _columns(p: QPainter, area: QRect, columns: int, strength: int, part: float) -> None:
    width = area.width() / columns
    color = QColor(0, 0, 0, strength)
    for col in range(columns):
        left = area.left() + col * width
        p.fillRect(QRectF(left + width * (1 - part), area.top(), width * part, area.height()), color)


def _mask(p: QPainter, area: QRect) -> None:
    """The red / green / blue stripes of a tube TV."""
    tile = QImage(3, 1, FORMAT)
    for x, color in enumerate((QColor(255, 175, 175), QColor(175, 255, 175), QColor(175, 175, 255))):
        tile.setPixelColor(x, 0, color)
    p.save()
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.fillRect(area, QBrush(tile))
    p.restore()


def _glow(p: QPainter, picture: QImage, area: QRect) -> None:
    soft = picture.scaled(max(1, picture.width() // 4), max(1, picture.height() // 4),
                          Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    p.save()
    p.setOpacity(0.35)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawImage(area, soft)
    p.restore()


def render(picture: QImage, ids, size: QSize) -> QImage:
    """The picture as it looks with these shaders, at the preview's size (black around)."""
    ids = shaders.clean(ids)
    rows, columns = picture.height(), picture.width()
    if "handheld_colors" in ids:
        picture = handheld_colors(picture)
    if "ntsc" in ids:
        picture = ntsc(picture)
    if "fxaa" in ids:
        picture = fxaa(picture)
    if "sharpen" in ids:
        picture = sharpen(picture)
    if "gameboy" in ids:
        picture = gameboy_shades(picture)
    look = next((i for i in ids if shaders.BY_ID[i].final), None)  # the upscaler or screen effect
    smooth = look in ("sharp_pixels", "xbrz", "scalefx", "crt", "crt_curved")
    if look in ("xbrz", "scalefx"):
        picture = scale2x(picture)
        if look == "scalefx" and picture.width() <= MAX_WIDTH:
            picture = scale2x(picture)
    elif look == "sharp_pixels":
        factor = max(1, min(size.width() // picture.width(), size.height() // picture.height()))
        picture = picture.scaled(picture.width() * factor, picture.height() * factor)  # whole pixels first
    # the screen's lines on an exact grid (4 canvas pixels per console pixel), then made smaller
    canvas = QImage(columns * GRID, rows * GRID, FORMAT)
    whole = canvas.rect()
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
    p.drawImage(whole, picture)
    if look == "scanlines":
        _rows(p, whole, rows, 120, 0.5)
    elif look in ("crt", "crt_curved"):
        _glow(p, picture, whole)
        _rows(p, whole, rows, 150, 0.5)
        _mask(p, whole)
    elif look in ("lcd", "gameboy"):
        strength = 80 if look == "gameboy" else 120
        _rows(p, whole, rows, strength, 0.25)
        _columns(p, whole, columns, strength, 0.25)
    p.end()
    out = QImage(size, FORMAT)
    out.fill(Qt.GlobalColor.black)
    area = _fit(QSize(columns, rows), size)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if look == "crt_curved":
        path = QPainterPath()
        path.addRoundedRect(QRectF(area), area.width() * 0.06, area.height() * 0.08)
        p.setClipPath(path)
    p.drawImage(area, canvas)
    if look == "crt_curved":
        shade = QRadialGradient(QPointF(area.center()), max(area.width(), area.height()) * 0.72)
        shade.setColorAt(0.55, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 200))
        p.fillRect(area, QBrush(shade))
    p.end()
    return out
