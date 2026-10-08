#!/usr/bin/env python3
"""
Сборщик сайта еон.рус.

Содержание страниц лежит в content/*.json, вёрстка — здесь.
Сборка кладёт готовую статику в dist/.

Запуск:  python3 build.py
"""
import json, html, pathlib, re, shutil, sys

ROOT = pathlib.Path(__file__).parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

# ─────────────────────────────── утилиты ───────────────────────────────

def e(s):
    """Экранирование текста. Данные из content/ — это текст, не разметка."""
    return html.escape(str(s), quote=True)

def raw(s):
    """Поля, которым разрешена разметка: только &nbsp;, <br> и <em>."""
    return str(s)

def attr(d, k, default=""):
    return e(d.get(k, default))

def cls(*parts):
    return " ".join(p for p in parts if p)


# ─────────────────────────────── блоки ───────────────────────────────
# Каждый блок — словарь с полем "type". Ниже рендер каждого типа.
# Новый тип блока добавляется сюда и становится доступен всем страницам.

def b_hero(b):
    cta = "".join(
        f'<a class="pill{" ghost" if c.get("ghost") else ""}" href="{attr(c,"href")}">{e(c["label"])}</a>'
        for c in b.get("cta", [])
    )
    plate = _shot(b.get("image")) + (_plate(b["plate"]) if b.get("plate") else "")
    plate = f'<div>{plate}</div>' if plate else ""
    i = f' id="{attr(b, "id")}"' if b.get("id") else ""
    return f"""<section class="hero"{i}>
  <div class="wrap hero-grid">
    <div>
      <div class="eyebrow">{e(b["eyebrow"])}</div>
      <h1>{raw(b["h1"])}{f' <span class="q">{raw(b["h1q"])}</span>' if b.get("h1q") else ''}</h1>
      <p class="lede">{raw(b["lede"])}</p>
      <div class="cta">{cta}</div>
    </div>
    {plate}
  </div>
</section>"""


def b_figs(b):
    n = len(b["items"])
    items = "".join(
        f'<div class="fig"><b>{e(i["value"])}</b><small>{e(i["label"])}</small></div>'
        for i in b["items"]
    )
    extra = " f3" if n == 3 else ""
    return f"""<section{_pad(b)}>
  <div class="wrap">{_head(b)}<div class="figs{extra}">{items}</div></div>
</section>"""


def b_cards(b):
    g = {2: "g2", 3: "g3", 4: "g4"}.get(b.get("cols", len(b["items"])), "g3")
    out = []
    for c in b["items"]:
        parts = []
        if c.get("chip"):
            parts.append(f'<span class="chip{" calc" if c.get("chip_accent") else ""}">{e(c["chip"])}</span>')
        if c.get("image"):
            parts.append(_shot(c["image"]))
        parts.append(f'<h3>{e(c["title"])}</h3><div class="rule"></div>')
        if c.get("text"):
            parts.append(f'<p>{raw(c["text"])}</p>')
        if c.get("spec"):
            parts.append(f'<div class="spec">{raw(c["spec"])}</div>')
        if c.get("link"):
            parts.append(f'<a class="more" href="{attr(c["link"],"href")}">{e(c["link"]["label"])} <span>&rarr;</span></a>')
        out.append(f'<div class="{cls("card", c.get("fill") and "fill-" + c["fill"])}">{"".join(parts)}</div>')
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<div class="grid {g}">{"".join(out)}</div></div></section>'


def b_points(b):
    items = "".join(f'<li><b>{e(i["term"])}</b><span>{raw(i["text"])}</span></li>' for i in b["items"])
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<ul class="points">{items}</ul></div></section>'


def b_steps(b):
    items = "".join(
        f'<div class="step"><div class="n">{i+1:02d}</div><h3>{e(s["title"])}</h3><p>{raw(s["text"])}</p></div>'
        for i, s in enumerate(b["items"])
    )
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<div class="steps">{items}</div></div></section>'


def b_cases(b):
    items = "".join(
        f'<div class="case">{_shot(c.get("image"))}<div class="meta">{e(c["meta"])}</div>'
        f'<h3>{e(c["title"])}</h3><p>{raw(c["text"])}</p></div>'
        for c in b["items"]
    )
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<div class="grid g3">{items}</div></div></section>'


