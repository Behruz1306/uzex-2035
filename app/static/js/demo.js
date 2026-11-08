import { html, useState, useEffect, api, nf, sum, short, Icon, go } from "./lib.js";
import { FindScreen, MarketDetail, BusinessScreen } from "./insights.js";

const SLUG = "ammonium-nitrate";
const QTY = 500;
const SCENES = [
  ["Поиск", "Покупатель ищет товар в интернете"],
  ["Запрос", "Пишет одной фразой — ИИ-брокер понимает"],
  ["Рынок", "Данные биржи вместо догадок"],
  ["Мой бизнес", "Брокер, который знает, куда расти"],
  ["Сделка", "Исполнение с гарантией биржи"],
  ["Итог", "Что получает биржа"],
];

const clampStep = a => Math.min(Math.max((+(a || 1) || 1) - 1, 0), SCENES.length - 1);

export function DemoScreen({ arg }) {
  const i = clampStep(arg);
  const setI = k => { location.hash = "#/demo/" + (Math.min(Math.max(k, 0), SCENES.length - 1) + 1); };
  const [m, setM] = useState(null);
  useEffect(() => { api("/api/insights/market/" + SLUG).then(setM); }, []);
  useEffect(() => {
    const k = e => { if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
      const cur = clampStep(location.hash.split("/")[2]);
      if (e.key === "ArrowRight") setI(cur + 1); if (e.key === "ArrowLeft") setI(cur - 1); };
    addEventListener("keydown", k); return () => removeEventListener("keydown", k);
  }, []);
  useEffect(() => { scrollTo({ top: 0, behavior: "smooth" }); }, [i]);
  const S = [Search, Ask, Market, Business, Deal, Outcome][i];
  return html`<div class="demo">
    <div class="demo-steps">${SCENES.map(([t], k) => html`<button class=${k === i ? "on" : k < i ? "done" : ""} onClick=${() => setI(k)}>
      <i>${k < i ? html`<${Icon} n="check" s=${13}/>` : k + 1}</i><span>${t}</span></button>`)}</div>
    <div class="demo-head"><div class="h1">${SCENES[i][1]}</div></div>
    <${S} m=${m}/>
    <div class="demo-nav">
      <button class="btn ghost" disabled=${i === 0} onClick=${() => setI(i - 1)}><${Icon} n="back" s=${16}/> Назад</button>
      <span class="tiny muted">${i + 1} из ${SCENES.length}<span class="hide-m"> · стрелки ← → на клавиатуре</span></span>
      ${i < SCENES.length - 1 ? html`<button class="btn pri" onClick=${() => setI(i + 1)}>Дальше <${Icon} n="arrow" s=${16}/></button>`
        : html`<button class="btn pri" onClick=${() => go("/find")}>Попробовать самому</button>`}
    </div>
  </div>`;
}

const Note = ({ children }) => html`<p class="demo-note"><${Icon} n="spark" s=${15}/><span>${children}</span></p>`;

// 1 — the exchange appears where buyers already search (search engine + AI assistant)
function Search({ m }) {
  if (!m) return html`<div class="empty"><span class="spin"/></div>`;
  const url = `uzex-2035.fly.dev › tovar › ${SLUG}`;
  return html`<div class="grid" style="gap:14px">
    <div class="grid two">
      <div class="serp">
        <div class="serp-q"><${Icon} n="spark" s=${15}/> ammonium nitrate Uzbekistan wholesale 500 t</div>
        <div class="serp-r hl"><div class="u">${url}</div><a class="t" href=${"/tovar/" + SLUG} target="_blank" rel="noopener">${m.name} оптом — цена ${nf(m.price)} сум/т | UZEX</a>
          <div class="rich"><b>${nf(m.price)} сум/т</b> · ${m.sellers} продавцов · исполнено ${m.exec_rate}% сделок · в наличии</div>
          <div class="d">${m.name} (${m.en}) на Узбекской товарной бирже. Купить с гарантией расчётов: деньги блокируются на клиринговом счёте, продавец вносит задаток.</div></div>
        <div class="serp-r"><div class="u">board.example › chemicals</div><div class="t">Селитра аммиачная, цена договорная — объявление</div><div class="d">Звоните, цена по запросу. Предоплата 100%.</div></div>
        <div class="serp-r"><div class="u">plant-site.example</div><div class="t">Химический завод — продукция</div><div class="d">Сайт временно недоступен.</div></div>
      </div>
      <div class="aibox">
        <div class="aiq">Where can I buy 500 t of ammonium nitrate in Uzbekistan with a guarantee?</div>
        <div class="aia"><div class="tiny muted" style="margin-bottom:4px">ИИ-ассистент</div>
          On the Uzbek commodity exchange (UZEX) ammonium nitrate trades at about <b>${nf(m.price)} UZS/t</b>.
          There are <b>${m.sellers} sellers</b>; ${m.exec_rate}% of deals were executed. The exchange guarantees settlement, so no bank guarantee or prepayment is needed.
          <div class="src">Источник: ${url} · /llms.txt</div></div>
      </div>
    </div>
    <${Note}>Сегодня страницы предложений на uzex.uz закрыты от поисковиков (в robots.txt: <code>Disallow: /Trade/Offer</code>), и покупатель находит доски объявлений и неработающие сайты. Мы открываем витрину биржи: у каждого товара своя страница с ценой и продавцами, разметка для поисковиков, карта сайта и файл для ИИ-ассистентов. Цифры здесь реальные, оформление поисковика — иллюстрация.<//>
    <div class="row" style="gap:8px;flex-wrap:wrap"><a class="btn ghost sm" href=${"/tovar/" + SLUG} target="_blank" rel="noopener">Открыть живую страницу товара</a>
      <a class="btn ghost sm" href="/llms.txt" target="_blank" rel="noopener">Файл для ИИ-ассистентов</a><a class="btn ghost sm" href="/sitemap.xml" target="_blank" rel="noopener">Карта сайта</a></div>
  </div>`;
}

