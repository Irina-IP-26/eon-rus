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
import difflib, html, json, pathlib, re, shutil, subprocess, sys
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
BLOCK_TYPES = {"hero", "figs", "cards", "points", "steps", "cases", "plates", "faq", "circuit", "form", "table"}
HEAD_BLOCKS = {"cards", "points", "steps", "cases", "plates", "faq", "form", "table"}  # шапка раздела через _head()
TABLE_ALIGN = {"right"}  # по умолчанию — влево; другого выравнивания у колонки не бывает

# Ячейка таблицы: blocks[N].rows[M].<колонка> или blocks[N].groups[K].rows[M].<колонка>.
# Колонку могут назвать как угодно — text, v, href, — поэтому разметку в ячейках
# проверяем по месту, а не по имени ключа: в ячейке не работает никакая.
TABLE_CELL_RE = re.compile(r"^blocks\[(\d+)\]\.(?:groups\[\d+\]\.)?rows\[\d+\]\.[^.\[]+$")
CIRCUIT_SYMBOLS = {"saw", "cap", "dot"}
CARD_FILLS = {"accent", "slate"}

# Страницы первой волны, которые ещё не написаны. Ссылка на страницу из этого
# списка — предупреждение: страница появится, сборку это не валит. Ссылка на
# любую другую несуществующую страницу — ошибка: скорее всего, опечатка.
# Написал страницу — убери её отсюда. Список опустел — режим предупреждений
# выключился сам. Список живёт здесь, а не в STATUS.md: разбирать таблицу
# из markdown ненадёжно, а этот файл и так правят вместе со страницами.
PLANNED = {
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

        if t == "table":
            check_table(b, where, g, rep, need)


def check_table(b, where, g, rep, need):
    """Блок table: колонки, группы, строки. Главное — ключ строки, которого нет
    в columns: build.py такую ячейку не выведет, и значение пропадёт молча."""
    cols = b.get("columns")
    keys = []
    if not isinstance(cols, list) or not cols:
        rep.add(g, "поле", f"{where}: нет колонок (поле «columns» отсутствует или пустое)")
        cols = []
    for n, col in enumerate(cols):
        cw = f"{where}, columns[{n}]"
        if not isinstance(col, dict):
            rep.add(g, "поле", f"{cw}: колонка должна быть объектом {{\"key\": …, \"label\": …}}")
            continue
        need(col, ["key", "label"], cw)
        k = col.get("key")
        if not empty(k):
            if k in keys:
                rep.add(g, "поле", f"{cw}: ключ «{k}» повторяется — у двух колонок были бы одни и те же значения")
            keys.append(k)
        if col.get("align") is not None and col["align"] not in TABLE_ALIGN:
            rep.add(g, "поле", f"{cw}: align «{col['align']}» — бывает только \"right\" (по умолчанию влево)")

    has_groups, has_rows = "groups" in b, "rows" in b
    if has_groups and has_rows:
        rep.add(g, "поле", f"{where}: есть и «groups», и «rows» — должно быть что-то одно; "
                           f"строки из «rows» при группах на страницу не попадут")
    if has_groups:
        groups = b["groups"]
        if not isinstance(groups, list) or not groups:
            rep.add(g, "поле", f"{where}: «groups» пустой — в таблице нет ни одной строки")
            groups = []
        named = []
        for k, grp in enumerate(groups):
            gw = f"{where}, groups[{k}]"
            if not isinstance(grp, dict):
                rep.add(g, "поле", f"{gw}: группа должна быть объектом {{\"title\": …, \"rows\": […]}}")
                continue
            need(grp, ["title"], gw)
            if not empty(grp.get("title")):
                gw = f"{where}, группа «{short(grp['title'])}»"
            named.append((gw, grp.get("rows")))
    elif has_rows:
        named = [(where, b["rows"])]
    else:
        rep.add(g, "поле", f"{where}: нет строк — нужно «rows» или «groups»")
        named = []

    extra = {}  # ключ, которого нет в columns → строки, где он встретился
    for gw, rows in named:
        if not isinstance(rows, list) or not rows:
            rep.add(g, "поле", f"{gw}: нет строк (поле «rows» отсутствует или пустое)")
            continue
        for m, row in enumerate(rows):
            if not isinstance(row, dict):
                rep.add(g, "поле", f"{gw}, строка {m + 1}: строка должна быть объектом {{колонка: значение}}")
                continue
            first = row.get(keys[0]) if keys else None
            rw = f"{gw}, строка {m + 1}" + (f" («{short(first)}»)" if not empty(first) else "")
            for k in row:
                if keys and k not in keys:
                    extra.setdefault(k, []).append(rw)
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    rep.add(g, "поле", f"{rw}: в ячейке «{k}» не текст, а {'список' if isinstance(v, list) else 'объект'}")
            if keys and all(empty(row.get(k)) for k in keys):
                rep.add(g, "поле", f"{rw}: строка пустая — ни одна ячейка не заполнена")

    # Одна строка на ключ, а не на каждую строку таблицы: опечатку в имени колонки
    # обычно копируют во все строки, и двадцать одинаковых сообщений её только прячут.
    for k, where_rows in extra.items():
        n, cols_list = len(where_rows), ", ".join(keys)
        if n == 1:
            rep.add(g, "поле", f"{where_rows[0]}: ключа «{k}» нет в columns — ячейка не отрисуется, "
                               f"значение пропадёт; колонки: {cols_list}")
        else:
            first = where_rows[0].removeprefix(where + ", ")
            rep.add(g, "поле", f"{where}: ключа «{k}» нет в columns, а он есть в {n} строках "
                               f"(первая: {first}) — эти ячейки не отрисуются; колонки: {cols_list}")


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


def markup_problems(key, value, cell=False):
    """Пункт 6: что не так с разметкой в одном текстовом поле. → [(сообщение, позиция)]
    cell — ячейка таблицы: разметка в ней не работает никакая, как бы ни звалась колонка."""
    out = []
    tags = list(TAG_RE.finditer(value))
    if key in RAW_FIELDS and not cell:
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
            where = f"в ячейке «{key}»" if cell else f"в поле «{key}»"
            out.append((f"{names} {where}, где разметка не работает — "
                        f"на сайте будет видно как текст", found[0].start()))
    return out


def snippet(value, pos, n=70):
    """Кусок значения как есть, с разметкой, вокруг места ошибки."""
    value = value.replace("\n", " ")
    if len(value) <= n:
        return value
    a = max(0, min(pos - 20, len(value) - n))
    return ("…" if a else "") + value[a:a + n] + ("…" if a + n < len(value) else "")


def _block_type(page, i):
    try:
        return page["blocks"][i].get("type")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def check_page_markup(slug, page, rep):
    g = page_group(slug)
    for path, key, value in walk_strings(page):
        m = TABLE_CELL_RE.match(path)
        cell = bool(m) and _block_type(page, int(m.group(1))) == "table"
        if key in NOT_TEXT and not cell:
            continue
        for msg, pos in markup_problems(key, value, cell):
            rep.add(g, "разметка", f"{readable_path(page, path)}: {msg}\n        значение: «{snippet(value, pos)}»")


# ─────────────────────── границы диапазона против таблицы ───────────────────────
# Колонка таблицы с "bounds": true объявляет: минимум и максимум её значений —
# официальный диапазон линейки. Тогда «от X до Y» с той же единицей в любом
# тексте страницы обязано совпадать с ним, а одиночное число — быть в таблице.
# Колонки без отметки не участвуют: на странице полно законных чисел с единицами
# (220 В сети, 3000 циклов, 36 месяцев), и угадывать, какие из них про линейку,
# проверка не должна — это заявляет автор данных.

# Латиница, неотличимая на глаз от кириллицы: «A·ч» с латинской A — та же единица.
LOOKALIKE = str.maketrans("AaBCcEeHKkMOoPpTXxy", "АаВСсЕеНКкМОоРрТХху")
# Единица словами → сокращение (после снятия разделителей и регистра).
UNIT_WORDS = [
    (r"киловатт-?час\w*", "квтч"), (r"ватт-?час\w*", "втч"), (r"ампер-?час\w*", "ач"),
    (r"киловатт\w*", "квт"), (r"ватт\w*", "вт"), (r"вольт\w*", "в"), (r"ампер\w*", "а"),
    (r"килограмм\w*", "кг"), (r"циклов|цикла|цикл", "цикл"),
]
NUM = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
UNIT = r"°?[A-Za-zА-Яа-яЁё]+(?:[-·⋅*.][A-Za-zА-Яа-яЁё]+)*(?![\dA-Za-zА-Яа-яЁё])"
# Число не должно продолжать слово или другое число: «ЕОН-24В150-Т» — артикул, не «150».
def _n(name):
    return rf"(?<![\dA-Za-zА-Яа-яЁё.,])(?P<{name}>[−+-]?(?:{NUM}))(?P<{name}plus>\+)?"
RANGE_FROM_RE = re.compile(rf"\bот\s+{_n('x')}\s*(?P<ux>{UNIT})?\s*до\s+{_n('y')}\s*(?P<uy>{UNIT})", re.I)
RANGE_DASH_RE = re.compile(rf"{_n('x')}\s*(?P<ux>{UNIT})?\s*[–—…-]\s*{_n('y')}\s*(?P<uy>{UNIT})")
SINGLE_RE = re.compile(rf"{_n('n')}\s*(?P<u>{UNIT})")


def norm_unit(u):
    """«А·ч», «Ач», «A·ч» (латинская A), «ампер-часов» → «ач»."""
    u = (u or "").translate(LOOKALIKE).lower().replace("ё", "е")
    for pat, short_u in UNIT_WORDS:
        if re.fullmatch(pat, u):
            return short_u
    return re.sub(r"[\s·⋅*.\-]", "", u)  # ° остаётся: «°С» — не «с»


def num(s):
    return float(re.sub(r"[ \u00a0\u202f+]", "", s).replace(",", ".").replace("−", "-"))


def fmt(x):
    return f"{x:g}".replace(".", ",")


def plain(value):
    """Текст поля без разметки: <br> и теги — пробел, &nbsp; — пробел."""
    return html.unescape(re.sub(r"<[^>]*>", " ", value)).replace("\u00a0", " ")


def table_bounds(page, g, rep):
    """Значения колонок с bounds: {единица: {"vals": {значение: модель}, "col": подпись}}."""
    out = {}
    for i, b in enumerate(page.get("blocks", [])):
        if b.get("type") != "table" or not isinstance(b.get("columns"), list):
            continue
        cols = [c for c in b["columns"] if isinstance(c, dict)]
        first = cols[0].get("key") if cols else None
        groups = b.get("groups") if b.get("groups") else [{"rows": b.get("rows") or []}]
        for col in cols:
            if "bounds" in col and col["bounds"] is not True:
                rep.add(g, "диапазон", f"{block_label(i, b)}, колонка «{col.get('label')}»: bounds = "
                                       f"{col['bounds']!r} — бывает только true")
            if col.get("bounds") is not True:
                continue
            # Единица может стоять в заголовке колонки: «Ёмкость, А·ч» и голые числа в ячейках.
            label_unit = col.get("label", "").rpartition(",")[2].strip() if "," in col.get("label", "") else ""
            for grp in groups if isinstance(groups, list) else []:
                for row in (grp.get("rows") or []) if isinstance(grp, dict) else []:
                    if not isinstance(row, dict):
                        continue
                    v = row.get(col.get("key"))
                    if empty(v):
                        continue
                    text = plain(str(v))
                    found = [(m.group("n"), m.group("u")) for m in SINGLE_RE.finditer(text)]
                    if not found and label_unit and re.fullmatch(rf"\s*(?:{NUM})\s*", text):
                        found = [(text.strip(), label_unit)]
                    if not found:
                        rep.add(g, "диапазон", f"{block_label(i, b)}, колонка «{col.get('label')}» с bounds: "
                                               f"ячейка «{short(text)}» не читается как число с единицей — "
                                               f"она не попадёт в диапазон линейки")
                        continue
                    model = short(row.get(first, "")) if first else ""
                    for n, u in found:
                        e = out.setdefault(norm_unit(u), {"vals": {}, "unit": u, "col": col.get("label")})
                        e["vals"].setdefault(num(n), model)
    return out


def lineup_rows(page):
    """Строк в модельном ряду страницы: во всех таблицах, где есть колонка с bounds.
    Отметка bounds уже значит «это и есть модельный ряд», вторая не нужна; таблица
    без неё (батарейные модули рядом с конфигурациями) в счёт не идёт."""
    n = 0
    for b in page.get("blocks", []):
        if b.get("type") != "table" or not isinstance(b.get("columns"), list):
            continue
        if not any(isinstance(c, dict) and c.get("bounds") is True for c in b["columns"]):
            continue
        groups = b.get("groups") if b.get("groups") else [{"rows": b.get("rows") or []}]
        n += sum(len(g.get("rows") or []) for g in groups if isinstance(g, dict))
    return n


def page_lineups(data, broken, rep):
    """Модельный ряд каждой страницы: свои таблицы с bounds плюс таблицы страницы из lineup.
    → {slug: {"units": {…}, "rows": N, "pages": [откуда]}}. Свои не подменяются, а складываются:
    появись на продающей странице своя отмеченная таблица — молча терять её нельзя."""
    own = {}
    for slug, page in data.items():
        if isinstance(page, dict):
            units = table_bounds(page, page_group(slug), rep)
            rows = lineup_rows(page)
            own[slug] = {"units": units, "rows": rows, "pages": [slug] if units or rows else []}
    out = {}
    for slug, e in own.items():
        units = {u: dict(v, vals=dict(v["vals"])) for u, v in e["units"].items()}
        res = {"units": units, "rows": e["rows"], "pages": list(e["pages"])}
        q = data[slug].get("lineup")
        if q is not None:
            g = page_group(slug)
            if not isinstance(q, str) or not q.strip():
                rep.add(g, "диапазон", f"страница: lineup = {q!r} — нужно имя страницы модельного ряда, "
                                       f"например \"guardian-lineup\"")
            elif q.endswith(".html"):
                rep.add(g, "диапазон", f"страница: lineup = «{q}» — имя страницы без .html: "
                                       f"«{q.removesuffix('.html')}»")
            elif q == slug:
                rep.add(g, "диапазон", f"страница: lineup = «{q}» — страница ссылается сама на себя; "
                                       f"свои таблицы с bounds и так в силе, поле не нужно")
            elif q in broken:
                pass  # страница есть, но её JSON не читается — об этом уже сказано
            elif q not in own:
                rep.add(g, "диапазон", f"страница: lineup = «{q}» — такой страницы нет (нужен content/{q}.json)")
            elif not own[q]["units"]:
                rep.add(g, "диапазон", f"страница: lineup = «{q}» — на странице {q} нет ни одной колонки "
                                       f"с \"bounds\": true; связь выглядит рабочей, а сверять не с чем")
            else:
                # Один уровень: lineup страницы модельного ряда не подтягивается — модельный ряд конечная точка.
                for u, v in own[q]["units"].items():
                    t = units.setdefault(u, dict(v, vals={}))
                    for val, model in v["vals"].items():
                        t["vals"].setdefault(val, model)
                res["rows"] += own[q]["rows"]
                res["pages"].append(q)
        out[slug] = res
    return out


# «N конфигураций» против числа строк. Слова — в README, список можно дополнять.
# «исполнение» сюда не входит намеренно: у «Хранителя» три исполнения — это корпуса,
# а не строки модельного ряда. «модуль» — тоже: у модулей своя таблица.
COUNT_NOUNS = {
    "конфигурация": "конфигурация конфигурации конфигурацию конфигурацией конфигураций конфигурациям конфигурациями конфигурациях",
    "модель": "модель модели моделью моделей моделям моделями моделях",
    "позиция": "позиция позиции позицию позицией позиций позициям позициями позициях",
}
_UNITS = {2: "два две двух двум двумя", 3: "три трех трем тремя", 4: "четыре четырех четырем четырьмя",
          5: "пять пяти пятью", 6: "шесть шести шестью", 7: "семь семи семью", 8: "восемь восьми восемью восьмью",
          9: "девять девяти девятью"}
_ONE = "один одна одно одного одной одному одним одну"   # только в составных: «двадцать одна»
_TEENS = {10: "десять", 11: "одиннадцать", 12: "двенадцать", 13: "тринадцать", 14: "четырнадцать",
          15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать", 19: "девятнадцать"}
_TENS = {20: "двадцать двадцати двадцатью", 30: "тридцать тридцати тридцатью", 40: "сорок сорока",
         50: "пятьдесят пятидесяти пятьюдесятью", 60: "шестьдесят шестидесяти шестьюдесятью",
         70: "семьдесят семидесяти семьюдесятью", 80: "восемьдесят восьмидесяти восемьюдесятью",
         90: "девяносто девяноста"}


def _number_words():
    """Числительные от 2 до 100 словами, с падежами: «шестнадцать», «из шестнадцати»,
    «двадцать две», «двадцати двух». «один / одна» сами по себе — оборот речи, не счёт."""
    w = {}
    for n, forms in _UNITS.items():
        for f in forms.split():
            w[f] = n
    for n, f in _TEENS.items():
        w[f] = n
        w[f[:-1] + "и"] = n      # шестнадцать → шестнадцати
        w[f + "ю"] = n           # шестнадцатью
    for n, forms in _TENS.items():
        for f in forms.split():
            w[f] = n
            for un, uforms in list(_UNITS.items()) + [(1, _ONE)]:
                for uf in uforms.split():
                    w[f"{f} {uf}"] = n + un
    w["сто"] = w["ста"] = 100
    return w


NUMBER_WORDS = _number_words()
_NW = "|".join(sorted((re.escape(k).replace(r"\ ", r"\s+") for k in NUMBER_WORDS), key=len, reverse=True))
_NOUN = "|".join(sorted({f for v in COUNT_NOUNS.values() for f in v.split()}, key=len, reverse=True))
_ADJ = r"[а-я]+(?:ые|ых|ая|ое|ий|ый|ой|ую|ыми|ими|ого|его|ому|ему|ей)"
COUNT_RE = re.compile(rf"(?<![\wа-я])(?P<n>\d+|{_NW})\s+(?:{_ADJ}\s+){{0,2}}(?P<noun>{_NOUN})(?![\wа-я])")


def count_problems(text, rows):
    """«16 конфигураций», «двадцать две серийные модели» — число обязано равняться строкам ряда."""
    out = []
    low = text.lower().replace("ё", "е")   # та же длина, позиции совпадают с исходным текстом
    for m in COUNT_RE.finditer(low):
        raw_n = m.group("n")
        n = int(raw_n) if raw_n.isdigit() else NUMBER_WORDS.get(re.sub(r"\s+", " ", raw_n))
        if n is None or n < 2:
            continue
        if n != rows:
            out.append((text[m.start():m.end()], f"в тексте {n}, а строк в модельном ряду {rows}", None))
    return out


# Слово перед одиночным числом, которое делает его заявлением о крае линейки.
# «не более N» и «не менее N» сюда НЕ входят: это обещание на каждое изделие
# («ресурс не менее 3000 циклов» — ни одна батарея не хуже), а не край ряда.
CLAIM_UPPER_RE = re.compile(r"(?:^|[^\wА-Яа-яЁё])(?:до|свыше|более)\s+$", re.I)
CLAIM_LOWER_RE = re.compile(r"(?:^|[^\wА-Яа-яЁё])от\s+$", re.I)
NOT_CLAIM_RE = re.compile(r"(?:^|[^\wА-Яа-яЁё])не\s+(?:более|менее)\s+$", re.I)
BOUNDS_SKIP = {"src", "key", "align", "bounds_ignore"}


def bound_problems(text, bounds):
    """Расхождения чисел в тексте с границами таблицы → [(фрагмент, что не так, единица)]."""
    out, taken = [], []
    for rx in (RANGE_FROM_RE, RANGE_DASH_RE):
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            u = norm_unit(m.group("uy"))
            if m.group("ux") and norm_unit(m.group("ux")) != u:
                continue  # «от 5 кВт до 10 кВт·ч» — не диапазон одной величины
            taken.append(m.span())
            if u not in bounds:
                continue
            vals = bounds[u]["vals"]
            lo, hi = min(vals), max(vals)
            x, y = num(m.group("x")), num(m.group("y"))
            bad = []
            if x != lo:
                bad.append(f"нижняя граница {fmt(x)}, а минимум таблицы {fmt(lo)} ({vals[lo]})")
            if y != hi:
                bad.append(f"верхняя граница {fmt(y)}, а максимум таблицы {fmt(hi)} ({vals[hi]})")
            if bad:
                out.append((m.group(0).strip(), "; ".join(bad), u))
    for m in SINGLE_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue
        u = norm_unit(m.group("u"))
        if u not in bounds:
            continue
        vals, n, before = bounds[u]["vals"], num(m.group("n")), text[:m.start()]
        lo, hi = min(vals), max(vals)
        phrase = m.group(0).strip()
        if NOT_CLAIM_RE.search(before):
            claim = None
        elif m.group("nplus") or CLAIM_UPPER_RE.search(before):
            claim = "upper"
        elif CLAIM_LOWER_RE.search(before):
            claim = "lower"
        else:
            claim = None
        if claim:
            word = re.search(r"(до|свыше|более|от)\s+$", before, re.I)
            phrase = (word.group(1) + " " if word else "") + phrase
        if claim == "upper" and n != hi:
            out.append((phrase, f"заявлена верхняя граница {fmt(n)}, а максимум таблицы {fmt(hi)} ({vals[hi]})", u))
        elif claim == "lower" and n != lo:
            out.append((phrase, f"заявлена нижняя граница {fmt(n)}, а минимум таблицы {fmt(lo)} ({vals[lo]})", u))
        elif claim is None and n not in vals:
            out.append((phrase, "такого значения в таблице нет", u))
    return out


def link_target(d, here):
    """Страница, к которой объект относится по своей ссылке: href, link.href, button.href.
    Ссылка на свою же страницу (или якорь на ней) текст никуда не переносит."""
    for h in (d.get("href"), (d.get("link") or {}).get("href") if isinstance(d.get("link"), dict) else None,
              (d.get("button") or {}).get("href") if isinstance(d.get("button"), dict) else None):
        if isinstance(h, str) and h and not is_external(h):
            page = h.partition("#")[0]
            if page.endswith(".html") and page.removesuffix(".html") != here:
                return page.removesuffix(".html")
    return None


def bound_texts(obj, here, path="", owner=None, ignore=None, rep=None, group=None, page=None):
    """Тексты для сверки: (путь, значение, чья страница, исключение bounds_ignore или None).
    Объект со ссылкой на другую страницу отдаёт свой текст ей — и всё внутри него."""
    if isinstance(obj, dict):
        target = link_target(obj, here)
        if target:
            owner = target
        if "bounds_ignore" in obj:
            if obj["bounds_ignore"] is True:
                ignore = path or "страница"
            else:
                rep.add(group, "диапазон", f"{readable_path(page, path) if page else path}: bounds_ignore = "
                                           f"{obj['bounds_ignore']!r} — бывает только true")
        for k, v in obj.items():
            if k in NOT_TEXT or k in BOUNDS_SKIP:
                continue
            yield from bound_texts(v, here, f"{path}.{k}" if path else k, owner, ignore, rep, group, page)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from bound_texts(v, here, f"{path}[{i}]", owner, ignore, rep, group, page)
    elif isinstance(obj, str):
        if TABLE_CELL_RE.match(path) or re.search(r"(?:^|\.)columns\[\d+\]\.", path):
            return
        yield path, obj, owner, ignore


def check_bounds_in(data, here, group, lineups, rep, page=None):
    """Правила границ и счёта для одного файла данных: страницы (here = её slug) или site.json (here = None)."""
    used, ignores = set(), set()
    for path, value, owner, ignore in bound_texts(data, here, owner=here, rep=rep, group=group, page=page):
        if ignore:
            ignores.add(ignore)
        lu = lineups.get(owner)
        if not lu or not (lu["units"] or lu["rows"]):
            continue  # у страницы, к которой относится текст, нет модельного ряда — сверять не с чем
        text = plain(value)
        problems = bound_problems(text, lu["units"]) + (count_problems(text, lu["rows"]) if lu["rows"] else [])
        if problems and ignore:
            used.add(ignore)
            continue
        where = readable_path(page, path) if page else path
        src = " таблице" if lu["pages"] == [here] else \
              " таблице страницы " + ", ".join(f"{p}.html" for p in lu["pages"])
        for phrase, msg, u in problems:
            if u is None:
                line = f"{where}: «{phrase}» — {msg}"
                if lu["pages"] != [here]:
                    line += f"\n        модельный ряд: {', '.join(p + '.html' for p in lu['pages'])}"
            else:
                bounds = lu["units"]
                vals = bounds[u]["vals"]
                line = f"{where}: «{phrase}» — {msg}\n        по{src}: от {fmt(min(vals))} до {fmt(max(vals))} {bounds[u]['unit']}"
                if msg.startswith("такого"):
                    line += f", значения: {', '.join(fmt(v) for v in sorted(vals))}"
                else:
                    line += f" (колонка «{bounds[u]['col']}», {len(vals)} {plural(len(vals), 'значение', 'значения', 'значений')})"
            line += "\n        если фраза не про модельный ряд — \"bounds_ignore\": true у этого элемента"
            rep.add(group, "диапазон", line)
    # Исключение, которое ничего не глушит, — мусор, который однажды прикроет настоящую ошибку.
    for ig in sorted(ignores - used):
        where = readable_path(page, ig) if page and ig != "страница" else ig
        rep.add(group, "диапазон", f"{where}: bounds_ignore ничего не глушит — без него здесь и так чисто; "
                                   f"уберите, чтобы оно не прикрыло настоящую ошибку потом")


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
    # Границы: сначала таблицы всех страниц, потом тексты — текст со ссылкой
    # на другую страницу сверяется с её таблицей.
    lineups = page_lineups(data, broken, rep)
    for slug, page in data.items():
        if isinstance(page, dict):
            check_bounds_in(page, slug, page_group(slug), lineups, rep, page)
    if site is not None:
        check_bounds_in(site, None, SITE_GROUP, lineups, rep)
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
