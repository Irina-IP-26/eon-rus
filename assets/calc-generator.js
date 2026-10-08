/* Калькулятор «генератор или накопитель».

   Считает не цену покупки, а цену киловатт-часа за весь срок службы.
   Вся арифметика открыта и показана на странице: читатель должен иметь
   возможность проверить нас, а не поверить.

   Источник исходных чисел — расчёт НПК Еон по генератору 5 кВт
   и системе «Хранитель»; разбор в _sources/калькуляторы.md.
*/
(function () {
  "use strict";
  var root = document.getElementById("calcgen");
  if (!root) return;

  function num(id) {
    var el = document.getElementById(id);
    if (!el) return 0;
    var v = parseFloat(String(el.value).replace(",", "."));
    return isFinite(v) ? v : 0;
  }

  function money(x) {
    return Math.round(x).toLocaleString("ru-RU") + " ₽";
  }

  function rub(x) {
    // цена киловатт-часа: до целых рублей выше сотни, иначе с десятыми
    var s = x >= 100 ? Math.round(x).toLocaleString("ru-RU")
                     : (Math.round(x * 10) / 10).toString().replace(".", ",");
    return s + " ₽";
  }

  function put(id, text, cls) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (cls !== undefined) el.className = cls;
  }

  function calc() {
    var kw = num("cg-power");          // мощность нагрузки, кВт
    var hours = num("cg-hours");       // часов работы в сутки
    var fuel = num("cg-fuel");         // цена топлива, ₽/л
    var grid = num("cg-grid");         // цена сетевой энергии, ₽/кВт·ч
    var load = num("cg-load") / 100;   // средняя загрузка генератора, доля
    var daysYear = num("cg-days");     // сколько дней в году так работаем

    var bad = [];
    if (kw <= 0) bad.push("мощность");
    if (hours <= 0 || hours > 24) bad.push("часы");
    if (fuel <= 0) bad.push("цена топлива");
    if (load <= 0 || load > 1) bad.push("загрузка");
    if (daysYear <= 0 || daysYear > 365) bad.push("дни в году");
    if (bad.length) {
      put("cg-note", "Проверьте: " + bad.join(", ") + ".", "cg-note bad");
      return;
    }

    // Генератор. Расход привязан к его номиналу, а не к вашей нагрузке:
    // в этом вся суть. Берём номинал как мощность нагрузки, делённую
    // на загрузку, и округляем вверх до ближайшего киловатта.
    var rated = Math.max(kw, Math.ceil(kw / load));
    var litPerHour = 0.64 * rated;          // 0,64 л на киловатт номинала в час
    var genBuy = GEN_BUY;
    var genLifeHours = GEN_LIFE_HOURS;

    var genUseful = kw * hours;             // полезных киловатт-часов в сутки
    var genFuelDay = litPerHour * hours * fuel;
    var genDays = genLifeHours / hours;     // на сколько суток хватит ресурса
    var genAmort = genBuy / (genUseful * genDays);
    var genFuelPerKwh = genFuelDay / genUseful;
    var genTotal = genFuelPerKwh + genAmort;

    // Накопитель. Заряжается из сети, срок считаем в циклах.
    var stoBuy = STO_BUY;
    var stoCap = STO_CAP;                   // энергоёмкость, кВт·ч
    var stoCycles = STO_CYCLES;
    var stoThrough = stoCap * stoCycles * 0.95; // с поправкой на потери
    var stoAmort = stoBuy / stoThrough;
    var stoTotal = stoAmort + grid;

    put("cg-gen", rub(genTotal));
    put("cg-sto", rub(stoTotal));
    put("cg-ratio", (Math.round((genTotal / stoTotal) * 10) / 10)
        .toString().replace(".", ",") + " ×");

    // Окупаемость считается в годах, а не в «днях работы»: день работы
    // бывает не каждый день. Без этого числа расчёт выглядит красивее,
    // чем есть, — для дома с парой отключений в год он честно показывает,
    // что накопитель берут не ради экономии.
    var saveDay = (genTotal - stoTotal) * genUseful;
    var saveYear = saveDay * daysYear;
    var diff = stoBuy - genBuy;
    var paybackText;
    if (diff <= 0) {
      paybackText = "Накопитель дешевле с первого дня: он и стоит меньше, "
        + "и киловатт-час у него дешевле.";
    } else if (saveYear <= 0) {
      paybackText = "При таком режиме накопитель не выгоднее генератора "
        + "по деньгам — считайте по другим доводам: тишина, отсутствие "
        + "выхлопа и то, что он включается сам.";
    } else {
      var years = diff / saveYear;
      if (years > 10) {
        paybackText = "Разница в цене окупалась бы дольше срока службы: "
          + "при " + Math.round(daysYear) + " "
          + plural(Math.round(daysYear), "дне", "днях", "днях")
          + " работы в году генератор просто не успевает сжечь столько "
          + "топлива. Накопитель здесь берут не ради экономии, а ради того, "
          + "что он включается сам, не шумит и не травит выхлопом.";
      } else {
        paybackText = "Разница в цене окупается примерно за "
          + (Math.round(years * 10) / 10).toString().replace(".", ",") + " "
          + plural(Math.round(years), "год", "года", "лет")
          + ": это " + money(saveYear) + " экономии в год. "
          + "Дальше накопитель работает в плюс.";
      }
    }
    put("cg-note", paybackText, "cg-note");
    put("cg-detail",
      "Генератор: нужен номинал " + rated + " кВт, расход "
      + (Math.round(litPerHour * 10) / 10).toString().replace(".", ",")
      + " л/ч, топлива на " + money(genFuelDay) + " в сутки. "
      + "Полезно при этом " + Math.round(genUseful) + " кВт·ч.");
  }

  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  var GEN_BUY = +root.dataset.genBuy || 268400;
  var GEN_LIFE_HOURS = +root.dataset.genLife || 2000;
  var STO_BUY = +root.dataset.stoBuy || 356000;
  var STO_CAP = +root.dataset.stoCap || 5;
  var STO_CYCLES = +root.dataset.stoCycles || 3000;

  root.addEventListener("input", calc);
  calc();
})();