// 2 — one-phrase request, live
function Ask() {
  return html`<div class="grid" style="gap:12px">
    <${Note}>Иностранный покупатель пишет как в мессенджере, на своём языке. ИИ-брокер разбирает запрос (товар, объём, куда, срок) и сразу показывает цену биржи, надёжных продавцов и полную стоимость. Это работает вживую — можно ввести свой запрос.<//>
    <${FindScreen} auto="Malayziyaga 500 tonna selitra kerak, dekabrgacha. Narxi qancha?"/>
  </div>`;
}

// 3 — market data, live
function Market() {
  return html`<div class="grid" style="gap:12px">
    <${Note}>Сегодня такие данные биржа даёт только крупным компаниям по платному запросу. ИИ-брокер показывает их каждому: оборот и рост, цена, сколько покупателей и продавцов, где спрос, когда дешевле и кто из продавцов надёжен. Источник — реестр 500 000 сделок.<//>
    <${MarketDetail} s=${SLUG}/>
  </div>`;
}

// 4 — the mentor's example on real data
function Business() {
  return html`<div class="grid" style="gap:12px">
    <${Note}>Пример ментора про блокноты и стаканчики — на реальной компании из реестра. Брокер видит, какую долю рынка занимает компания, где спрос есть, а продаж нет, и что ещё покупают её же покупатели. Кнопка «План роста» — ИИ-брокер составит план на год.<//>
    <${BusinessScreen}/>
  </div>`;
}

// 5 — execution: what happens after the request (visual walkthrough of the working prototype)
function Deal({ m }) {
  const [k, setK] = useState(0);
  useEffect(() => { const t = setInterval(() => setK(x => (x + 1) % 7), 1700); return () => clearInterval(t); }, []);
  if (!m) return html`<div class="empty"><span class="spin"/></div>`;
  const goods = QTY * m.price, dep = Math.round(goods * 0.1);
  const steps = [
    ["doc", "Поручение", `Купить ${QTY} т не дороже ${nf(Math.round(m.price * 1.03))} сум/т до декабря. Клиент подписывает PIN-кодом; агент не может выйти за эти границы.`],
    ["market", "Торги", "Поручение уходит через брокерскую контору на торговую сессию. Цена — единая по итогам торгов, видно, почему она такая."],
    ["lock", "Гарантия", `Задаток покупателя ${short(dep)} сум и задаток продавца блокируются на клиринговом счёте биржи. Сборы: 0,13% + 0,05%.`],
    ["shield", "Документы", "Договор, счёт-фактура (ЭСФ с кодом ИКПУ, НДС 12%) и накладная создаются сами, подписываются, проверяются по QR."],
    ["truck", "Отгрузка", "Продавец отмечает вес, госномер и пломбу. Покупатель на приёмке фотографирует весовой талон — ИИ читает вес."],
    ["scale", "Спор, если нужно", "Недовес → весы, пломба и GPS сравниваются автоматически: видно, кто виноват — продавец или перевозчик. Решение утверждает арбитр биржи."],
    ["check", "Расчёт", `Продавец получает ${short(goods)} сум, рейтинги обеих сторон обновляются — следующий покупатель увидит, кто надёжен.`],
  ];
  return html`<div class="grid" style="gap:14px">
    <div class="pipe">${steps.map(([ic, t, d], j) => html`<div class=${"pipe-s" + (j === k ? " on" : j < k ? " done" : "")} onClick=${() => setK(j)}>
      <div class="pipe-i"><${Icon} n=${ic} s=${18}/></div><b>${t}</b><span>${d}</span></div>`)}</div>
    <div class="grid two">
      <div class="card pad"><h3>Сделка в цифрах</h3>
        <div class="kv"><span>${QTY} т × ${nf(m.price)} сум/т</span><b class="mono">${sum(goods)}</b></div>
        <div class="kv"><span>Сборы биржи и клиринг</span><b class="mono">${sum(Math.round(goods * 0.0018))}</b></div>
        <div class="kv"><span>Задаток (засчитывается в оплату)</span><b class="mono">${sum(dep)}</b></div>
        <div class="kv"><span>Банковская гарантия, письма о намерениях</span><b>не нужны</b></div></div>
      <div class="card pad"><h3>Что работает уже сейчас</h3>
        <p class="small" style="margin:0 0 8px;color:var(--text2)">Весь путь исполнения — рабочий прототип: торги по расписанию, клиринг с двойной записью, подписи Ed25519, документы с QR, цепочка доказательств, разбор спора. Госсервисы (SMS, MyID, Payme/Click) — в песочнице, протоколы реализованы.</p>
        <button class="btn sm" onClick=${() => go("/start")}>Пройти сделку вживую</button></div>
    </div>
    <${Note}>Схема показывает весь путь сделки по шагам. Каждый шаг можно открыть в рабочем прототипе: войти, дать поручение ИИ-брокеру, дождаться торгов и посмотреть документы.<//>
  </div>`;
}

