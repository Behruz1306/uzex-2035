import { html, useState, useEffect, useRef, api, store, useStore, nf, sum, pct, Icon, Spark, usePoll, useNow, countdown, time, insName, Modal, short, tr, nm, toast, go, refreshMe } from "./lib.js";
import { MandateCard } from "./agent.js";

export function MarketScreen({ key_ }) {
  const s = useStore();
  const [list, setList] = useState([]);
  const [k, qs] = (key_ || "cement").split("?");
  usePoll(() => api("/api/market").then(d => setList(d.instruments)), 6000, [s.tick]);
  return html`<div class="mk-layout">
    <div class="card ilist" style="overflow:hidden">
      ${list.map(i => html`<div class="ii ${i.key === k ? "on" : ""}" onClick=${() => location.hash = "#/market/" + i.key}>
        <div><div class="nm">${insName(i)}</div><div class="ns">лот ${i.lot} т · ${i.next ? (i.next.status === "open" ? html`<span class="up pulse">${tr("Идут торги")}</span>` : "торги в " + time(i.next.opens_at).slice(0, 5)) : ""}</div></div>
        <${Spark} data=${i.spark}/>
        <div><div class="pr">${nf(i.price)}</div><div class="ch ${i.change_pct >= 0 ? "up" : "down"}">${pct(i.change_pct)}</div></div>
      </div>`)}
      ${!list.length && html`<div class="empty"><span class="spin"/></div>`}
    </div>
    <${Detail} k=${k} qs=${qs || ""} key=${k}/>
  </div>`;
}

function Chart({ d }) {
  const el = useRef(null);
  useEffect(() => {
    const LW = window.LightweightCharts;
    const c = LW.createChart(el.current, {
      autoSize: true, layout: { background: { color: "transparent" }, textColor: "#7E8BA3", fontFamily: "JetBrains Mono" },
      grid: { vertLines: { color: "rgba(36,50,77,.45)" }, horzLines: { color: "rgba(36,50,77,.45)" } },
      rightPriceScale: { borderColor: "#24324D" }, timeScale: { borderColor: "#24324D" }, crosshair: { mode: 0 },
      localization: { priceFormatter: p => nf(p) },
    });
    const cs = c.addCandlestickSeries({ upColor: "#1FC48A", downColor: "#F2555A", borderVisible: false, wickUpColor: "#1FC48A", wickDownColor: "#F2555A" });
    cs.setData(d.candles.map(x => ({ time: x.time, open: x.open, high: x.high, low: x.low, close: x.close })));
    const last = d.candles[d.candles.length - 1];
    const line = (f, o) => c.addLineSeries({ priceLineVisible: false, lastValueVisible: false, ...o })
      .setData([{ time: last.time, value: last.close }, ...d.forecast.points.map(p => ({ time: p.time, value: p[f] }))]);
    line("price", { color: "#F5B93D", lineWidth: 2, lineStyle: 2 });
    line("low", { color: "rgba(245,185,61,.35)", lineWidth: 1, lineStyle: 1 });
    line("high", { color: "rgba(245,185,61,.35)", lineWidth: 1, lineStyle: 1 });
    c.timeScale().setVisibleLogicalRange({ from: Math.max(0, d.candles.length - 70), to: d.candles.length + 10 });
    return () => c.remove();
  }, [d.key, d.candles.length, d.candles[d.candles.length - 1]?.close]);
  return html`<div class="chart" ref=${el}/>`;
}

function Seasonality({ k }) {
  const [s, setS] = useState(null);
  useEffect(() => { api(`/api/market/${k}/seasonality`).then(setS); }, [k]);
  if (!s) return null;
  const vals = s.months.map(m => m.dev_pct ?? 0), mx = Math.max(...vals.map(Math.abs), 1);
  const cur = new Date().getMonth() + 1;
  return html`<div class="card pad"><h3><${Icon} n="calendar" s=${15}/> ${tr("Когда выгоднее покупать")}</h3>
    <div class="season">${s.months.map(m => html`<div class="sm ${m.month === cur ? "cur" : ""}" title=${`${m.name}: ${m.dev_pct}% к среднему за год`}>
      <div class="bw"><i class=${m.dev_pct < 0 ? "lo" : "hi"} style="height:${Math.abs(m.dev_pct || 0) / mx * 48}%;${m.dev_pct < 0 ? "top:50%" : "bottom:50%"}"/></div>
      <span class="mono tiny ${m.dev_pct < 0 ? "up" : "down"}">${m.dev_pct > 0 ? "+" : ""}${m.dev_pct ?? "—"}</span><span class="tiny muted">${m.name}</span></div>`)}</div>
    <p class="small" style="margin:10px 0 0">Обычно дешевле: <b class="up">${s.cheapest.join(", ")}</b> · дороже: <b class="down">${s.priciest.join(", ")}</b>.
      Сейчас ${s.current_month?.name}: ${s.current_month?.dev_pct > 0 ? "+" : ""}${s.current_month?.dev_pct}% к среднему за год.</p>
    <p class="tiny muted" style="margin:4px 0 0">${s.note} Годы: ${s.years_used.join(", ")}.</p></div>`;
}

