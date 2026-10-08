/* Форма заявки еон.рус — без сторонних библиотек.
 *
 * Адрес приёмника, почта и телефон берутся из атрибутов формы, которые ставит build.py
 * из content/site.json:
 *   <form class="form" data-endpoint="…" data-email="…" data-tel="…" data-tel-label="…">
 * data-endpoint пуст или отсутствует — это макет: форма проверяет поля и честно говорит,
 * что заявка никуда не ушла. Переключение на боевой приём — одна строка в site.json.
 *
 * Состояния: отправляется → отправлено | не отправилось. «Не отправилось» — это и ошибка
 * сервера, и ошибка сети, и молчание дольше TIMEOUT_MS: без подтверждения успеха не бывает.
 * У провала всегда есть запасной путь — почта (с уже заполненным письмом) и телефон.
 */
(function () {
  "use strict";

  var TIMEOUT_MS = 15000;
  var PHONE_MIN_DIGITS = 10;
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function digits(s) { return (s.match(/\d/g) || []).length; }

  function contacts(form) {
    // Из атрибутов формы; если их нет — из ссылок в шапке, чтобы запасной путь был всегда.
    var mail = form.getAttribute("data-email") || "";
    var tel = form.getAttribute("data-tel") || "";
    var telLabel = form.getAttribute("data-tel-label") || "";
    if (!mail) {
      var m = document.querySelector('a[href^="mailto:"]');
      if (m) mail = m.getAttribute("href").replace(/^mailto:/, "").split("?")[0];
    }
    if (!tel) {
      var t = document.querySelector('a[href^="tel:"]');
      if (t) { tel = t.getAttribute("href").replace(/^tel:/, ""); telLabel = telLabel || t.textContent.trim(); }
    }
    return { mail: mail, tel: tel, telLabel: telLabel || tel };
  }

  function field(form, name) { return form.elements.namedItem(name); }

  // ── ошибки у поля ──
  function setError(input, text) {
    var id = input.id + "-err";
    var box = document.getElementById(id);
    if (!box) {
      box = document.createElement("span");
      box.id = id;
      box.className = "field-error";
      // у чекбокса согласия подпись стоит после самого поля — ошибку ставим после подписи
      var anchor = input.type === "checkbox" && input.nextElementSibling ? input.nextElementSibling : input;
      anchor.insertAdjacentElement("afterend", box);
    }
    box.textContent = text;
    input.setAttribute("aria-invalid", "true");
    var described = (input.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
    if (described.indexOf(id) < 0) { described.push(id); input.setAttribute("aria-describedby", described.join(" ")); }
  }

  function clearError(input) {
    var box = document.getElementById(input.id + "-err");
    if (box) box.remove();
    input.removeAttribute("aria-invalid");
    var described = (input.getAttribute("aria-describedby") || "").split(" ")
      .filter(function (x) { return x && x !== input.id + "-err"; });
    if (described.length) input.setAttribute("aria-describedby", described.join(" "));
    else input.removeAttribute("aria-describedby");
  }

  function validate(form) {
    var name = field(form, "name"), tel = field(form, "tel"), mail = field(form, "email"), ok = field(form, "agree");
    var bad = [];
    [name, tel, mail, ok].forEach(function (f) { if (f) clearError(f); });

    if (name && !name.value.trim()) { setError(name, "Как к вам обращаться?"); bad.push(name); }

    var telVal = tel ? tel.value.trim() : "", mailVal = mail ? mail.value.trim() : "";
    // Заполненное поле должно быть правильным, даже если второе тоже заполнено.
    if (telVal && digits(telVal) < PHONE_MIN_DIGITS) { setError(tel, "Похоже, в номере не хватает цифр."); bad.push(tel); }
    if (mailVal && !EMAIL_RE.test(mailVal)) { setError(mail, "Проверьте адрес: в нём должны быть @ и домен."); bad.push(mail); }
    if (!telVal && !mailVal && tel && mail) {
      setError(tel, "Оставьте телефон или почту — иначе ответить будет некуда.");
      bad.push(tel);
    }

    if (ok && !ok.checked) { setError(ok, "Без согласия мы не можем принять заявку."); bad.push(ok); }
    return bad;
  }

  // ── статус под кнопкой ──
  function statusBox(form) {
    var box = form.querySelector(".form-status");
    if (!box) {
      box = document.createElement("div");
      box.className = "form-status";
      box.setAttribute("aria-live", "polite");
      var btn = form.querySelector('[type="submit"]');
      (btn ? btn.parentNode : form).insertAdjacentElement("afterend", box);
    }
    var old = form.querySelector("#sent");   // прежняя строка «Это макет…» из build.py
    if (old) old.hidden = true;
    return box;
  }

  function show(form, state, html) {
    var box = statusBox(form);
    box.setAttribute("data-state", state);
    box.setAttribute("role", state === "error" ? "alert" : "status");
    box.innerHTML = html;
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  // Письмо с уже заполненной заявкой: человеку не придётся перепечатывать.
  function mailtoHref(form, mail) {
    var lines = [];
    ["name", "tel", "email", "task"].forEach(function (n) {
      var f = field(form, n);
      if (f && f.value.trim()) {
        var label = form.querySelector('label[for="' + f.id + '"]');
        lines.push((label ? label.textContent.trim() : n) + ": " + f.value.trim());
      }
    });
    lines.push("Страница: " + location.href);
    var body = lines.join("\n").slice(0, 1500);
    return "mailto:" + mail + "?subject=" + encodeURIComponent("Заявка с сайта") + "&body=" + encodeURIComponent(body);
  }

  function fallbackHtml(form) {
    var c = contacts(form), parts = [];
    if (c.mail) parts.push('напишите на <a href="' + esc(mailtoHref(form, c.mail)) + '">' + esc(c.mail) + "</a>");
    if (c.tel) parts.push('позвоните: <a href="tel:' + esc(c.tel) + '">' + esc(c.telLabel) + "</a>");
    return parts.length ? " Чтобы заявка не потерялась, " + parts.join(" или ") + "." : "";
  }

  function setBusy(form, busy) {
    form.setAttribute("aria-busy", busy ? "true" : "false");
    var btn = form.querySelector('[type="submit"]');
    if (btn) btn.disabled = busy;
  }

  function send(form, endpoint) {
    var data = new FormData(form);
    data.set("page", location.href);
    data.set("page_title", document.title);
    var ctrl = typeof AbortController === "function" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, TIMEOUT_MS);
    return fetch(endpoint, {
      method: "POST",
      body: data,
      headers: { Accept: "application/json" },
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      clearTimeout(timer);
      if (!r.ok) { var err = new Error("HTTP " + r.status); err.name = "HttpError"; throw err; }
    }, function (err) {
      clearTimeout(timer);
      throw err;
    });
  }

  function onSubmit(e) {
    var form = e.currentTarget;
    e.preventDefault();
    e.stopImmediatePropagation();   // прежний обработчик макета из build.py не должен сработать вторым
    if (form.getAttribute("aria-busy") === "true") return;   // уже отправляется — второй клик не считаем

    var bad = validate(form);
    if (bad.length) {
      show(form, "invalid", "Проверьте отмеченные поля.");
      bad[0].focus();
      return;
    }

    // Ловушка для ботов: поле, которого человек не видит. Заполнено — делаем вид, что всё ушло.
    var trap = field(form, "website");
    if (trap && trap.value) { show(form, "sent", "Заявка отправлена. Мы свяжемся с вами в рабочее время."); return; }

    var endpoint = (form.getAttribute("data-endpoint") || "").trim();
    if (!endpoint) {
      show(form, "mock", "Это макет — заявка никуда не ушла." + fallbackHtml(form));
      return;
    }

    setBusy(form, true);
    show(form, "sending", "Отправляем заявку…");
    send(form, endpoint).then(function () {
      setBusy(form, false);
      form.reset();
      show(form, "sent", "Заявка отправлена. Мы свяжемся с вами в рабочее время.");
    }, function (err) {
      setBusy(form, false);   // введённое не трогаем: можно повторить или отправить письмом
      // Говорим только то, что знаем наверняка. Ошибка сети — это и «не дошло», и «дошло,
      // но браузер не дал прочитать ответ» (приёмник без разрешения CORS для нашего домена):
      // «не отправилась» там было бы неправдой и рождало бы дубли заявок.
      var name = err && err.name;
      var text = name === "AbortError" ? "Сервер не ответил — мы не знаем, дошла ли заявка."
               : name === "HttpError" ? "Заявка не принята: сервер ответил ошибкой."
               : "Не получилось связаться с сервером заявок.";
      show(form, "error", text + fallbackHtml(form));
    });
  }

  // Enter в однострочном поле не отправляет форму посреди заполнения, а переводит к следующему полю.
  function onKeydown(e) {
    var t = e.target;
    if (e.key !== "Enter" || e.isComposing || t.tagName !== "INPUT" || t.type === "checkbox" || t.type === "submit") return;
    e.preventDefault();
    var items = Array.prototype.filter.call(e.currentTarget.elements, function (el) {
      return !el.disabled && el.type !== "hidden" && el.offsetParent !== null;
    });
    var next = items[items.indexOf(t) + 1];
    if (next) next.focus();
  }

  function onInput(e) {
    if (e.target.getAttribute("aria-invalid") === "true") clearError(e.target);
    // ошибка «телефон или почта» висит на пустом телефоне — снимаем её, когда заполнили почту;
    // ошибку про неполный номер не трогаем
    if (e.target.name === "email") {
      var tel = field(e.currentTarget, "tel");
      if (tel && !tel.value.trim()) clearError(tel);
    }
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("form.form"), function (form) {
      form.addEventListener("submit", onSubmit, true);   // захват: раньше прежнего обработчика
      form.addEventListener("keydown", onKeydown);
      form.addEventListener("input", onInput);
      form.addEventListener("change", onInput);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