def b_plates(b):
    body = "".join(_plate(p) if p.get("rows") is not None else _plate_card(p) for p in b["items"])
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<div class="grid g2">{body}</div></div></section>'


def b_faq(b):
    items = "".join(
        f'<details><summary>{e(q["q"])}</summary><p>{raw(q["a"])}</p></details>'
        for q in b["items"]
    )
    return f'<section{_pad(b)}><div class="wrap">{_head(b)}<div class="faq">{items}</div></div></section>'


def b_circuit(b):
    sym = {
        "saw": '<svg width="74" height="16" viewBox="0 0 74 16"><path d="M0 8h16l4-6 8 12 8-12 8 12 4-6h26" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
        "cap": '<svg width="34" height="16" viewBox="0 0 34 16"><path d="M0 8h14M20 8h14" stroke="currentColor" stroke-width="1" fill="none"/><path d="M14 1v14M20 1v14" stroke="currentColor" stroke-width="1"/></svg>',
        "dot": '<svg width="24" height="16" viewBox="0 0 24 16"><path d="M0 8h7M17 8h7" stroke="currentColor" stroke-width="1"/><circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
    }
    parts = ["<i></i>"]
    for k in b.get("symbols", ["saw", "cap", "dot"]):
        parts.append(sym[k])
        parts.append("<i></i>")
    return f'<div class="wrap"><div class="circuit" aria-hidden="true">{"".join(parts)}</div></div>'


def b_form(b):
    b = dict(b); b.setdefault("id", "form")
    return f"""<section{_pad(b, attr_only=True)}>
  <div class="wrap">{_head(b)}
    <form class="form" id="calc" novalidate>
      <div><label for="f-name">Имя</label><input id="f-name" name="name" autocomplete="name" placeholder="Как к вам обращаться"></div>
      <div><label for="f-tel">Телефон</label><input id="f-tel" name="tel" inputmode="tel" autocomplete="tel" placeholder="+7"></div>
      <div class="full"><label for="f-mail">Электронная почта</label><input id="f-mail" name="email" type="email" autocomplete="email" placeholder="для спецификации"></div>
      <div class="full"><label for="f-task">Задача</label><textarea id="f-task" name="task" placeholder="{attr(b,'placeholder')}"></textarea></div>
      <div class="full agree"><input id="f-ok" name="agree" type="checkbox"><label for="f-ok">Согласен на обработку персональных данных</label></div>
      <div class="full" style="display:flex; gap:16px; align-items:center; flex-wrap:wrap">
        <button class="pill" type="submit">Отправить заявку</button>
        <span class="sent" id="sent" hidden>Это макет — заявка никуда не ушла.</span>
      </div>
    </form>
  </div>
</section>"""


def b_table(b):
    """Каталожная таблица: колонки из columns, строки — в groups[].rows или прямо в rows.

    Настоящий <table>, чтобы таблица оставалась таблицей для экранных читалок:
    первая колонка — заголовок строки, заголовок группы — строка <th> в начале
    своего <tbody>. Узкий экран прокручивает таблицу внутри .tbl, а не страницу.
    """
    cols = b["columns"]

    def c(col):
        k = cls("r" if col.get("align") == "right" else "", "m" if col.get("mono") else "")
        return f' class="{k}"' if k else ""

    def cell(row, n, col):
        v = row.get(col["key"])
        v = "" if v is None else v
        if n == 0:
            return f'<th scope="row"{c(col)}>{e(v)}</th>'
        return f'<td{c(col)}>{e(v)}</td>'

    head = "".join(f'<th scope="col"{c(col)}>{e(col["label"])}</th>' for col in cols)
    groups = b["groups"] if b.get("groups") else [{"rows": b["rows"]}]
    body = []
    for g in groups:
        title = (f'<tr class="tbl-group"><th colspan="{len(cols)}" scope="rowgroup">{e(g["title"])}</th></tr>'
                 if g.get("title") else "")
        rows = "".join(f'<tr>{"".join(cell(r, n, col) for n, col in enumerate(cols))}</tr>' for r in g["rows"])
        body.append(f"<tbody>{title}{rows}</tbody>")
    # Подпись области прокрутки для читалок: заголовок раздела без разметки.
    label = " ".join(str(b.get(k, "")) for k in ("h2", "h2q")).strip() or b.get("eyebrow") or "Таблица"
    label = e(" ".join(html.unescape(re.sub(r"<[^>]*>", " ", label)).split()))
    return (f'<section{_pad(b)}><div class="wrap">{_head(b)}'
            f'<div class="tbl" role="region" aria-label="{label}" tabindex="0">'
            f'<table><thead><tr>{head}</tr></thead>{"".join(body)}</table></div></div></section>')


