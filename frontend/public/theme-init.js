/* MVP-8.3, раунд 2 (T4): синхронный скрипт темы до отрисовки. CSP запрещает
 * инлайн-скрипты (default-src 'self'), поэтому тема применяется внешним файлом
 * из <head>. Ставит data-theme и color-scheme до первого макета — без вспышки
 * тёмной темы у пользователя со светлой. Ключ хранилища совпадает с
 * src/lib/theme.ts (THEME_STORAGE_KEY). */
(function () {
  "use strict";
  var KEY = "veles-theme";
  var DEFAULT = "dark";
  var theme;
  try {
    var stored = window.localStorage.getItem(KEY);
    theme = stored === "light" || stored === "dark" ? stored : DEFAULT;
  } catch (err) {
    theme = DEFAULT;
  }
  var root = document.documentElement;
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
  var color = document.querySelector('meta[name="theme-color"]');
  if (color) {
    color.setAttribute("content", theme === "dark" ? "#0c0e16" : "#f6f7fc");
  }
  var scheme = document.querySelector('meta[name="color-scheme"]');
  if (scheme) {
    scheme.setAttribute("content", theme);
  }
})();