function LockModal({ k, d, onClose }) {
  const [qty, setQty] = useState(d.lot * 2); const [weeks, setWeeks] = useState(4);
  const [qt, setQt] = useState(null); const [pin, setPin] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { const t = setTimeout(() => api("/api/forward/quote", { body: { instrument: k, qty, weeks } }).then(setQt).catch(() => {}), 250); return () => clearTimeout(t); }, [qty, weeks]);
  const go_ = async () => { setErr(""); setBusy(true); try { const r = await api("/api/forward/create", { body: { instrument: k, qty, weeks, pin } }); await refreshMe(); onClose(); go("/deals/" + r.deal_id); toast("Цена зафиксирована", `${nf(qty)} т по ${nf(qt.price)} сум/т`); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  return html`<${Modal} onClose=${onClose}>
    <div class="h1" style="font-size:20px"><${Icon} n="lockp"/> ${tr("Ценовой щит")}: ${insName(d)}</div>
    <p class="sub" style="margin-bottom:12px">Зафиксируйте цену сейчас с поставкой позже. Если рынок вырастет, как пропан в сентябре 2026 (+65% за два дня), вы платите зафиксированную цену. Как форварды на CME и UzEx, но в одну кнопку.</p>
    <div class="field"><label>Объём, т (минимум ${d.lot})</label><input class="inp mono" value=${qty} onInput=${e => setQty(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>
    <div class="field"><label>Поставка через ${weeks} нед.</label><input type="range" min="1" max="8" value=${weeks} onInput=${e => setWeeks(+e.target.value)}/></div>
    ${qt && html`<dl class="kv" style="margin-bottom:10px"><dt>Цена фиксации</dt><dd><b>${nf(qt.price)}</b> сум/т</dd>
      <dt>Прогноз на неделю ${qt.delivery_week}</dt><dd>${nf(qt.forecast)} (коридор ${nf(qt.low)}–${nf(qt.high)})</dd>
      <dt>Премия продавца за риск</dt><dd>${qt.premium_pct}%</dd><dt>Сумма</dt><dd>${sum(qty * qt.price)}</dd><dt>Задаток 15%</dt><dd>${sum(qt.deposit)}</dd></dl>
      <p class="tiny muted">${qt.explain}</p>`}
    <div class="row"><input class="inp mono" type="password" maxlength="6" placeholder="PIN" style="width:110px;text-align:center" value=${pin} onInput=${e => setPin(e.target.value.replace(/\D/g, ""))} inputmode="numeric"/>
      <button class="btn pri" disabled=${busy || pin.length < 4 || !qt || qty < d.lot} onClick=${go_}><${Icon} n="check"/> ${tr("Зафиксировать цену")}</button></div>
    ${err && html`<div class="err">${err}</div>`}
  </${Modal}>`;
}

function AlertModal({ k, d, onClose }) {
  const [list, setList] = useState([]); const [kind, setKind] = useState("session"); const [val, setVal] = useState(Math.round(d.recommendation.current * 0.97 / 1000) * 1000);
  const load = () => api("/api/alerts").then(r => setList(r.alerts.filter(a => a.instrument === k)));
  useEffect(load, []);
  const add = async () => { await api("/api/alerts", { body: { instrument: k, kind, value: val } }); toast("Подписка оформлена", kind === "session" ? "Сообщу об анонсе и за минуту до продаж" : "Сообщу при пересечении цены"); load(); };
  const del = async id => { await api("/api/alerts/" + id, { method: "DELETE" }); load(); };
  return html`<${Modal} onClose=${onClose}>
    <div class="h1" style="font-size:20px"><${Icon} n="bellplus"/> ${tr("Подписки")}: ${insName(d)}</div>
    <p class="sub" style="margin-bottom:12px">Продажи идут по графику продавцов. Агент предупредит при анонсе и за минуту до начала, проверит, хватает ли задатка.</p>
    <div class="choice">${[["session", "Анонсы и старт продаж", "«Пропилен откроется в 11:00 — будьте готовы»"], ["below", "Цена опустилась до", "уведомление после клиринга"], ["above", "Цена поднялась до", "уведомление после клиринга"]]
      .map(([kk, b, sub]) => html`<button class=${kind === kk ? "on" : ""} onClick=${() => setKind(kk)}><span><b>${b}</b><span>${sub}</span></span></button>`)}</div>
    ${kind !== "session" && html`<div class="field"><label>Порог, сум/т (сейчас ${nf(d.recommendation.current)})</label><input class="inp mono" value=${nf(val)} onInput=${e => setVal(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>`}
    <button class="btn pri" style="width:100%" onClick=${add}>Подписаться</button>
    ${list.length > 0 && html`<h3 style="margin-top:14px">Ваши подписки</h3>${list.map(a => html`<div class="lrow"><span>${a.kind === "session" ? "Анонсы торгов" : (a.kind === "below" ? "Цена ≤ " : "Цена ≥ ") + nf(a.value)}</span><span class="sp"/>
      ${a.active ? html`<span class="chip ag">активна</span>` : html`<span class="chip ok">сработала</span>`}<button class="btn sm ghost" onClick=${() => del(a.id)}><${Icon} n="x" s=${14}/></button></div>`)}`}
  </${Modal}>`;
}

function Detail({ k, qs }) {
  const s = useStore();
  const [d, setD] = useState(null);
  const [modal, setModal] = useState(qs.includes("sell") ? "sell" : qs.includes("lock") ? "lock" : null);
  const [mand, setMand] = useState(null);
  const now = useNow();
  usePoll(() => api("/api/market/" + k).then(setD), 5000, [k, s.tick]);
  useEffect(() => { if (d && (modal === "buy" || modal === "sell") && !mand) {
    const p = modal === "sell" ? Math.round(d.recommendation.current * 0.98 / 1000) * 1000 : Math.round(d.recommendation.current * 1.04 / 1000) * 1000;
    api("/api/mandates", { body: { side: modal, instrument: k, qty: d.lot * 2, limit_price: p, strategy: "smart", deadline_days: 7 } }).then(setMand).catch(e => { toast("Ошибка", e.message); setModal(null); });
  } }, [d, modal]);
  if (!d) return html`<div class="card pad empty"><span class="spin"/></div>`;
  const r = d.recommendation;
  const live = d.sessions.find(x => x.status === "open"), next = [...d.sessions].reverse().find(x => x.status === "scheduled");
  const done = d.sessions.filter(x => x.status === "cleared").slice(0, 6);
  const last = d.candles[d.candles.length - 1], prev = d.candles[d.candles.length - 2];
  const closeM = () => { setModal(null); setMand(null); };
  return html`<div class="grid">
    <div class="card pad">
      <div class="row" style="flex-wrap:wrap;gap:14px;align-items:flex-start">
        <div><div class="h1" style="font-size:20px">${insName(d)}</div>
          <div class="small muted">${d.anchor ? html`Реальные котировки <a href="https://uzex.uz/Quote/QuotesDynamics" target="_blank" rel="noopener">uzex.uz</a> 2024–2026 + сессии платформы` : "Форма — реестр 2022–2026, уровень — котировка uzex.uz"} · лот ${d.lot} т · задаток ${Math.round(d.deposit * 100)}%${d.key === "propane" ? " · ценовой коридор +10% (Комитет по конкуренции, с 12.01.2026)" : ""}</div></div>
        <span class="sp"/>
        <div style="text-align:right"><div class="mono" style="font-size:24px;font-weight:600">${nf(r.current)} <span class="small muted">сум/т</span></div>
          <div class="mono small ${last.close >= prev.close ? "up" : "down"}">${pct(100 * (last.close - prev.close) / prev.close)} за неделю</div></div>
      </div>
      <div class="actions">
        <button class="btn pri" onClick=${() => setModal("buy")}><${Icon} n="buy"/> ${tr("Купить")}</button>
        <button class="btn" onClick=${() => setModal("sell")}><${Icon} n="sell"/> ${tr("Продать")}</button>
        <button class="btn" onClick=${() => setModal("lock")}><${Icon} n="lockp"/> ${tr("Ценовой щит")}</button>
        <button class="btn" onClick=${() => setModal("alert")}><${Icon} n="bellplus"/> ${tr("Сообщить о торгах")}</button>
      </div>
      <${Chart} d=${d}/>
      <div class="legend"><span><i style="background:#1FC48A"/>Недельные свечи</span><span><i style="background:#F5B93D"/>Прогноз на 8 недель</span><span><i style="background:rgba(245,185,61,.4)"/>Коридор ошибки</span><span>${d.forecast.accuracy_note}</span></div>
    </div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
      <div class="rec ${r.action === "wait" ? "wait" : "buy"}">
        <div class="small muted">${tr("Рекомендация агента")} · уверенность ${r.confidence}</div>
        <div class="big ${r.action === "wait" ? "agentc" : "up"}">${r.action === "wait" ? tr("Подождать") : tr("Покупать сейчас")}</div>
        <div class="small">Прогноз: ${nf(r.target_price)} сум/т к неделе ${r.target_week} (${r.expected_change_pct > 0 ? "+" : ""}${r.expected_change_pct}%)</div>
        <ul>${r.reasons.map(x => html`<li>${x}</li>`)}</ul>
        <p class="tiny muted" style="margin:8px 0 0">${r.disclaimer}</p>
      </div>
      <div class="card pad">
        ${live ? html`<h3><span class="up pulse">●</span> ${tr("Идут торги")} · ${live.seller_name}</h3>
          <div class="row"><div><div class="count">${countdown(live.closes_at, now)}</div><div class="tiny muted">до клиринга</div></div><span class="sp"/>
            <div style="text-align:right"><b class="mono">${nf(live.offered)} т</b><div class="tiny muted">старт ${nf(live.start_price)}</div></div></div>
          <div class="book" style="margin-top:10px">${(live.book || []).map(([p, q]) => html`<div class="bl"><i style="width:${Math.min(100, 100 * q / live.offered)}%"/><span>${nf(p)}</span><span>${nf(q)} т</span></div>`)}
            ${!(live.book || []).length && html`<span class="muted small">Заявки собираются…</span>`}</div>
          ${live.pools > 0 && html`<p class="small agentc" style="margin:8px 0 0"><${Icon} n="users" s=${14}/> Участвует общий лот мелких покупателей</p>`}`
        : next ? html`<h3><${Icon} n="clock" s=${15}/> ${tr("Следующая сессия")}</h3>
          <div class="count">${countdown(next.opens_at, now)}</div>
          <div class="small">${next.seller_name} выставит <b>${nf(next.offered)} т</b> · старт ${nf(next.start_price)} сум/т</div>
          <div class="tiny muted" style="margin-top:4px">Агенты с поручениями по этому товару уже готовят задатки.</div>` : html`<span class="muted">Нет запланированных сессий</span>`}
      </div>
    </div>
    <${Seasonality} k=${k}/>
    <div class="card pad" style="overflow-x:auto"><h3>${tr("Как сложилась цена — последние сессии")}</h3>
      ${!done.length ? html`<p class="muted small">Первая сессия по этому товару скоро начнётся.</p>` : html`
      <table class="tbl"><thead><tr><th>Время</th><th>Продавец</th><th class="num">Товар</th><th class="num">Спрос</th><th class="num">Старт</th><th class="num">Цена</th><th>Почему</th></tr></thead>
      <tbody>${done.map(x => html`<tr><td class="mono">${time(x.closes_at).slice(0, 5)}</td><td class="small">${x.seller_name}</td><td class="num">${nf(x.offered)} т</td><td class="num">${nf(x.demand)} т</td>
        <td class="num">${nf(x.start_price)}</td><td class="num"><b>${nf(x.clearing_price)}</b></td>
        <td class="small muted">${x.explain ? `${x.explain.bidders} покуп.${x.explain.sellers > 1 ? `, ${x.explain.sellers} продавц.` : ""}${x.explain.pools ? ", общий лот" : ""}; ${x.explain.capped ? "упёрлись в коридор +10% — распределение по времени" : x.clearing_price > x.start_price ? (x.demand > x.offered ? "спрос выше предложения" : "покупатели дали выше старта") : "спроса меньше, чем товара, — цена на старте"}` : ""}</td></tr>`)}</tbody></table>
      <p class="tiny muted" style="margin:8px 0 0">Единая цена клиринга: все покупатели сессии платят одну цену — ту, при которой продаётся наибольший объём.</p>`}
    </div>
    ${(modal === "buy" || modal === "sell") && html`<${Modal} onClose=${closeM}>${mand ? html`<${MandateCard} c=${mand} onDone=${() => setTimeout(closeM, 900)}/>` : html`<div class="empty"><span class="spin"/></div>`}</${Modal}>`}
    ${modal === "lock" && html`<${LockModal} k=${k} d=${d} onClose=${closeM}/>`}
    ${modal === "alert" && html`<${AlertModal} k=${k} d=${d} onClose=${closeM}/>`}
  </div>`;
}

export function CalendarCard() {
  const s = useStore(); const now = useNow();
  const [rows, setRows] = useState([]);
  usePoll(() => api("/api/calendar").then(d => setRows(d.sessions)), 7000, [s.tick]);
  return html`<div class="card pad"><h3><${Icon} n="calendar" s=${15}/> ${tr("Календарь торгов")}</h3>
    <table class="tbl"><tbody>${rows.slice(0, 8).map(r => html`<tr class="click" onClick=${() => location.hash = "#/market/" + r.instrument}>
      <td class="mono">${r.status === "open" ? html`<span class="up pulse">идёт</span>` : countdown(r.opens_at, now)}</td><td>${nm(r.instrument)}</td><td class="small muted">${r.seller}</td><td class="num">${nf(r.offered)} т</td></tr>`)}</tbody></table></div>`;
}
