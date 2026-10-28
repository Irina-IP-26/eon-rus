#!/usr/bin/env python3
"""Карточки проектов из сводной таблицы.

Зачем: владелец собирает объекты в Google-таблице «Наши проекты — сводная».
Объектов будет под сотню, и вписывать каждый в JSON руками — работа, которую
никто не будет делать. Этот скрипт берёт выгрузку таблицы и дописывает карточки
на страницы раздела.

Что он НЕ делает: не трогает карточки, которые уже стоят на странице. Написанный
человеком текст лучше собранного из граф, и затирать его нельзя. Скрипт добавляет
только те объекты, которых на странице ещё нет — совпадение ищет по заголовку
карточки.

Порядок работы:
    1) выгрузить лист «Проекты» в _sources/проекты.json (список строк-списков)
    2) python3 make_projects.py
    3) python3 build.py && python3 check.py
"""
import json, pathlib, sys

SRC = pathlib.Path("_sources/проекты.json")
CONTENT = pathlib.Path("content")

# линейка в таблице → страница раздела
PAGE = {
    "Тяговые АКБ":  "projects-forklift",
    "Скиф":         "projects-skif",
    "Хранитель":    "projects-guardian",
    "Энергопоток":  "projects-energyflow",
}
# графы таблицы по порядку (A..Y)
COL = {name: i for i, name in enumerate(
    "№ Линейка Заголовок Клиент Покупатель Публиковать Место Регион Год Месяц "
    "Модели Колво Напряжение Ёмкость Запас Техника ЗУ Грузокомпенсатор Модификации "
    "Задача Результат Фото Статус Источник Примечание".split())}

MONTH = {"1":"январь","2":"февраль","3":"март","4":"апрель","5":"май","6":"июнь",
         "7":"июль","8":"август","9":"сентябрь","10":"октябрь","11":"ноябрь","12":"декабрь"}


def cell(row, name):
    i = COL[name]
    v = row[i] if i < len(row) else ""
    return str(v).strip() if v not in (None, "") else ""


def publishable(row):
    """Строка идёт на сайт, если это не отказ и есть чем заполнить карточку."""
    if cell(row, "Публиковать").lower().startswith("нет"):
        return False
    if cell(row, "Статус") in ("дубль", "свод — не считать", "учтено в строке 13", "количество 0 в файле"):
        return False
    if not cell(row, "Клиент"):
        return False
    # Главное условие: про объект должно быть написано, какая была задача
    # или что система дала. Без этого карточка вырождается в «описание
    # уточняется», и страница из списка работ превращается в список строк
    # реестра. Пусть лучше объект подождёт одну фразу от отдела продаж.
    return bool(cell(row, "Задача") or cell(row, "Результат"))


def meta(row):
    """Строка над заголовком: когда · где · сколько."""
    parts = []
    y, m = cell(row, "Год"), cell(row, "Месяц")
    if y:
        parts.append(f"{MONTH[m]} {y}" if m in MONTH and "–" not in y else y)
    elif cell(row, "Статус").startswith("отгрузка"):
        parts.append("отгрузка запланирована")
    if cell(row, "Место"):
        parts.append(cell(row, "Место"))
    n = cell(row, "Колво")
    if n and n != "1":
        parts.append(f"{n} шт")
    if cell(row, "Запас"):
        parts.append(f"{cell(row,'Запас')} кВт·ч")
    return " · ".join(parts)


def text(row):
    """Текст карточки: задача и результат, как их записал отдел продаж."""
    out = [t for t in (cell(row, "Задача"), cell(row, "Результат")) if t]
    if not out:
        tech = cell(row, "Техника")
        out = [f"Объект: {tech}." if tech else "Описание объекта уточняется."]
    return " ".join(out)


def need(row):
    """Подпись под рамкой-заглушкой, пока фотографии нет."""
    what = cell(row, "Техника") or cell(row, "Линейка").lower()
    where = cell(row, "Место")
    return f"{what}{', ' + where if where else ''}"


def main():
    if not SRC.exists():
        sys.exit(f"нет выгрузки {SRC} — сначала выгрузите лист «Проекты»")
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    added = {}
    for line, stem in PAGE.items():
        f = CONTENT / f"{stem}.json"
        if not f.exists():
            continue
        page = json.loads(f.read_text(encoding="utf-8"))
        cases = next((b for b in page["blocks"] if b.get("type") == "cases"), None)
        if cases is None:
            continue
        have = {str(i.get("title", "")).strip().lower() for i in cases["items"]}
        new = []
        for row in rows:
            if cell(row, "Линейка") != line or not publishable(row):
                continue
            title = cell(row, "Заголовок") or cell(row, "Клиент")
            if title.strip().lower() in have:
                continue
            have.add(title.strip().lower())
            new.append({"image": {"need": need(row)}, "meta": meta(row),
                        "title": title, "text": text(row)})
        if new:
            cases["items"] += new
            f.write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            added[stem] = len(new)
    if added:
        for k, v in added.items():
            print(f"  {k}: добавлено карточек — {v}")
    else:
        print("  новых объектов в выгрузке нет, страницы не тронуты")


if __name__ == "__main__":
    main()
