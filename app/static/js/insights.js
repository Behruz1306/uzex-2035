import { html, useState, useEffect, useRef, api, store, set, useStore, nf, sum, short, Icon, go, tr } from "./lib.js";

const sgn = v => v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + nf(v, 1) + "%";
const cls = v => v === null || v === undefined ? "muted" : v >= 0 ? "up" : "down";
const unitS = u => ({ "тонна": "т", "килограмм": "кг", "литр": "л", "штука": "шт", "куб.метр": "м³", "кв.метр": "м²", "метр": "м" }[u] || u);
const regionRu = r => (r || "").replace(" viloyati", " обл.").replace("Toshkent shahri", "г. Ташкент").replace("Qoraqalpog‘iston Respublikasi", "Каракалпакстан")
  .replace("Farg‘ona", "Фергана").replace("Toshkent", "Ташкентская").replace("Namangan", "Наманган").replace("Buxoro", "Бухара").replace("Samarqand", "Самарканд")
  .replace("Sirdaryo", "Сырдарья").replace("Qashqadaryo", "Кашкадарья").replace("Xorazm", "Хорезм").replace("Andijon", "Андижан").replace("Surxondaryo", "Сурхандарья")
  .replace("Navoiy", "Навои").replace("Jizzax", "Джизак");
const askBroker = q => { set({ pendingAsk: q }); go(store.token ? "/agent" : "/start"); };
const Src = () => html`<p class="tiny muted" style="margin:6px 0 0">Источник: реестр сделок UZEX, 500 000 сделок 2022–2026. Данные других компаний — только в обобщённом виде.</p>`;

// ------------------------------------------------------------------ Find: request in one phrase
const EXAMPLES = ["Нужно 30 тонн цемента в Самарканд до пятницы", "Malayziyaga 500 tonna selitra kerak, dekabrgacha",
  "Need 2,000 t of urea delivered to Afghanistan, price?", "Хочу продать 40 тонн муки, кому и почём?"];

