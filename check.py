#!/usr/bin/env python3
"""
Проверка сайта еон.рус.

Проверяет данные в content/, собирает сайт и проверяет готовый dist/:
обязательные поля, лишнюю разметку, меню и подвал, сборку, ссылки между
страницами, якоря и закрытость от индексации.

Запуск:  python3 check.py   (из корня репозитория, без аргументов)
Код возврата: 0 — ошибок нет (предупреждения о страницах из PLANNED не в счёт),
1 — есть ошибки.
"""
import difflib, json, pathlib, re, shutil, subprocess, sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).parent
CONTENT = ROOT / "content"
DIST = ROOT / "dist"

# ─────────────────────────── что считается правильным ───────────────────────────

# Поля, которые build.py выводит как разметку (raw). В них разрешены
# только <br> и <em>, плюс сущности вроде &nbsp; и &lt;. Список повторяет
# build.py, а не README: там нет поля "v" табличек, хотя рендер выводит его как raw.
RAW_FIELDS = {"h1", "h1q", "lede", "text", "spec", "a", "h2", "h2q", "v"}
ALLOWED_TAGS = {"br", "em"}

# Служебные поля: не текст, разметку в них не ищем.
NOT_TEXT = {"type", "id", "href", "fill", "symbols", "slug", "cols"}

# Поля внутри каждого элемента items[], без которых рендер падает или выводит пустоту.
ITEM_FIELDS = {
    "figs": ["value", "label"],
    "cards": ["title"],
    "points": ["term", "text"],
    "steps": ["title", "text"],
    "cases": ["meta", "title", "text"],
    "faq": ["q", "a"],
}
BLOCK_FIELDS = {"hero": ["eyebrow", "h1", "lede"], "form": ["placeholder"]}
BLOCK_TYPES = {"hero", "figs", "cards", "points", "steps", "cases", "plates", "faq", "circuit", "form"}
HEAD_BLOCKS = {"cards", "points", "steps", "cases", "plates", "faq", "form"}  # шапка раздела через _head()
CIRCUIT_SYMBOLS = {"saw", "cap", "dot"}
CARD_FILLS = {"accent", "slate"}

# Страницы первой волны, которые ещё не написаны. Ссылка на страницу из этого
# списка — предупреждение: страница появится, сборку это не валит. Ссылка на
# любую другую несуществующую страницу — ошибка: скорее всего, опечатка.
# Написал страницу — убери её отсюда. Список опустел — режим предупреждений
# выключился сам. Список живёт здесь, а не в STATUS.md: разбирать таблицу
# из markdown ненадёжно, а этот файл и так правят вместе со страницами.
PLANNED = {
    "ups_boiler", "forklift", "skif", "damping", "substations", "mobile", "custom",
    "about", "buy", "support", "docs", "partners", "articles", "legal",
}

TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][\w-]*)([^>]*)>")
ENTITY_RE = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")


# ─────────────────────────────── сбор ошибок ───────────────────────────────

class Report:
    """Ошибки, сгруппированные по месту: странице, общему файлу, сборке."""

    # Виды, которые НЕ валят сборку: пока идёт первая волна, ссылки на
    # ещё не написанные страницы — это нормальное состояние работы, а не поломка.
    SOFT_KINDS = {"ненаписанная страница"}

    def __init__(self):
        self.groups = {}

    def add(self, group, kind, msg):
        self.groups.setdefault(group, []).append((kind, msg))

    def count(self):
        return sum(len(v) for v in self.groups.values())

    def hard(self):
        """Ошибки, из-за которых сборку публиковать нельзя."""
        return sum(1 for v in self.groups.values() for k, _ in v if k not in self.SOFT_KINDS)

    def soft(self):
        return self.count() - self.hard()


def page_group(slug):
    return f"content/{slug}.json  →  {slug}.html"

