import { h, render } from "preact";
import { useState, useEffect, useRef, useMemo, useCallback } from "preact/hooks";
import htm from "htm";
export const html = htm.bind(h);
export { h, render, useState, useEffect, useRef, useMemo, useCallback };

// ------------------------------------------------------------------ store
const listeners = new Set();
export const store = {
  token: (() => { try { return localStorage.getItem("uzx_token") } catch (e) { return null } })(),
  me: null, wallet: { wallet: 0, blocked: 0 }, unread: 0, lang: (() => { try { return localStorage.getItem("uzx_lang") || "ru" } catch (e) { return "ru" } })(),
  toasts: [], market: [], tick: 0,
};
export function set(patch) { Object.assign(store, patch); listeners.forEach(f => f()); }
export function useStore() {
  const [, force] = useState(0);
  useEffect(() => { const f = () => force(x => x + 1); listeners.add(f); return () => listeners.delete(f); }, []);
  return store;
}
export function setToken(t) { try { t ? localStorage.setItem("uzx_token", t) : localStorage.removeItem("uzx_token") } catch (e) {} set({ token: t }); }
export function setLang(l) { try { localStorage.setItem("uzx_lang", l) } catch (e) {} set({ lang: l }); }

// ------------------------------------------------------------------ api
export async function api(path, opts = {}) {
  const r = await fetch(path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(store.token ? { Authorization: "Bearer " + store.token } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await r.json() } catch (e) {}
  if (r.status === 401 && store.token && !opts.noLogout) { setToken(null); location.hash = ""; }
  if (!r.ok) throw new Error((data && data.detail) || `Ошибка ${r.status}`);
  return data;
}
export async function refreshMe() {
  if (!store.token) return;
  const d = await api("/api/me");
  set({ me: d.user, wallet: d.wallet, unread: d.unread });
  return d;
}

// ------------------------------------------------------------------ formatting
export const nf = (n, d = 0) => n === null || n === undefined || isNaN(n) ? "—" :
  Number(n).toLocaleString("ru-RU", { maximumFractionDigits: d, minimumFractionDigits: 0 });
export const sum = n => nf(n) + " " + (store.lang === "uz" ? "soʻm" : "сум");
export const short = n => { const a = Math.abs(n); const s = store.lang === "uz" ? ["ming", "mln", "mlrd", "trln"] : ["тыс", "млн", "млрд", "трлн"];
  if (a >= 1e12) return nf(n / 1e12, 2) + " " + s[3]; if (a >= 1e9) return nf(n / 1e9, 2) + " " + s[2];
  if (a >= 1e6) return nf(n / 1e6, 2) + " " + s[1]; if (a >= 1e4) return nf(n / 1e3, 1) + " " + s[0]; return nf(n); };
export const time = ts => new Date(ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const dt = ts => new Date(ts * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
export const pct = v => (v > 0 ? "+" : "") + nf(v, 2) + "%";
export const md = s => DOMPurify.sanitize(marked.parse(s || "", { breaks: true }));
export function countdown(ts, now) { const s = Math.max(0, Math.round(ts - now)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; }
export function useNow(ms = 1000) {
  const [n, setN] = useState(Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setN(Date.now() / 1000), ms); return () => clearInterval(t); }, [ms]);
  return n;
}
export function usePoll(fn, ms, deps = []) {
  useEffect(() => { let on = true; const go = () => on && fn(); go(); const t = setInterval(go, ms); return () => { on = false; clearInterval(t); }; }, deps);
}

// ------------------------------------------------------------------ toasts & live stream
export function toast(title, body = "", link = "") {
  const id = Math.random();
  set({ toasts: [...store.toasts, { id, title, body, link }].slice(-4) });
  setTimeout(() => set({ toasts: store.toasts.filter(t => t.id !== id) }), 6500);
}
let es = null;
export function connectStream() {
  if (es || !store.token) return;
  es = new EventSource("/api/stream?token=" + encodeURIComponent(store.token));
  es.onmessage = e => {
    const ev = JSON.parse(e.data);
    if (ev.type === "notification") {
      toast(ev.title, ev.body, ev.link);
      set({ unread: store.unread + 1, tick: store.tick + 1 });
      refreshMe().catch(() => {});
      try { if (document.hidden && Notification.permission === "granted") new Notification(ev.title, { body: ev.body }); } catch (x) {}
    } else if (ev.type === "session" || ev.type === "book") set({ tick: store.tick + 1 });
  };
  es.onerror = () => { es.close(); es = null; setTimeout(connectStream, 3000); };
}
export function go(link) { if (!link) return; location.hash = "#" + (link.startsWith("/") ? link : "/" + link); }

// ------------------------------------------------------------------ i18n (UI chrome; the agent itself speaks any language)
const T = {
  ru: { agent: "Агент", market: "Рынок", deals: "Сделки", wallet: "Кошелёк", profile: "Мой агент", ops: "Пульт биржи",
        available: "доступно", blocked: "в задатках", buyNow: "Покупать сейчас", wait: "Подождать", sellNow: "Продавать сейчас",
        ask: "Напишите или скажите, что нужно…", newMandate: "Поручить агенту", confirm: "Подтвердить", cancel: "Отмена" },
  uz: { agent: "Agent", market: "Bozor", deals: "Bitimlar", wallet: "Hamyon", profile: "Mening agentim", ops: "Birja pulti",
        available: "mavjud", blocked: "zakalatda", buyNow: "Hozir sotib oling", wait: "Kuting", sellNow: "Hozir soting",
        ask: "Nima kerakligini yozing yoki ayting…", newMandate: "Agentga topshirish", confirm: "Tasdiqlash", cancel: "Bekor qilish" },
};
export const t = k => (T[store.lang] || T.ru)[k] || T.ru[k] || k;
export const insName = i => i ? (store.lang === "uz" ? i.name_uz : i.name_ru) : "";

// ------------------------------------------------------------------ icons
const P = {
  agent: "M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.4 7.2 17.9l.9-5.4L4.2 8.7l5.4-.8z",
  market: "M3 17l5-6 4 3 7-9M15 5h4v4",
  deals: "M7 4h10a2 2 0 012 2v14l-3-2-3 2-3-2-3 2V6a2 2 0 012-2zM9 9h6M9 13h6",
  wallet: "M3 7a2 2 0 012-2h13v4M3 7v10a2 2 0 002 2h15V9H5a2 2 0 01-2-2zM16 14h.01",
  profile: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  ops: "M4 5h16v10H4zM8 19h8M12 15v4",
  bell: "M6 16V11a6 6 0 0112 0v5l2 2H4zM10 20a2 2 0 004 0",
  mic: "M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3zM5 11a7 7 0 0014 0M12 18v3",
  send: "M5 12h14M13 6l6 6-6 6",
  check: "M5 12.5l4.5 4.5L19 7",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  truck: "M3 7h11v9H3zM14 10h4l3 3v3h-7M7 19a2 2 0 100-4 2 2 0 000 4zM17 19a2 2 0 100-4 2 2 0 000 4z",
  camera: "M4 8h3l2-3h6l2 3h3v11H4zM12 17a4 4 0 100-8 4 4 0 000 8z",
  scale: "M12 3v18M5 7h14M5 7l-3 7a4 4 0 006 0zM19 7l-3 7a4 4 0 006 0z",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  users: "M9 11a4 4 0 100-8 4 4 0 000 8zM2 21a7 7 0 0114 0M17 3a4 4 0 010 8M22 21a7 7 0 00-5-6.7",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 018 0v4",
  spark: "M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M19 5l-4 4M9 15l-4 4",
  x: "M6 6l12 12M18 6L6 18", plus: "M12 5v14M5 12h14", arrow: "M5 12h14M13 6l6 6-6 6", back: "M19 12H5M11 6l-6 6 6 6",
  gavel: "M14 4l6 6M11 7l6 6M8 10l4 4M13 9l-9 9M3 21h9",
  calendar: "M4 6h16v15H4zM4 10h16M9 3v4M15 3v4",
  home: "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z", bellplus: "M6 16V11a6 6 0 0112 0v5l2 2H4zM10 20a2 2 0 004 0M12 8v5M9.5 10.5h5",
  lockp: "M6 11h12v10H6zM8 11V7a4 4 0 018 0v4M12 15v2", law: "M12 3v18M7 21h10M4 7l3 7a3 3 0 006 0zM20 7l-3 7a3 3 0 01-6 0zM4 7h16",
  sell: "M12 19V5M5 12l7-7 7 7", buy: "M12 5v14M5 12l7 7 7-7", calc: "M5 3h14v18H5zM8 7h8M8 12h2M12 12h2M16 12v5M8 16h2M12 16h2",
};
export const Icon = ({ n, s = 18, w = 1.8 }) => html`<svg width=${s} height=${s} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width=${w} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${P[n] || P.spark}/></svg>`;

export const Spark = ({ data, w = 72, h = 26 }) => {
  if (!data || data.length < 2) return null;
  const mn = Math.min(...data), mx = Math.max(...data), r = mx - mn || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - mn) / r) * (h - 2) - 1}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return html`<svg width=${w} height=${h} viewBox="0 0 ${w} ${h}"><polyline points=${pts} fill="none" stroke=${up ? "var(--up)" : "var(--down)"} stroke-width="1.6"/></svg>`;
};

