/* Кнопка «показать ещё» под карточками внедрений.
   Карточки уже в разметке и помечены атрибутом hidden; кнопка снимает
   его с очередной дюжины. Перезагрузки и запросов к серверу нет. */
document.querySelectorAll('[data-more]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var grid = document.getElementById(btn.dataset.more);
    if (!grid) return;
    var step = parseInt(grid.dataset.step, 10) || 12;
    var скрытые = Array.prototype.filter.call(grid.children, function (el) {
      return el.hasAttribute('hidden');
    });
    скрытые.slice(0, step).forEach(function (el) { el.removeAttribute('hidden'); });
    var осталось = скрытые.length - step;
    if (осталось <= 0) {
      var wrap = btn.closest('.more-wrap');
      if (wrap) wrap.remove();
      return;
    }
    btn.innerHTML = 'Показать ещё ' + Math.min(step, осталось) +
                    ' <span class="more-left">из ' + осталось + '</span>';
  });
});
