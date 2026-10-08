"""
Размеры картинки по заголовку файла — без сторонних библиотек.

    from imgsize import image_size
    image_size("assets/img/guardian.jpg")   # → (1920, 1280) или None

Читает только первые байты файла: PNG, GIF, WebP (три вида заголовка) и JPEG
(ищет маркер SOF). Неизвестный формат или битый файл — None, без исключений.
Проверено против Pillow на JPEG (обычном, прогрессивном, с EXIF), PNG, WebP
с потерями и без, GIF — совпало во всех случаях.

Внимание: у снимков с телефона в EXIF бывает «повернуть на 90°». Здесь
возвращаются размеры как они записаны в файле, до поворота, — браузер же
показывает после. Снимки для сайта сохраняйте с уже применённым поворотом.
"""
import struct


def image_size(path):
    """(ширина, высота) картинки или None, если формат не распознан."""
    try:
        with open(path, "rb") as f:
            return _read(f)
    except (OSError, struct.error):
        return None


def _read(f):
    head = f.read(32)
    if head[:8] == b"\x89PNG\r\n\x1a\n":                      # PNG: IHDR сразу после подписи
        return struct.unpack(">II", head[16:24])
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        f.seek(0)
        data = f.read(64)
        kind = data[12:16]
        if kind == b"VP8 ":                                      # WebP с потерями
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":                                      # WebP без потерь
            v = int.from_bytes(data[21:25], "little")
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":                                      # WebP расширенный
            return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
        return None
    if head[:2] == b"\xff\xd8":                                  # JPEG: идём по сегментам до SOF
        f.seek(2)
        while True:
            b = f.read(1)
            while b and b != b"\xff":
                b = f.read(1)
            while b == b"\xff":
                b = f.read(1)
            if not b:
                return None
            m = b[0]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:           # маркеры без длины
                continue
            seg = struct.unpack(">H", f.read(2))[0]
            if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):  # SOF0…SOF15, кроме DHT/JPG/DAC
                h, w = struct.unpack(">xHH", f.read(5))
                return w, h
            f.seek(seg - 2, 1)
    return None
