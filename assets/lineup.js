/* Модельный ряд: фильтры, счётчик и сравнение отобранного.

   Фильтры только прячут карточки — вся разметка остаётся на месте,
   поэтому поисковик видит все шестнадцать конфигураций независимо
   от того, что выбрал посетитель. */
(function () {
  var sec = document.querySelector('.lgrid');
  if (!sec) return;
  var корень = sec.closest('section');
  var карточки = Array.prototype.slice.call(sec.querySelectorAll('.lcard'));
  var кнопки = Array.prototype.slice.call(корень.querySelectorAll('.chip-b'));
  var счётчик = корень.querySelector('.lcount');
  var сброс = корень.querySelector('.lf-reset');
  var панель = корень.querySelector('.lcmp-bar');
  var вывод = корень.querySelector('.lcmp-out');
  var выбор = {};

  function подходит(c) {
    for (var k in выбор) {
      if (выбор[k] === 'all') continue;
      var v = c.getAttribute('data-' + k);
      if (v === null) return false;
      if (выбор[k].indexOf('-') > 0) {           // числовой диапазон «8-16»
        var гр = выбор[k].split('-');
        var ч = parseFloat(String(v).replace(',', '.'));
        if (!(ч >= parseFloat(гр[0]) && ч <= parseFloat(гр[1]))) return false;
      } else if (v !== выбор[k]) return false;
    }
    return true;
  }

  function пересчитать() {
    var n = 0;
    карточки.forEach(function (c) {
      var ок = подходит(c);
      c.hidden = !ок;
      if (ок) n++;
    });
    var слово = (n % 10 === 1 && n % 100 !== 11) ? 'конфигурация'
      : ((n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) ? 'конфигурации' : 'конфигураций');
    счётчик.textContent = n ? ('Подходит ' + n + ' ' + слово + ' из ' + карточки.length)
                            : 'Под такие условия готовой конфигурации нет — соберём под объект.';
    var узко = Object.keys(выбор).some(function (k) { return выбор[k] !== 'all'; });
    сброс.hidden = !узко;
  }

  кнопки.forEach(function (b) {
    b.addEventListener('click', function () {
      выбор[b.dataset.key] = b.dataset.val;
      кнопки.forEach(function (x) {
        if (x.dataset.key === b.dataset.key) x.classList.toggle('on', x === b);
      });
      пересчитать();
    });
  });
  сброс.addEventListener('click', function () {
    выбор = {};
    кнопки.forEach(function (x) {
      x.classList.toggle('on', x.dataset.val === 'all');
    });
    пересчитать();
  });

  /* ── сравнение ── */
  function отобранные() {
    return карточки.filter(function (c) { return c.querySelector('input').checked; });
  }
  function обновитьПанель() {
    var n = отобранные().length;
    панель.hidden = n < 2;
    панель.querySelector('.lcmp-n').textContent = 'Выбрано: ' + n;
    if (n < 2) { вывод.hidden = true; вывод.innerHTML = ''; }
  }
  карточки.forEach(function (c) {
    c.querySelector('input').addEventListener('change', function () {
      c.classList.toggle('picked', this.checked);
      обновитьПанель();
    });
  });
  панель.querySelector('[data-cmp-clear]').addEventListener('click', function () {
    карточки.forEach(function (c) {
      c.querySelector('input').checked = false;
      c.classList.remove('picked');
    });
    обновитьПанель();
  });
  панель.querySelector('[data-cmp-show]').addEventListener('click', function () {
    var выбраны = отобранные();
    var графы = Array.prototype.map.call(выбраны[0].querySelectorAll('.ls-r span'),
      function (s) { return s.textContent; });
    var html = '<div class="tbl" role="region" tabindex="0"><table><thead><tr><th>Характеристика</th>';
    выбраны.forEach(function (c) { html += '<th>' + c.querySelector('h3').textContent + '</th>'; });
    html += '</tr></thead><tbody>';
    графы.forEach(function (г, i) {
      html += '<tr><td>' + г + '</td>';
      выбраны.forEach(function (c) {
        var b = c.querySelectorAll('.ls-r b')[i];
        html += '<td>' + (b ? b.innerHTML : '—') + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    вывод.innerHTML = '<h3>Сравнение</h3>' + html;
    вывод.hidden = false;
    вывод.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  пересчитать();
})();