BLOCKS = {
    "hero": b_hero, "figs": b_figs, "cards": b_cards, "points": b_points,
    "steps": b_steps, "cases": b_cases, "plates": b_plates, "faq": b_faq,
    "circuit": b_circuit, "form": b_form, "table": b_table,
}

# ───────────────────────── вспомогательная вёрстка ─────────────────────────

def _pad(b, attr_only=False):
    """Атрибуты раздела: якорь, тёмная подложка, снятый верхний отступ."""
    i = f' id="{attr(b, "id")}"' if b.get("id") else ""
    s = ' style="padding-top:0"' if b.get("tight") else ""
    if b.get("dark") and not attr_only:
        return f'{i} class="dark"{s}'
    return f'{i}{s}'


def _head(b):
    if not b.get("eyebrow") and not b.get("h2"):
        return ""
    if not b.get("h2"):
        return f'<div class="eyebrow">{e(b["eyebrow"])}</div>' if b.get("eyebrow") else ""
    q = f' <span class="q">{raw(b["h2q"])}</span>' if b.get("h2q") else ""
    lede = f'<p class="lede">{raw(b["lede"])}</p>' if b.get("lede") else ""
    eb = f'<div class="eyebrow">{e(b["eyebrow"])}</div>' if b.get("eyebrow") else "<div></div>"
    return f'<div class="head">{eb}<div><h2>{raw(b["h2"])}{q}</h2>{lede}</div></div>'


def _shot(img):
    """Изображение или подписанное пустое место под него.

    Поля: src (путь к файлу), alt (альтернативный текст), caption (подпись),
    need (что именно должно быть на снимке — показывается, пока файла нет).
    """
    if not img:
        return ""
    if img.get("src"):
        inner = f'<img src="{attr(img, "src")}" alt="{attr(img, "alt")}" loading="lazy">'
        box = f'<div class="shot">{inner}</div>'
    else:
        need = e(img.get("need", "место под изображение"))
        box = f'<div class="shot empty"><span><b>фото</b>{need}</span></div>'
    if img.get("caption"):
        return f'<figure class="shot-wrap">{box}<figcaption>{e(img["caption"])}</figcaption></figure>'
    return box


def _plate(p):
    rows = "".join(
        f'<div class="row"><span class="k">{e(r["k"])}</span><span class="dots"></span>'
        f'<span class="v{" good" if r.get("good") else ""}">{raw(r["v"])}</span></div>'
        for r in p["rows"]
    )
    btn = ""
    if p.get("button"):
        btn = (f'<div style="margin-top:16px"><a class="pill ghost" href="{attr(p["button"],"href")}">'
               f'{e(p["button"]["label"])}</a></div>')
    return f'<div class="plate"><div class="plate-head">{e(p["head"])}</div>{rows}{btn}</div>'


def _plate_card(p):
    btns = "".join(
        f'<a class="pill{" ghost" if c.get("ghost") else ""}" href="{attr(c,"href")}">{e(c["label"])}</a>'
        for c in p.get("cta", [])
    )
    wrap = f'<div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:6px">{btns}</div>' if btns else ""
    return (f'<div class="card" style="justify-content:center"><h3>{e(p["title"])}</h3>'
            f'<div class="rule"></div><p>{raw(p["text"])}</p>{wrap}</div>')


# ─────────────────────────── шапка, подвал, каркас ───────────────────────────

def logo(site):
    paths = "".join(f'<path d="{d}"/>' if d.startswith("M") else f'<polygon points="{d}"/>'
                    for d in site["logo"])
    return f'<svg class="logo" viewBox="{site["logo_viewbox"]}" role="img" aria-label="ЕОН">{paths}</svg>'


