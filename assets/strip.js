/* Стрелки у полосы документов: листают на ширину видимой части.
   Сама полоса прокручивается и без них — колесом, тачпадом, пальцем. */
document.querySelectorAll('[data-strip]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var row = document.getElementById(btn.dataset.strip);
    if (!row) return;
    row.scrollBy({left: row.clientWidth * 0.8 * Number(btn.dataset.dir), behavior: 'smooth'});
  });
});
