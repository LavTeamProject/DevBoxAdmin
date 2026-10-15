// Проверка словарей интерфейса: ru и en обязаны содержать ОДИНАКОВЫЕ ключи (i18n.js + static/i18n-ext-*.js).
// Запуск из папки проекта:  node check-i18n.js
const fs = require("fs"), path = require("path"), vm = require("vm");
const dir = path.join(__dirname, "static");
const files = ["i18n.js", ...fs.readdirSync(dir).filter((f) => /^i18n-ext-.*\.js$/.test(f)).sort()];
const sandbox = { console }; vm.createContext(sandbox);
// i18n.js обращается к DOM только внутри функций; выполняем лишь определение словарей
const src = fs.readFileSync(path.join(dir, "i18n.js"), "utf8");
const start = src.indexOf("const I18N = {"), end = src.indexOf("\n};", start) + 3;
vm.runInContext(src.slice(start, end).replace("const I18N", "var I18N"), sandbox);
for (const f of files.slice(1)) vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), sandbox);
const I = sandbox.I18N, ru = Object.keys(I.ru), en = Object.keys(I.en);
const missEn = ru.filter((k) => !(k in I.en)), missRu = en.filter((k) => !(k in I.ru));
console.log(`ru ${ru.length} · en ${en.length} · файлов: ${files.length}`);
if (missEn.length) console.log("нет в en:", missEn.slice(0, 40), missEn.length > 40 ? `…(+${missEn.length - 40})` : "");
if (missRu.length) console.log("нет в ru:", missRu.slice(0, 40), missRu.length > 40 ? `…(+${missRu.length - 40})` : "");
process.exit(missEn.length || missRu.length ? 1 : 0);