export function Modal({ onClose, children }) {
  return html`<div class="modalbg" onClick=${e => e.target === e.currentTarget && onClose && onClose()}><div class="modal card pad">${children}</div></div>`;
}

export const STATUS = {
  signed: ["Договор подписан", "bl"], paid: ["Оплачено в сейф", "bl"], in_transit: ["В пути", "ag"], delivered: ["Ждёт приёмки", "ag"],
  settled: ["Завершена", "ok"], disputed: ["Спор", "bad"], resolved: ["Решено арбитром", "ok"], annulled: ["Аннулирована", "bad"],
  forward: ["Цена зафиксирована", "bl"], active: ["Активен", "ag"], filled: ["Исполнен", "ok"], expired: ["Истёк", ""], cancelled: ["Отменён", ""], draft: ["Черновик", ""],
};
export const Status = ({ s }) => { const [l, c] = STATUS[s] || [s, ""]; return html`<span class="chip ${c}">${l}</span>`; };

// ------------------------------------------------------------------ v2: Russian-keyed UI dictionary (UZ Latin)
const UZ = {
  "Главная": "Bosh sahifa", "Агент": "Agent", "Рынок": "Bozor", "Сделки": "Bitimlar", "Юрист": "Yurist", "Кошелёк": "Hamyon",
  "Мой агент": "Mening agentim", "Пульт биржи": "Birja pulti", "Выйти": "Chiqish", "доступно": "mavjud", "в задатках": "zakalatda",
  "Поручить агенту": "Agentga topshirish", "Продать через агента": "Agent orqali sotish", "Зафиксировать цену": "Narxni qotirish",
  "Сообщить о торгах": "Savdo haqida xabar berish", "Подписки": "Obunalar", "Когда выгоднее покупать": "Qachon arzonroq",
  "Рекомендация агента": "Agent tavsiyasi", "Покупать сейчас": "Hozir sotib oling", "Подождать": "Kuting", "Продавать сейчас": "Hozir soting",
  "Идут торги": "Savdo ketmoqda", "Следующая сессия": "Keyingi sessiya", "Как сложилась цена — последние сессии": "Narx qanday shakllandi — so‘nggi sessiyalar",
  "Поручения агенту": "Agentga topshiriqlar", "Что делает агент": "Agent nima qilyapti", "Документы — созданы и подписаны автоматически": "Hujjatlar — avtomatik yaratilgan va imzolangan",
  "Цепочка доказательств": "Dalillar zanjiri", "Доставка": "Yetkazib berish", "Приёмка товара": "Tovarni qabul qilish",
  "Решение ИИ-арбитра": "SI-arbitr qarori", "Движение денег": "Pul harakati", "Обоснование": "Asoslash",
  "Сделок пока нет": "Hozircha bitimlar yo‘q", "Пополнить": "To‘ldirish", "Доступно": "Mavjud", "Заблокировано в задатках": "Zakalatda bloklangan",
  "Что агент узнал о вас": "Agent siz haqingizda nimani bilib oldi", "Календарь торгов": "Savdolar taqvimi",
  "Сэкономлено агентом": "Agent tejagan", "Активные сделки": "Faol bitimlar", "Ближайшие торги по вашим товарам": "Tovarlaringiz bo‘yicha yaqin savdolar",
  "Индекс UZEX": "UZEX indeksi", "Задача на сегодня": "Bugungi vazifa", "Отгрузить": "Jo‘natish", "Подтвердить отгрузку": "Jo‘natishni tasdiqlash",
  "Ценовой щит": "Narx qalqoni", "Калькулятор неустойки": "Penya kalkulyatori", "Составить претензию": "Da’vo xati tuzish",
  "Судебная практика": "Sud amaliyoti", "Нормы права": "Huquqiy normalar", "Спросить агента": "Agentdan so‘rash", "Отмена": "Bekor qilish",
  "Подписать PIN-кодом": "PIN-kod bilan imzolash", "Купить": "Sotib olish", "Продать": "Sotish",
  "Биржа, где за вас торгует ваш агент": "Siz uchun agentingiz savdo qiladigan birja",
  "Новая модель взаимодействия людей и бизнеса с биржей: у каждого — личный ИИ-агент, а биржа становится честными правилами, гарантом и судьёй.":
    "Odamlar va biznesning birja bilan yangi munosabat modeli: har kimda shaxsiy SI-agent bor, birja esa adolatli qoidalar, kafil va hakamga aylanadi.",
  "Вы не торгуете — вы поручаете.": "Siz savdo qilmaysiz — topshirasiz.",
  "Скажите голосом, что нужно и до какой цены. Агент сам следит за рынком и торгуется.": "Nima kerakligini va qancha narxgacha ekanini ovoz bilan ayting. Agent bozorni o‘zi kuzatadi va savdolashadi.",
  "Без брокера, бумаг и терминала.": "Brokersiz, qog‘ozsiz va terminalsiz.",
  "Вход по MyID, подпись — PIN-кодом, документы создаются сами и проверяются по QR.": "MyID orqali kirish, PIN-kod bilan imzo, hujjatlar o‘zi yaratiladi va QR orqali tekshiriladi.",
  "Деньги в сейфе биржи.": "Pul birja seyfida.",
  "Продавец получает оплату только после того, как вы приняли товар.": "Sotuvchi to‘lovni faqat siz tovarni qabul qilganingizdan keyin oladi.",
  "Споры — за минуты.": "Nizolar — daqiqalarda.",
  "Весы, пломба и GPS записаны в цепочку доказательств. ИИ-арбитр видит, кто виноват.": "Tarozi, plomba va GPS dalillar zanjiriga yoziladi. SI-arbitr kim aybdorligini ko‘radi.",
  "Создайте своего агента": "O‘z agentingizni yarating", "Начать": "Boshlash",
  "2 минуты. Нужен только телефон и ID-карта. Никаких брокерских договоров.": "2 daqiqa. Faqat telefon va ID-karta kerak. Broker shartnomalari yo‘q.",
  "Номер телефона": "Telefon raqami", "Это ваш логин. Пароль не нужен.": "Bu sizning loginingiz. Parol kerak emas.",
  "Получить код": "Kodni olish", "Войти": "Kirish", "Проверка личности MyID": "MyID orqali shaxsni tasdiqlash",
  "Пройти проверку": "Tekshiruvdan o‘tish", "Кто вы на бирже?": "Birjada kimsiz?", "Продолжить": "Davom etish",
  "Ваш личный агент": "Shaxsiy agentingiz", "Создать агента": "Agentni yaratish", "Пополните кошелёк": "Hamyonni to‘ldiring",
  "Позже": "Keyinroq", "Перейти к агенту": "Agentga o‘tish",
  "реальная котировка UZEX": "ta real UZEX kotirovkasi", "сделок реестра": "ta reyestr bitimi", "реальных судебных дела": "ta real sud ishi",
  "Это рабочий прототип: государственные сервисы (SMS, MyID, оплата картой) имитируются, но весь процесс — торги, клиринг, подписи, документы, споры — работает по-настоящему.":
    "Bu ishlaydigan prototip: davlat xizmatlari (SMS, MyID, karta orqali to‘lov) imitatsiya qilinadi, lekin butun jarayon — savdo, kliring, imzolar, hujjatlar, nizolar — haqiqatda ishlaydi.",
  "Согласен на обработку персональных данных (Закон РУз «О персональных данных», ЗРУ-547) и с правилами платформы":
    "Shaxsga doir ma’lumotlarni qayta ishlashga (O‘zR «Shaxsga doir ma’lumotlar to‘g‘risida»gi Qonuni) va platforma qoidalariga roziman",


};
export const tr = s => store.lang === "uz" ? (UZ[s] || s) : s;
export const NAMES = { cement: ["Цемент", "Sement"], propane: ["Сжиженный газ", "Suyultirilgan gaz"], ai92: ["Бензин А-92", "A-92 benzini"],
  pp: ["Полипропилен", "Polipropilen"], urea: ["Карбамид", "Karbamid"], wheat: ["Пшеница", "Bug‘doy"], sugar: ["Сахар", "Shakar"], rebar: ["Арматура", "Armatura"] };
export const nm = k => (NAMES[k] || [k, k])[store.lang === "uz" ? 1 : 0];