def header(site, current):
    nav = []
    for item in site["nav"]:
        if item.get("children"):
            subs = []
            for c in item["children"]:
                sub = f'<span class="sub">{e(c["sub"])}</span>' if c.get("sub") else ""
                subs.append(f'<li><a href="{attr(c, "href")}">{e(c["label"])}{sub}</a></li>')
            nav.append(
                f'<li class="drop"><button type="button" aria-haspopup="true">{e(item["label"])}</button>'
                f'<ul>{"".join(subs)}</ul></li>'
            )
        else:
            cur = ' aria-current="page"' if item.get("href") == current else ""
            nav.append(f'<li><a href="{attr(item, "href")}"{cur}>{e(item["label"])}</a></li>')
    return f"""<header class="top">
  <div class="top-in">
    <div class="top-row">
      <a class="brand" href="index.html" aria-label="ЕОН, на главную">{logo(site)}</a>
      <span class="brand-tag">{e(site["tagline"])}</span>
      <span class="top-sp"></span>
      <div class="top-c">
        <a href="mailto:{e(site["email"])}">{e(site["email"])}</a>
        <a href="tel:{e(site["phone_tel"])}">{e(site["phone"])}</a>
      </div>
      <a class="pill" href="{e(site.get("form_href", "#form"))}">{e(site["cta"])}</a>
    </div>
    <ul class="nav" aria-label="Основная навигация">{"".join(nav)}</ul>
  </div>
</header>"""


def footer(site):
    cols = []
    for col in site["footer"]:
        items = []
        for i in col["items"]:
            if i.get("href"):
                items.append(f'<li><a href="{attr(i, "href")}">{e(i["label"])}</a></li>')
            elif i.get("muted"):
                items.append(f'<li style="color:#7D8795">{e(i["label"])}</li>')
            else:
                items.append(f'<li>{e(i["label"])}</li>')
        extra = ""
        if col.get("head2"):
            sub = "".join(
                f'<li><a href="{attr(i, "href")}">{e(i["label"])}</a></li>' for i in col["items2"]
            )
            extra = f'<h2 style="margin-top:20px">{e(col["head2"])}</h2><ul>{sub}</ul>'
        cols.append(f'<div><h2>{e(col["head"])}</h2><ul>{"".join(items)}</ul>{extra}</div>')
    return f"""<footer>
  <div class="wrap">
    <div class="f-top">
      <div>
        <a class="brand" href="index.html" aria-label="ЕОН">{logo(site)}</a>
        <p class="f-about">{e(site["about"])}</p>
      </div>
      {"".join(cols)}
    </div>
    <div class="f-bot"><span>{e(site["legal"])}</span><span>{e(site["stamp"])}</span></div>
  </div>
</footer>"""


SCRIPT = """<script>
var f = document.getElementById('calc');
if (f) f.addEventListener('submit', function(e){ e.preventDefault(); document.getElementById('sent').hidden = false; });
</script>"""

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<meta name="description" content="{descr}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="draft">{draft}</div>
{header}
{body}
{footer}
{script}
</body>
</html>
"""

# ─────────────────────────────── сборка ───────────────────────────────

def render(page, site):
    body = []
    for b in page["blocks"]:
        fn = BLOCKS.get(b["type"])
        if fn is None:
            raise SystemExit(f'{page["slug"]}: неизвестный тип блока "{b["type"]}"')
        body.append(fn(b))
    return PAGE.format(
        title=e(page["title"]), descr=e(page.get("description", "")),
        draft=site["draft"], header=header(site, page["slug"] + ".html"),
        body="\n".join(body), footer=footer(site), script=SCRIPT,
    )


def main():
    site = json.loads((CONTENT / "site.json").read_text(encoding="utf-8"))
    DIST.mkdir(exist_ok=True)
    for f in ASSETS.iterdir():
        shutil.copy2(f, DIST / f.name)
    built = []
    for src in sorted(CONTENT.glob("*.json")):
        if src.name == "site.json":
            continue
        page = json.loads(src.read_text(encoding="utf-8"))
        page.setdefault("slug", src.stem)
        out = DIST / (page["slug"] + ".html")
        out.write_text(render(page, site), encoding="utf-8")
        built.append(f'{out.name} — {len(out.read_text(encoding="utf-8")):,} байт')
    (DIST / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    # Домен публикации. Без этого файла GitHub Pages сбрасывает
    # настройку custom domain при каждой публикации.
    (DIST / "CNAME").write_text(site["domain"] + "\n", encoding="utf-8")
    print("Собрано:")
    for b in built:
        print("  " + b)


if __name__ == "__main__":
    main()