SITE_GROUP = "content/site.json  (шапка, меню и подвал — на всех страницах)"
BUILD_GROUP = "Сборка (python3 build.py)"
ROBOTS_GROUP = "dist/robots.txt"


def is_external(href):
    return bool(re.match(r"^[a-zA-Z][\w+.-]*:", href)) or href.startswith("//")


def empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or v == [] or v == {}


def short(s, n=40):
    s = re.sub(r"<[^>]*>", "", str(s)).replace("&nbsp;", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def block_label(i, b):
    title = b.get("h2") or b.get("h1") or b.get("eyebrow") or ""
    t = b.get("type", "?")
    return f"блок {i + 1} ({t}" + (f", «{short(title)}»" if title else "") + ")"


# ─────────────────────────────── данные ───────────────────────────────

def load_pages(rep):
    """Читает content/*.json. Битый JSON — сразу ошибка с номером строки."""
    pages, site, broken = {}, None, set()
    for src in sorted(CONTENT.glob("*.json")):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            group = SITE_GROUP if src.name == "site.json" else page_group(src.stem)
            rep.add(group, "json", f"файл не читается как JSON: строка {err.lineno}, "
                                   f"позиция {err.colno} — {err.msg}")
            broken.add(src.stem)
            continue
        if src.name == "site.json":
            site = data
        else:
            slug = data.get("slug", src.stem) if isinstance(data, dict) else src.stem
            pages[slug] = data
    return pages, site, broken


def check_page_fields(slug, page, rep):
    """Пункт 5: обязательные поля страницы и блоков."""
    g = page_group(slug)

    def need(obj, keys, where):
        for k in keys:
            if empty(obj.get(k)):
                state = "нет поля" if k not in obj else "поле пустое"
                rep.add(g, "поле", f"{where}: {state} «{k}»")

    if not isinstance(page, dict):
        rep.add(g, "поле", "в файле не объект {…}, а что-то другое")
        return
    need(page, ["title", "description"], "страница")
    blocks = page.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        rep.add(g, "поле", "страница: нет блоков (поле «blocks» отсутствует или пустое)")
        return

    for i, b in enumerate(blocks):
        where = block_label(i, b)
        t = b.get("type")
        if t not in BLOCK_TYPES:
            rep.add(g, "поле", f"{where}: неизвестный тип блока «{t}» — "
                               f"бывают {', '.join(sorted(BLOCK_TYPES))}")
            continue
        need(b, BLOCK_FIELDS.get(t, []), where)

        # Шапка раздела: без h2 рендер молча выбрасывает lede и h2q.
        if t in HEAD_BLOCKS and empty(b.get("h2")):
            for k in ("lede", "h2q"):
                if not empty(b.get(k)):
                    rep.add(g, "поле", f"{where}: есть «{k}», но нет «h2» — "
                                       f"без заголовка «{k}» на страницу не попадёт")

        if t in ITEM_FIELDS or t == "plates":
            items = b.get("items")
            if not isinstance(items, list) or not items:
                rep.add(g, "поле", f"{where}: нет элементов (поле «items» отсутствует или пустое)")
                items = []
            for j, it in enumerate(items):
                iw = f"{where}, items[{j}]"
                if t == "plates":
                    check_plate(it, iw, need)
                else:
                    need(it, ITEM_FIELDS[t], iw)
                if t == "cards":
                    if it.get("link") is not None:
                        need(it["link"], ["href", "label"], iw + ".link")
                    if it.get("fill") and it["fill"] not in CARD_FILLS:
                        rep.add(g, "поле", f"{iw}: fill «{it['fill']}» — такого нет, бывает accent или slate")
            if t == "figs" and items and len(items) not in (3, 4):
                rep.add(g, "поле", f"{where}: цифр {len(items)}, а полоса рассчитана на 3 или 4")

        if t == "cards" and b.get("cols") not in (2, 3, 4):
            state = "нет поля «cols»" if "cols" not in b else f"cols = {b['cols']!r}"
            rep.add(g, "поле", f"{where}: {state} — должно быть 2, 3 или 4")

        if t == "hero":
            for j, c in enumerate(b.get("cta", [])):
                need(c, ["label", "href"], f"{where}, cta[{j}]")
            if b.get("plate"):
                check_plate(b["plate"], where + ", plate", need)

        if t == "circuit":
            bad = [s for s in b.get("symbols", []) if s not in CIRCUIT_SYMBOLS]
            if bad:
                rep.add(g, "поле", f"{where}: неизвестные символы {bad} — бывают saw, cap, dot")


def check_plate(p, where, need):
    """Табличка (с rows) или карточка рядом с ней (без rows) — у них разный минимум."""
    if p.get("rows") is not None:
        need(p, ["head", "rows"], where)
        for k, r in enumerate(p.get("rows") or []):
            need(r, ["k", "v"], f"{where}.rows[{k}]")
        if p.get("button") is not None:
            need(p["button"], ["href", "label"], where + ".button")
    else:
        need(p, ["title", "text"], where)
        for k, c in enumerate(p.get("cta", [])):
            need(c, ["label", "href"], f"{where}.cta[{k}]")


def walk_strings(obj, path=""):
    """Все строки внутри данных: (путь, имя поля, значение)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        key = re.sub(r"\[\d+\]$", "", path).rsplit(".", 1)[-1]
        yield path, key, obj


def readable_path(page, path):
    """blocks[4].items[1].text → блок 5 (cards, «Исполнения»), items[1].text"""
    m = re.match(r"blocks\[(\d+)\]\.?(.*)", path)
    if not m or not isinstance(page, dict):
        return path
    i = int(m.group(1))
    try:
        label = block_label(i, page["blocks"][i])
    except (KeyError, IndexError, TypeError):
        return path
    return f"{label}, {m.group(2)}" if m.group(2) else label


def markup_problems(key, value):
    """Пункт 6: что не так с разметкой в одном текстовом поле. → [(сообщение, позиция)]"""
    out = []
    tags = list(TAG_RE.finditer(value))
    if key in RAW_FIELDS:
        bad = [m for m in tags if m.group(2).lower() not in ALLOWED_TAGS]
        if bad:
            names = ", ".join(dict.fromkeys(m.group(0) for m in bad))
            out.append((f"лишние теги {names} — разрешены только <br> и <em>", bad[0].start()))
        attrs = [m for m in tags if m.group(2).lower() in ALLOWED_TAGS and m.group(3).strip() not in ("", "/")]
        if attrs:
            out.append((f"тег {attrs[0].group(0)} с атрибутами — разрешён только голый "
                        f"<{attrs[0].group(2).lower()}>", attrs[0].start()))
        ems = [m for m in tags if m.group(2).lower() == "em"]
        opened = sum(1 for m in ems if not m.group(1))
        if ems and opened != len(ems) - opened:
            out.append((f"<em> открыт {opened} раз, закрыт {len(ems) - opened} — "
                        f"курсив растечётся дальше по странице", ems[0].start()))
    else:
        found = tags + list(ENTITY_RE.finditer(value))
        if found:
            found.sort(key=lambda m: m.start())
            names = ", ".join(dict.fromkeys(m.group(0) for m in found))
            out.append((f"{names} в поле «{key}», где разметка не работает — "
                        f"на сайте будет видно как текст", found[0].start()))
    return out


def snippet(value, pos, n=70):
    """Кусок значения как есть, с разметкой, вокруг места ошибки."""
    value = value.replace("\n", " ")
    if len(value) <= n:
        return value
    a = max(0, min(pos - 20, len(value) - n))
    return ("…" if a else "") + value[a:a + n] + ("…" if a + n < len(value) else "")


def check_page_markup(slug, page, rep):
    g = page_group(slug)
    for path, key, value in walk_strings(page):
        if key in NOT_TEXT:
            continue
        for msg, pos in markup_problems(key, value):
            rep.add(g, "разметка", f"{readable_path(page, path)}: {msg}\n        значение: «{snippet(value, pos)}»")


def site_links(site):
    """Все ссылки из site.json: (href, где в меню/подвале)."""
    out = []
    for item in site.get("nav", []):
        if item.get("href"):
            out.append((item["href"], f"меню «{item.get('label')}»"))
        for c in item.get("children", []):
            out.append((c.get("href", ""), f"меню «{item.get('label')} → {c.get('label')}»"))
    for col in site.get("footer", []):
        for i in col.get("items", []):
            if i.get("href"):
                out.append((i["href"], f"подвал «{col.get('head')} → {i.get('label')}»"))
        for i in col.get("items2", []):
            out.append((i.get("href", ""), f"подвал «{col.get('head2')} → {i.get('label')}»"))
    out.append((site.get("form_href", "#form"), "кнопка и контакты в шапке (form_href)"))
    return out


def missing_page(target, known):
    """Ссылка на страницу, которой нет в content/: (вид, сообщение).
    Из списка PLANNED — предупреждение, иначе ошибка с подсказкой, на что похоже."""
    slug = target.removesuffix(".html")
    if slug in PLANNED:
        return "ненаписанная страница", f"страницы {target} пока нет (нужен content/{slug}.json)"
    msg = f"страницы {target} нет, и она не в списке ожидаемых (PLANNED в check.py)"
    near = difflib.get_close_matches(slug, sorted(known | PLANNED), n=1, cutoff=0.6)
    if near:
        msg += f" — опечатка? похоже на {near[0]}.html"
    else:
        msg += " — опечатка? если страница действительно планируется, добавьте её в PLANNED"
    return "ссылка", msg


def check_planned(slugs, rep):
    """Страница написана, а из PLANNED не убрана: список перестаёт пустеть,
    и ссылка на эту страницу после её удаления прошла бы предупреждением."""
    for slug in sorted(PLANNED & slugs):
        rep.add(page_group(slug), "список ожидаемых",
                f"страница написана, но всё ещё числится в PLANNED в check.py — уберите её оттуда")


def check_site(site, slugs, rep):
    """Пункт 4: меню и подвал ссылаются на страницы, которые есть в content/.
    Плюс разметка в текстах site.json."""
    missing = {}
    for href, where in site_links(site):
        if empty(href):
            rep.add(SITE_GROUP, "меню", f"{where}: пустая ссылка")
            continue
        if is_external(href):
            continue
        page = href.split("#", 1)[0]
        if page and page.removesuffix(".html") not in slugs:
            missing.setdefault(page, []).append(where)
    for page, wheres in sorted(missing.items()):
        kind, msg = missing_page(page, slugs)
        rep.add(SITE_GROUP, kind, f"{page}: {msg}\n"
                                  f"        ссылаются: " + "\n                   ".join(wheres))

    # draft — служебная полоса «макет»: build.py выводит её как разметку, и <b> в ней
    # стоит намеренно. Снимается к выпуску (README, «Состояние»), поэтому здесь не проверяется.
    skip = {"_", "logo", "logo_viewbox", "draft", "form_href"} | NOT_TEXT
    for path, key, value in walk_strings(site):
        if path.split(".")[0].split("[")[0] in skip or key in skip:
            continue
        for msg, pos in markup_problems(key, value):
            rep.add(SITE_GROUP, "разметка", f"{path}: {msg}\n        значение: «{snippet(value, pos)}»")
    return set(missing)


# ─────────────────────────────── сборка ───────────────────────────────

def build(rep, data_errors):
    """Пункт 1. dist/ стирается заранее, чтобы старые файлы не маскировали пропавшие страницы."""
    if DIST.exists():
        shutil.rmtree(DIST)
    r = subprocess.run([sys.executable, str(ROOT / "build.py")], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 0:
        return True
    tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
    msg = "build.py упал, ссылки, якоря и индексацию проверить не по чему.\n" + \
          "\n".join("        " + line for line in tail)
    if data_errors:
        msg += "\n      Почти наверняка причина — в ошибках данных, перечисленных выше."
    rep.add(BUILD_GROUP, "сборка", msg)
    return False


# ─────────────────────────────── готовые страницы ───────────────────────────────

class PageParser(HTMLParser):
    """Собирает со страницы id, ссылки (с текстом и зоной: шапка/подвал/тело) и meta robots."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.robots = set(), [], []
        self.zone, self.depth = [], 0
        self.cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag in ("header", "footer"):
            self.zone.append(tag)
        if tag == "meta" and (a.get("name") or "").lower() == "robots":
            self.robots.append(a.get("content") or "")
        if tag in ("a", "link") and "href" in a:
            zone = self.zone[-1] if self.zone else "body"
            link = {"href": a["href"] or "", "text": "", "zone": zone, "line": self.getpos()[0], "tag": tag}
            self.links.append(link)
            if tag == "a":
                self.cur = link

    def handle_endtag(self, tag):
        if tag in ("header", "footer") and self.zone:
            self.zone.pop()
        if tag == "a":
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None:
            self.cur["text"] += data


def parse_dist():
    pages = {}
    for f in sorted(DIST.glob("*.html")):
        p = PageParser()
        p.feed(f.read_text(encoding="utf-8"))
        pages[f.name] = p
    return pages


def check_dist(pages, data, known, site_missing, rep):
    """Пункты 2, 3, 7: ссылки, якоря, noindex на каждой странице."""
    shared = {}  # ошибки шапки/подвала: одинаковы на всех страницах, выводятся один раз
    for name, p in pages.items():
        slug = name.removesuffix(".html")
        g = page_group(slug)
        page = data.get(slug)
        hrefs = {}
        for path, key, value in walk_strings(page):
            if key == "href":
                hrefs.setdefault(value, []).append(readable_path(page, path))

        found = {}  # (вид, адрес, что не так) → тексты ссылок; одна строка на одну битую цель
        for link in p.links:
            href = link["href"]
            if not href.strip():
                problem = ("ссылка", "пустая ссылка")
            elif is_external(href):
                continue
            else:
                target, _, anchor = href.partition("#")
                problem = None
                if target and not (DIST / target).is_file():
                    if link["zone"] != "body" and target in site_missing:
                        continue  # уже сказано в разделе site.json
                    if target.endswith(".html"):
                        problem = missing_page(target, known)
                    else:
                        problem = ("ссылка", f"файла {target} нет в dist/")
                elif anchor:
                    tp = pages.get(target) if target else p
                    if tp is not None and anchor not in tp.ids:
                        on = f"на странице {target}" if target else "на этой странице"
                        problem = ("якорь", f"якоря #{anchor} {on} нет "
                                            f"(нужен блок с \"id\": \"{anchor}\")")
            if problem is None:
                continue
            kind, msg = problem
            text = short(link["text"]).rstrip(" →") or f"<{link['tag']}>"
            if link["zone"] != "body":
                shared.setdefault((kind, href, msg), set()).add(name)
                continue
            texts = found.setdefault((kind, href, msg), [])
            if text not in texts:
                texts.append(text)

        for (kind, href, msg), texts in found.items():
            line = f"{href}: {msg}\n        ссылки: {', '.join('«' + t + '»' for t in texts)}"
            if hrefs.get(href):
                line += "\n        в данных: " + "\n                  ".join(hrefs[href])
            rep.add(g, kind, line)

        # Пункт 7: noindex на каждой странице.
        if not any("noindex" in c.lower() for c in p.robots):
            got = f" (стоит: {p.robots[0]!r})" if p.robots else ""
            rep.add(g, "индексация", f"нет <meta name=\"robots\" content=\"noindex…\">{got} — "
                                     f"страница открыта для поисковиков")

    for (kind, href, msg), names in sorted(shared.items()):
        n = "на всех страницах" if len(names) == len(pages) else "на " + ", ".join(sorted(names))
        rep.add(SITE_GROUP, kind, f"{href} в шапке или подвале ({n}): {msg}")

    # Пункт 7: robots.txt запрещает обход целиком.
    robots = DIST / "robots.txt"
    if not robots.is_file():
        rep.add(ROBOTS_GROUP, "индексация", "файла нет — сайт открыт для обхода")
    else:
        lines = [l.split("#")[0].strip().lower() for l in robots.read_text(encoding="utf-8").splitlines()]
        if "user-agent: *" not in lines or "disallow: /" not in lines:
            rep.add(ROBOTS_GROUP, "индексация", "нет пары «User-agent: *» + «Disallow: /» — "
                                                "сайт открыт для обхода")


# ─────────────────────────────── вывод ───────────────────────────────

def print_report(rep, stats):
    print("Проверка сайта еон.рус\n")
    if not rep.groups:
        print(f"✓ Всё чисто: {stats}.")
        return
    order = sorted(rep.groups, key=lambda g: (g == BUILD_GROUP, g == ROBOTS_GROUP, g == SITE_GROUP, g))
    for g in order:
        items = rep.groups[g]
        hard = [i for i in items if i[0] not in Report.SOFT_KINDS]
        soft = [i for i in items if i[0] in Report.SOFT_KINDS]
        mark = "✗" if hard else "·"
        tail = f" — {len(hard)}" if hard else ""
        tail += f" (+{len(soft)} ждут своей страницы)" if soft and hard else ""
        if soft and not hard:
            tail = f" — {len(soft)} ждут своей страницы"
        print(f"{mark} {g}{tail}")
        for kind, msg in hard + soft:
            print(f"    [{kind}] {msg}")
        print()
    h, w = rep.hard(), rep.soft()
    parts = []
    if h:
        parts.append(f"{h} {plural(h, 'ошибка', 'ошибки', 'ошибок')}")
    if w:
        parts.append(f"{w} {plural(w, 'предупреждение', 'предупреждения', 'предупреждений')}")
    print(f"Итого: {' и '.join(parts)} "
          f"в {len(rep.groups)} {plural(len(rep.groups), 'месте', 'местах', 'местах')} ({stats}).")


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def main():
    rep = Report()
    data, site, broken = load_pages(rep)
    site_missing = set()
    if site is None and SITE_GROUP not in rep.groups:
        rep.add(SITE_GROUP, "json", "файла content/site.json нет")
    check_planned(set(data) | broken, rep)
    for slug, page in data.items():
        check_page_fields(slug, page, rep)
        check_page_markup(slug, page, rep)
    if site is not None:
        # страница с битым JSON существует, просто не читается — об этом уже сказано выше
        site_missing = check_site(site, set(data) | broken, rep)

    stats = f"страниц в content/: {len(data)}"
    if build(rep, rep.count() > 0):
        pages = parse_dist()
        check_dist(pages, data, set(data) | broken, site_missing, rep)
        links = sum(len(p.links) for p in pages.values())
        stats += f", собрано: {len(pages)}, ссылок проверено: {links}"
    print_report(rep, stats)
    if rep.soft() and not rep.hard():
        print("\nОшибок нет. Предупреждений: "
              f"{rep.soft()} — это ссылки на страницы, которые ещё не написаны.\n"
              "Пока идёт первая волна, это рабочее состояние: сборку они не валят.")
    elif rep.soft():
        print(f"\nИз них предупреждений: {rep.soft()} (ненаписанные страницы, сборку не валят).")
    sys.exit(1 if rep.hard() else 0)


if __name__ == "__main__":
    main()