// 6 — what the exchange gets
function Outcome() {
  const [o, setO] = useState(null);
  useEffect(() => { api("/api/insights/overview").then(setO); }, []);
  return html`<div class="grid" style="gap:14px">
    <div class="kpis">
      <div class="kpi"><span>Рынок в зоне охвата</span><b class="mono agentc">$49 млрд</b><i class="tiny muted">в год: оборот UZEX ≈ $16 млрд + экспорт Узбекистана $33,4 млрд</i></div>
      <div class="kpi"><span>Новый оборот через биржу</span><b class="mono">до +$1,1 млрд</b><i class="tiny muted">в год: +20% товарных торгов и экспорт через биржу до 1%</i></div>
      <div class="kpi"><span>Компаний-клиентов</span><b class="mono">до 27 000</b><i class="tiny muted">13 500 участников торгов + 14 000 производителей вне биржи</i></div>
      <div class="kpi"><span>Покупателей на одного продавца</span><b class="mono">${o ? Math.round(o.buyers / o.sellers) : "—"}</b><i class="tiny muted">${o ? `${nf(o.buyers)} / ${o.sellers} в ${o.year}` : ""} — продавцов не хватает</i></div></div>
    <div class="grid three">
      <div class="card pad"><h3><${Icon} n="users" s=${16}/> Доступность</h3><p class="small" style="margin:0">Биржу находят из интернета; запрос одной фразой на любом языке; малый бизнес получает те же данные, что и крупный.</p></div>
      <div class="card pad"><h3><${Icon} n="market" s=${16}/> Прозрачность</h3><p class="small" style="margin:0">Цены, спрос по регионам и рейтинг надёжности продавцов открыты. Посредник больше не решает, кто с кем работает.</p></div>
      <div class="card pad"><h3><${Icon} n="shield" s=${16}/> Безопасность</h3><p class="small" style="margin:0">Деньги на клиринговом счёте, задатки, поручение с границами и PIN; чужие сделки — только в агрегатах.</p></div></div>
    <div class="card pad"><h3>Рынок</h3>
      <div class="kv"><span>TAM — оборот, который может идти через ИИ-брокера (биржа + экспорт)</span><b class="mono">≈ $49 млрд/год</b></div>
      <div class="kv"><span>SAM — оборот всех площадок UZEX</span><b class="mono">≈ $16 млрд/год</b></div>
      <div class="kv"><span>SOM — новый оборот через ИИ-брокера к 2029 году</span><b class="mono">≈ $1,1 млрд/год</b></div>
      <div class="kv"><span>Потенциал выручки сервиса (подписка на аналитику + 0,1% со сделок)</span><b class="mono">до $82 млн/год</b></div>
      <p class="tiny muted" style="margin:8px 0 0">Источники: spot.uz (оборот UZEX), gov.uz (экспорт 2025), stat.uz, реестр сделок UZEX; допущения помечены в расчёте.</p></div>
  </div>`;
}
