"""
Карта сайта, канонические адреса и карточка для мессенджеров (Open Graph).

Ничего не знает о том, кто отдаёт страницы — GitHub Pages или свой сервер:
адреса строятся только из домена в content/site.json. Сборка вызывает отсюда
функции, проверка (check.py) — те же функции, чтобы «правильный адрес»
означал одно и то же и там, и там.

    from seo import page_url, page_lastmod, sitemap_xml, og_meta
"""
import datetime
import html
import pathlib
import subprocess

from imgsize import image_size

ROOT = pathlib.Path(__file__).parent


# ─────────────────────────────── адреса ───────────────────────────────

def origin(domain):
    """https:// + домен. Кириллический домен (еон.рус) — в записи для протоколов
    (xn--…): этого требует протокол карты сайта, и так адрес одинаков везде."""
    host = domain.strip().strip("/").lower()
    host = host.removeprefix("https://").removeprefix("http://")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass  # кривой домен покажет проверка; здесь не падаем
    return f"https://{host}"


def page_url(domain, slug):
    """Канонический адрес страницы. Главная — корень сайта, без index.html:
    иначе у одной страницы два адреса, и поисковик выбирает сам."""
    if slug == "index":
        return origin(domain) + "/"
    return f"{origin(domain)}/{slug}.html"


# ─────────────────────────────── дата изменения ───────────────────────────────

_SHALLOW = None


def history_is_full():
    """Есть ли полная история git. В неполной копии (actions/checkout по умолчанию
    берёт один коммит) у всех файлов окажется дата этого коммита — то есть одна дата
    на весь сайт, честной она только выглядит. Нет git вовсе — тоже False."""
    global _SHALLOW
    if _SHALLOW is None:
        try:
            r = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10)
            _SHALLOW = r.returncode != 0 or r.stdout.strip() != "false"
        except (OSError, subprocess.SubprocessError):
            _SHALLOW = True
    return not _SHALLOW


def page_lastmod(content_file):
    """Дата последнего коммита, менявшего данные страницы (content/<страница>.json),
    в виде ГГГГ-ММ-ДД. Не дата файла в dist/: та у всех одинаковая и меняется при
    каждой сборке. Нет истории, нет git, файл ещё не в истории — None: дата
    в карте сайта необязательна, а неправдивая хуже отсутствующей."""
    if not history_is_full():
        return None
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(content_file)],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    d = r.stdout.strip()
    return d if r.returncode == 0 and len(d) == 10 else None


# ─────────────────────────────── карта сайта ───────────────────────────────

def sitemap_xml(entries):
    """entries: [(адрес, дата или None)] → текст sitemap.xml."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in entries:
        out.append("  <url>")
        out.append(f"    <loc>{html.escape(url, quote=False)}</loc>")
        if lastmod:
            out.append(f"    <lastmod>{lastmod}</lastmod>")
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


# ─────────────────────────────── карточка для мессенджеров ───────────────────────────────

def first_image(page):
    """Первый снимок страницы, у которого есть файл: сначала герой, потом по порядку.
    Пустые слоты ("src": "") пропускаются."""
    def walk(x):
        if isinstance(x, dict):
            img = x.get("image")
            if isinstance(img, dict) and str(img.get("src") or "").strip():
                yield img
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)
    for img in walk(page.get("blocks", [])):
        return img
    return None


def og_meta(page, site, slug, assets_dir=None):
    """Теги Open Graph для <head>, одной строкой на тег. Картинка — из первого снимка
    страницы, когда снимки появятся; размеры читаются из самого файла."""
    domain = site["domain"]
    url = page_url(domain, slug)
    tags = [
        ("og:type", "website"),
        ("og:site_name", site.get("site_name") or domain),
        ("og:locale", "ru_RU"),
        ("og:url", url),
        ("og:title", page.get("title", "")),
        ("og:description", page.get("description", "")),
    ]
    img = first_image(page)
    if img:
        src = str(img["src"]).strip().lstrip("/")
        tags.append(("og:image", f"{origin(domain)}/{src}"))
        if img.get("alt"):
            tags.append(("og:image:alt", img["alt"]))
        size = image_size(pathlib.Path(assets_dir or ROOT / "assets") / src)
        if size:
            tags += [("og:image:width", str(size[0])), ("og:image:height", str(size[1]))]
    lines = [f'<meta property="{k}" content="{html.escape(str(v), quote=True)}">' for k, v in tags]
    lines.append(f'<meta name="twitter:card" content="{"summary_large_image" if img else "summary"}">')
    return "\n".join(lines)


def canonical_link(site, slug):
    return f'<link rel="canonical" href="{html.escape(page_url(site["domain"], slug), quote=True)}">'


def today():
    return datetime.date.today().isoformat()