export function FindScreen({ arg }) {
  const q0 = decodeURIComponent((arg || "").split("q=")[1] || "");
  const [text, setText] = useState(q0 ? `Нужно купить: ${q0}` : "");
  const [img, setImg] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const send = async (t = text) => {
    if (!t.trim() && !img) return;
    setBusy(true); setErr(""); setRes(null);
    try { setRes(await api("/api/rfq", { method: "POST", body: { text: t, image: img } })); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const pick = e => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => setImg(r.result); r.readAsDataURL(f); };
  return html`<div class="grid" style="gap:16px;max-width:880px">
    <div><div class="h1">Найти товар на бирже</div>
      <p class="sub">Напишите, что нужно, как в мессенджере: на русском, узбекском или английском. Можно приложить скриншот переписки. ИИ-брокер найдёт товар на бирже, покажет цену, надёжных продавцов и полную стоимость. Регистрация не нужна.</p></div>
    <div class="card pad">
      <textarea class="inp" rows="3" style="width:100%;resize:vertical" placeholder="Например: нужно 30 тонн цемента в Самарканд до пятницы" value=${text}
        onInput=${e => setText(e.target.value)} onKeyDown=${e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }}/>
      <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:10px">
        <label class="btn ghost sm"><${Icon} n="camera" s=${15}/> ${img ? "Скриншот приложен" : "Скриншот"}<input type="file" accept="image/*" hidden onChange=${pick}/></label>
        ${img && html`<button class="btn ghost sm" onClick=${() => setImg(null)}><${Icon} n="x" s=${14}/></button>`}
        <span class="sp"/>
        <button class="btn" disabled=${busy} onClick=${() => send()}>${busy ? html`<span class="spin"/>` : html`<${Icon} n="send" s=${16}/>`} Найти</button>
      </div>
      <div class="chips" style="margin-top:12px">${EXAMPLES.map(x => html`<button class="chip" onClick=${() => { setText(x); send(x); }}>${x}</button>`)}</div>
    </div>
    ${err && html`<div class="card pad err">${err}</div>`}
    ${res && html`<${RfqResult} r=${res}/>`}
  </div>`;
}

function RfqResult({ r }) {
  const p = r.parsed || {}, m = r.market;
  return html`<div class="grid" style="gap:12px">
    <div class="card pad" style="border-color:var(--agent)"><div class="row" style="gap:10px;align-items:flex-start">
      <div class="av" style="flex:none"><${Icon} n="agent" s=${18}/></div>
      <div><div class="small muted">ИИ-брокер</div><div>${r.reply}</div>
        <div class="chips" style="margin-top:8px">${[p.side === "sell" ? "Продать" : "Купить", m?.name || p.product, p.qty && `${nf(p.qty)} ${unitS(p.unit)}`, p.destination, p.deadline, p.foreign && "иностранный покупатель"]
          .filter(Boolean).map(x => html`<span class="chip">${x}</span>`)}</div></div></div></div>
    ${!r.found ? html`<div class="card pad">${r.next}</div>` : html`
    <div class="grid two">
      <div class="card pad"><h3>${m.name} на бирже</h3>
        <div class="kpis" style="grid-template-columns:1fr 1fr">
          <div class="kpi"><span>Цена сделок</span><b class="mono">${nf(m.price)}</b><i class="tiny muted">сум/${unitS(m.unit)} · ${sgn(m.price_change)} за год</i></div>
          <div class="kpi"><span>Продавцов</span><b class="mono">${m.sellers}</b><i class="tiny muted">исполнено ${m.exec_rate}% сделок</i></div></div>
        ${r.cheapest_months?.length ? html`<p class="small" style="margin:10px 0 0">Обычно дешевле: <b class="up">${r.cheapest_months.map(x => x.month).join(", ")}</b></p>` : ""}
        <p class="small" style="margin:8px 0 0;color:var(--text2)"><${Icon} n="shield" s=${14}/> ${r.guarantee}</p></div>
      <div class="card pad"><h3>Надёжные продавцы</h3>
        ${r.sellers.map(s => html`<div class="lrow"><span style="flex:1;min-width:0"><b class="small">${s.name}</b><div class="tiny muted">${s.deals} сделок · в срок ${s.on_time}%</div></span><span class="chip ok">${s.score}</span></div>`)}
        <p class="tiny muted" style="margin:6px 0 0">Рейтинг 0–100: исполнение, поставка в срок, стаж на бирже, объём.</p></div>
    </div>
    ${r.estimate && html`<div class="card pad"><h3><${Icon} n="calc" s=${15}/> Полная стоимость до сделки</h3>
      <div class="kv"><span>Товар</span><b class="mono">${sum(r.estimate.goods)}</b></div>
      <div class="kv"><span>Сборы биржи и клиринг</span><b class="mono">${sum(r.estimate.fees)}</b></div>
      <div class="kv"><span>Итого</span><b class="mono">${sum(r.estimate.total)}</b></div>
      <div class="kv"><span>Задаток (вернётся в оплату)</span><b class="mono">${sum(r.estimate.deposit)}</b></div>
      <p class="tiny muted" style="margin:6px 0 0">${r.estimate.note} Цена — медиана последних сделок; итог определят торги.</p></div>`}
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <button class="btn" onClick=${() => askBroker(`${p.side === "sell" ? "Хочу продать" : "Хочу купить"} ${m.name}${p.qty ? ` ${p.qty} ${unitS(p.unit)}` : ""}${p.destination ? `, ${p.destination}` : ""}${p.deadline ? `, ${p.deadline}` : ""}. Подготовь поручение.`)}>
        <${Icon} n="agent" s=${16}/> Оформить через ИИ-брокера</button>
      <button class="btn ghost" onClick=${() => go("/markets/" + m.slug)}>Аналитика рынка</button>
      <a class="btn ghost" href=${r.page} target="_blank" rel="noopener">Открытая страница товара</a>
    </div>`}
  </div>`;
}

// ------------------------------------------------------------------ Markets: exchange data for everyone
export function MarketsScreen({ arg }) {
  return arg ? html`<${MarketDetail} s=${arg} key=${arg}/>` : html`<${MarketsList}/>`;
}

function MarketsList() {
  const [ov, setOv] = useState(null), [list, setList] = useState([]), [qq, setQ] = useState(""), [cat, setCat] = useState("");
  useEffect(() => { api("/api/insights/overview").then(setOv); api("/api/insights/markets").then(d => setList(d.markets)); }, []);
  const cats = [...new Set(list.map(f => f.category))];
  const shown = list.filter(f => (!cat || f.category === cat) && (!qq || (f.name + f.en).toLowerCase().includes(qq.toLowerCase())));
  return html`<div class="grid" style="gap:16px">
    <div><div class="h1">Рынки биржи</div><p class="sub">Что покупают на UZEX, сколько, где и у кого — по реальному реестру сделок. Для производителя это карта спроса, для покупателя — карта цен и надёжных продавцов.</p></div>
    ${ov && html`<div class="kpis">
      <div class="kpi"><span>Сделок за ${ov.year}</span><b class="mono">${nf(ov.deals)}</b><i class="tiny muted">$${short(ov.volume_usd)}</i></div>
      <div class="kpi"><span>Покупателей</span><b class="mono">${nf(ov.buyers)}</b><i class="tiny muted">${ov.small_buyers} малых</i></div>
      <div class="kpi"><span>Продавцов</span><b class="mono">${ov.sellers}</b><i class="tiny agentc">в ${Math.round(ov.buyers / ov.sellers)} раз меньше покупателей</i></div>
      <div class="kpi"><span>Исполнено сделок</span><b class="mono">${ov.exec_rate}%</b><i class="tiny muted">продавцов: ${ov.sellers_by_year[2022]} → ${ov.sellers_by_year[2025]}</i></div></div>`}
    ${ov && html`<div class="card pad"><h3><${Icon} n="market" s=${15}/> Где растёт спрос</h3><div class="chips">
      ${ov.rising.map(f => html`<button class="chip" onClick=${() => go("/markets/" + f.slug)}>${f.name} <b class="up">${sgn(f.growth)}</b></button>`)}</div>
      <p class="tiny muted" style="margin:8px 0 0">Рост оборота ${ov.year} к ${ov.year - 1}, товары с оборотом от $3 млн.</p></div>`}
    <div class="card" style="overflow:hidden">
      <div class="row" style="flex-wrap:wrap;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)">
        <input class="inp" style="flex:1;min-width:160px" placeholder="Поиск товара" value=${qq} onInput=${e => setQ(e.target.value)}/>
        <select class="inp" value=${cat} onChange=${e => setCat(e.target.value)}><option value="">Все категории</option>${cats.map(c => html`<option>${c}</option>`)}</select></div>
      <div class="tbl-wrap"><table class="tbl mk-tbl"><thead><tr><th>Товар</th><th>Оборот за год</th><th>Рост</th><th>Цена</th><th>Продавцов</th><th class="hide-m">Доля топ-3</th></tr></thead>
        <tbody>${shown.map(f => html`<tr class="click" onClick=${() => go("/markets/" + f.slug)}>
          <td><b>${f.name}</b><div class="tiny muted">${f.category}</div></td><td class="mono">${short(f.volume_uzs)}</td>
          <td class="mono ${cls(f.growth)}">${sgn(f.growth)}</td><td class="mono">${nf(f.price)}<span class="tiny muted"> /${unitS(f.unit)}</span></td>
          <td class="mono">${f.sellers}</td><td class="mono hide-m">${f.top3_share}%</td></tr>`)}</tbody></table></div>
      ${!list.length && html`<div class="empty"><span class="spin"/></div>`}
    </div><${Src}/>
  </div>`;
}

function VolChart({ d }) {
  const el = useRef(null);
  useEffect(() => {
    const LW = window.LightweightCharts;
    const c = LW.createChart(el.current, { autoSize: true, layout: { background: { color: "transparent" }, textColor: "#7E8BA3", fontFamily: "JetBrains Mono" },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(36,50,77,.45)" } }, rightPriceScale: { borderColor: "#24324D" },
      leftPriceScale: { visible: true, borderColor: "#24324D" }, timeScale: { borderColor: "#24324D" }, localization: { priceFormatter: p => short(p) } });
    const pts = d.monthly.filter(m => m.m >= "2022-01");
    c.addHistogramSeries({ priceScaleId: "left", color: "rgba(76,141,255,.55)", priceLineVisible: false, lastValueVisible: false })
      .setData(pts.map(m => ({ time: m.m + "-01", value: m.vol })));
    c.addLineSeries({ color: "#F5B93D", lineWidth: 2, priceLineVisible: false }).setData(pts.filter(m => m.price).map(m => ({ time: m.m + "-01", value: m.price })));
    c.timeScale().fitContent();
    return () => c.remove();
  }, [d.slug]);
  return html`<div class="chart" style="height:260px" ref=${el}/>`;
}

function MarketDetail({ s }) {
  const [d, setD] = useState(null);
  useEffect(() => { api("/api/insights/market/" + s).then(setD); }, [s]);
  if (!d) return html`<div class="empty"><span class="spin"/></div>`;
  const M = ["я", "ф", "м", "а", "м", "и", "и", "а", "с", "о", "н", "д"];
  const sp = d.season_price || [], mx = Math.max(...sp.map(v => Math.abs(v - 100)), 1);
  const nb = d.new_buyers || {};
  return html`<div class="grid" style="gap:16px">
    <div><button class="btn ghost sm" onClick=${() => go("/markets")}><${Icon} n="back" s=${15}/> Все рынки</button>
      <div class="h1" style="margin-top:8px">${d.name}</div><p class="sub">${d.category} · ${d.industry}</p></div>
    <div class="kpis">
      <div class="kpi"><span>Оборот за год</span><b class="mono">${short(d.volume_uzs)}</b><i class="tiny ${cls(d.growth)}">${sgn(d.growth)} к прошлому году</i></div>
      <div class="kpi"><span>Цена сделок</span><b class="mono">${nf(d.price)}</b><i class="tiny muted">сум/${unitS(d.unit)} · ${sgn(d.price_change)}</i></div>
      <div class="kpi"><span>Покупателей / продавцов</span><b class="mono">${nf(d.buyers)} / ${d.sellers}</b><i class="tiny muted">продавцов год назад: ${d.sellers_prev}</i></div>
      <div class="kpi"><span>Доля трёх крупнейших</span><b class="mono">${d.top3_share}%</b><i class="tiny muted">${d.top3_share > 70 ? "рынок сконцентрирован" : "есть место новым продавцам"}</i></div></div>
    <div class="card pad"><h3>Оборот по месяцам и цена</h3><${VolChart} d=${d}/>
      <p class="tiny muted" style="margin:6px 0 0"><span style="color:#4C8DFF">■</span> оборот, сум · <span class="agentc">—</span> медианная цена сделки</p></div>
    <div class="grid two">
      <div class="card pad"><h3><${Icon} n="calendar" s=${15}/> Когда цена ниже</h3>
        <div class="season">${sp.map((v, i) => html`<div class="sm"><div class="bw"><i class=${v < 100 ? "lo" : "hi"} style="height:${Math.abs(v - 100) / mx * 48}%;${v < 100 ? "top:50%" : "bottom:50%"}"/></div>
          <span class="mono tiny ${v < 100 ? "up" : "down"}">${v > 100 ? "+" : ""}${nf(v - 100, 1)}</span><span class="tiny muted">${M[i]}</span></div>`)}</div>
        <p class="small" style="margin:8px 0 0">Дешевле всего: <b class="up">${(d.cheapest_months || []).map(x => x.month).join(", ")}</b> (средний профиль цены 2022–2025).</p></div>
      <div class="card pad"><h3><${Icon} n="users" s=${15}/> Где покупают</h3>
        ${d.regions.slice(0, 7).map(r => html`<div class="bar-row"><span class="small" style="width:120px;flex:none">${regionRu(r.region)}</span>
          <div class="bar-t"><i style="width:${r.share * 2.2}%"/></div><span class="mono small" style="width:46px;text-align:right">${r.share}%</span>
          <span class="mono tiny ${cls(r.growth)}" style="width:58px;text-align:right">${sgn(r.growth)}</span></div>`)}
        <p class="tiny muted" style="margin:6px 0 0">Доля оборота ${d.monthly.length ? "2025" : ""} и рост к прошлому году. Регионы, где меньше 3 покупателей, скрыты.</p></div>
    </div>
    <div class="grid two">
      <div class="card pad"><h3><${Icon} n="shield" s=${15}/> Рейтинг продавцов</h3>
        ${d.top_sellers.slice(0, 8).map(x => html`<div class="lrow"><span style="flex:1;min-width:0"><b class="small">${x.name}</b>
          <div class="tiny muted">исполнено ${x.exec_rate}% · в срок ${x.on_time}% · ${x.deals} сделок · доля ${x.share}%</div></span><span class="chip ${x.score >= 80 ? "ok" : ""}">${x.score}</span></div>`)}</div>
      <div class="card pad"><h3>Покупатели</h3>
        <div class="kv"><span>Покупателей за год</span><b class="mono">${nf(d.buyer_size.buyers)}</b></div>
        <div class="kv"><span>Из них малых (до 650 млн сум в год)</span><b class="mono">${nf(d.buyer_size.small)}</b></div>
        <div class="kv"><span>Типичная закупка за год</span><b class="mono">${short(d.buyer_size.median_uzs)} сум</b></div>
        <div class="kv"><span>Новых покупателей по годам</span><b class="mono small">${Object.entries(nb).map(([y, n]) => `${y}: ${n}`).join(" · ")}</b></div>
        <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:12px">
          <button class="btn sm" onClick=${() => askBroker(`Хочу продавать ${d.name} на бирже. Оцени рынок и подскажи, с чего начать.`)}><${Icon} n="sell" s=${15}/> Хочу продавать</button>
          <button class="btn ghost sm" onClick=${() => go("/find?q=" + encodeURIComponent(d.name))}><${Icon} n="buy" s=${15}/> Хочу купить</button>
          ${d.instrument && html`<button class="btn ghost sm" onClick=${() => go("/market/" + d.instrument)}>Торги и котировки</button>`}</div></div>
    </div><${Src}/>
  </div>`;
}

// ------------------------------------------------------------------ My business: the broker that knows the market
export function BusinessScreen() {
  const s = useStore();
  const [demos, setDemos] = useState([]);
  const [inn, setInn] = useState(s.bizInn || s.me?.inn || "");
  const [c, setC] = useState(null), [err, setErr] = useState(""), [mine, setMine] = useState(s.me?.inn || "");
  useEffect(() => { api("/api/insights/demos").then(d => { setDemos(d.demos); if (!inn && d.demos[0]) setInn(d.demos[0].inn); }); }, []);
  useEffect(() => { if (!inn) return; setC(null); setErr(""); set({ bizInn: inn });
    api("/api/insights/company?inn=" + inn).then(setC).catch(e => setErr(e.message)); }, [inn]);
  const saveMine = async () => { try { await api("/api/me/company", { method: "POST", body: { inn: mine } }); setInn(mine.replace(/\D/g, "")); } catch (e) { setErr(e.message); } };
  return html`<div class="grid" style="gap:16px">
    <div><div class="h1">Мой бизнес</div><p class="sub">ИИ-брокер, который знает рынок: ваша доля, где спрос, кому продавать дальше и куда расти. Считается по вашим сделкам на бирже и обобщённым данным рынка.</p></div>
    <div class="card pad"><div class="row" style="flex-wrap:wrap;gap:8px">
      ${demos.map(d => html`<button class="chip ${inn === d.inn ? "on" : ""}" onClick=${() => setInn(d.inn)}>${d.role}: ${d.name}</button>`)}
      ${s.token ? html`<span class="sp"/><input class="inp mono" style="width:140px" placeholder="ИНН компании" value=${mine} onInput=${e => setMine(e.target.value)}/>
        <button class="btn sm" onClick=${saveMine}>Моя компания</button>` : html`<span class="sp"/><button class="btn sm" onClick=${() => go("/start")}>Подключить свою компанию</button>`}
    </div><p class="tiny muted" style="margin:8px 0 0">Демо — реальные компании из реестра. Свою компанию видит только она сама: в боевой версии ИНН подтверждается ключом E-IMZO руководителя.</p></div>
    ${err && html`<div class="card pad err">${err}</div>`}
    ${!c && !err && html`<div class="empty"><span class="spin"/></div>`}
    ${c && !c.found && html`<div class="card pad">Сделок с ИНН ${c.inn} в реестре нет. ИИ-брокер поможет выйти на биржу: <button class="btn sm" onClick=${() => go("/markets")}>Посмотреть рынки</button></div>`}
    ${c?.found && html`<${Company} c=${c}/>`}
  </div>`;
}

function Company({ c }) {
  const r = c.rating, sel = c.seller, buy = c.buyer;
  const main = sel?.markets?.[0];
  return html`<div class="grid" style="gap:16px">
    <div class="card pad"><div class="row" style="gap:16px;flex-wrap:wrap">
      <div class="score"><b class="mono">${r.score}</b><span class="tiny">рейтинг</span></div>
      <div style="flex:1;min-width:200px"><h3 style="margin:0">${c.name}</h3><div class="small muted">ИНН ${c.inn} · на бирже с ${r.since} · ${nf(r.deals)} сделок</div>
        <div class="small" style="margin-top:6px">Исполнено <b>${nf(r.exec_rate, 1)}%</b> сделок (в среднем по бирже ${nf(r.market_exec_rate, 1)}%) · поставка в срок <b>${nf(r.on_time, 1)}%</b></div></div>
      <button class="btn" onClick=${() => askBroker("Посмотри на мои данные на бирже и составь план роста на год: где продавать, что добавить в ассортимент, когда продавать.")}>
        <${Icon} n="agent" s=${16}/> План роста от ИИ-брокера</button></div></div>
    ${sel && html`
      <div class="card pad"><h3>Ваше место на рынке</h3>
        ${sel.markets.map(m => html`<div class="mrow">
          <div style="flex:1;min-width:0"><b>${m.name}</b><div class="tiny muted">место ${m.rank} из ${m.competitors} продавцов · ${m.my_buyers} ваших покупателей из ${nf(m.market_buyers)}</div></div>
          <div class="share"><b class="mono">${nf(m.share, 2)}%</b><span class="tiny muted">рынка${m.share_prev ? ` (год назад ${nf(m.share_prev, 2)}%)` : ""}</span></div></div>`)}
        ${main && html`<div class="insight"><${Icon} n="spark" s=${16}/><span>${main.market_growth > 0 && (main.my_growth ?? 0) < main.market_growth
          ? `Рынок «${main.name}» вырос на ${nf(main.market_growth, 1)}%, а ваши продажи ${main.my_growth >= 0 ? "выросли на " + nf(main.my_growth, 1) + "%" : "упали на " + nf(-main.my_growth, 1) + "%"}. Вы продаёте ${nf(main.share, 1)}% того, что покупают на бирже, — спрос есть, его забирают конкуренты.`
          : `Вы растёте быстрее рынка: ${sgn(main.my_growth)} против ${sgn(main.market_growth)}.`}</span></div>`}
      </div>
      <div class="grid two">
        <div class="card pad"><h3><${Icon} n="users" s=${15}/> Где вас нет, а спрос есть</h3>
          ${sel.gaps.length ? sel.gaps.map(g => html`<div class="lrow"><span style="flex:1"><b class="small">${regionRu(g.region)}</b><div class="tiny muted">${nf(g.buyers)} покупателей</div></span>
            <span class="small"><b class="mono">${g.market_share}%</b> спроса · у вас <b class="mono">${g.my_share}%</b></span></div>`) : html`<p class="small muted">Вы продаёте во всех регионах пропорционально спросу.</p>`}
          ${sel.gaps.length > 0 && html`<p class="small" style="margin:8px 0 0">Агент может выставлять лоты с доставкой в эти регионы и показать их покупателям.</p>`}</div>
        <div class="card pad"><h3><${Icon} n="market" s=${15}/> Куда расти</h3>
          ${sel.ideas.map(i => html`<div class="idea click" onClick=${() => go("/markets/" + i.slug)}><b>${i.name}</b>
            <span class="mono small ${cls(i.growth)}">${sgn(i.growth)}</span><div class="tiny muted" style="width:100%">${i.why}</div></div>`)}
          <p class="tiny muted" style="margin:6px 0 0">Подбор по тому, что ещё покупают ваши же покупатели (можно предложить им вместе с вашим товаром), и по росту рынка.</p></div>
      </div>`}
    ${buy && html`<div class="card pad"><h3><${Icon} n="buy" s=${15}/> Ваши закупки</h3>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Товар</th><th>Куплено</th><th>Ваша цена</th><th>Рынок</th><th>Разница</th><th class="hide-m">Дешевле в</th></tr></thead>
      <tbody>${buy.purchases.map(p => html`<tr class="click" onClick=${() => go("/markets/" + p.slug)}><td><b>${p.name}</b><div class="tiny muted">${p.sellers} продавцов</div></td>
        <td class="mono">${nf(p.qty)} ${unitS(p.unit)}</td><td class="mono">${nf(p.my_price)}</td><td class="mono">${nf(p.market_price)}</td>
        <td class="mono ${p.overpay_pct > 0.5 ? "down" : "up"}">${sgn(p.overpay_pct)}${p.overpay_uzs > 0 ? html`<div class="tiny">${short(p.overpay_uzs)} сум</div>` : ""}</td>
        <td class="small hide-m">${p.cheapest_months.map(m => m.month).join(", ")}</td></tr>`)}</tbody></table></div>
      <p class="tiny muted" style="margin:6px 0 0">Сравнение с медианой рынка в те же месяцы, когда покупали вы.</p></div>`}
    <${Src}/>
  </div>`;
}
