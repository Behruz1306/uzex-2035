import { html, useState, api, store, useStore, nf, sum, short, pct, Icon, usePoll, useNow, countdown, time, Status, tr, nm, go } from "./lib.js";

function IndexCard({ ix }) {
  if (!ix) return null;
  const pts = ix.points.slice(-52).map(p => p.value);
  const mn = Math.min(...pts), mx = Math.max(...pts), w = 180, h = 44;
  const path = pts.map((v, i) => `${i ? "L" : "M"}${(i / (pts.length - 1)) * w},${h - ((v - mn) / (mx - mn || 1)) * (h - 4) - 2}`).join(" ");
  return html`<div class="card pad kpi">
    <div class="small muted">${tr("Индекс UZEX")}</div>
    <div class="row"><b class="mono" style="font-size:24px">${nf(ix.value, 2)}</b><span class="mono small ${ix.change_pct >= 0 ? "up" : "down"}">${pct(ix.change_pct)}</span></div>
    <svg width="100%" height=${h} viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d=${path} fill="none" stroke="var(--agent)" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>
    <div class="tiny muted">8 товаров, реальные котировки, база 100 = январь 2024</div></div>`;
}

export function HomeScreen() {
  const s = useStore();
  const [d, setD] = useState(null);
  const now = useNow();
  usePoll(() => api("/api/home").then(setD), 5000, [s.tick]);
  if (!d) return html`<div class="empty"><span class="spin"/></div>`;
  const me = s.me, agent = me?.agent?.name;
  const todo = [
    ...d.active_deals.filter(x => x.role === "buyer" && x.status === "delivered").map(x => ({ id: x.id, t: `Примите товар: ${nf(x.qty)} т ${nm(x.instrument)}`, s: "Машина на месте. Сфотографируйте весовой талон — агент сверит вес.", ic: "scale", due: x.accept_due })),
    ...d.active_deals.filter(x => x.role === "seller" && x.status === "paid").map(x => ({ id: x.id, t: `Отгрузите: ${nf(x.qty)} т ${nm(x.instrument)}`, s: "Покупатель оплатил, деньги в сейфе биржи. Укажите вес, машину и пломбу.", ic: "truck", due: x.ship_due })),
    ...d.active_deals.filter(x => x.status === "disputed").map(x => ({ id: x.id, t: `Спор по сделке: ${nm(x.instrument)}`, s: "ИИ-арбитр подготовил решение — посмотрите.", ic: "gavel" })),
  ];
  const h = new Date().getHours();
  const hello = h < 12 ? "Доброе утро" : h < 18 ? "Добрый день" : "Добрый вечер";
  return html`<div class="grid" style="gap:16px">
    <div class="hero-home">
      <div><div class="small muted">${hello}, ${me?.name?.split(" ")[0]}</div>
        <div class="h1">${agent} на работе: ${d.mandates.length ? `${d.mandates.length} ${d.mandates.length === 1 ? "поручение" : "поручения"} в работе` : "ждёт ваших поручений"}</div>
        <div class="row" style="flex-wrap:wrap;margin-top:12px">
          <button class="btn pri" onClick=${() => go("/agent")}><${Icon} n="agent"/> Сказать агенту</button>
          <button class="btn" onClick=${() => go("/market/" + (d.interests[0] || "cement"))}><${Icon} n="buy"/> ${tr("Купить")}</button>
          <button class="btn" onClick=${() => go("/market/" + (d.interests[0] || "wheat") + "?sell=1")}><${Icon} n="sell"/> ${tr("Продать")}</button>
          <button class="btn" onClick=${() => go("/market/" + (d.interests[0] || "propane") + "?lock=1")}><${Icon} n="lockp"/> ${tr("Ценовой щит")}</button>
        </div></div>
    </div>
    ${todo.length > 0 && html`<div class="grid">${todo.map(x => html`<button class="todo" onClick=${() => go("/deals/" + x.id)}>
      <span class="ic"><${Icon} n=${x.ic} s=${20}/></span><span style="flex:1;text-align:left"><b>${x.t}</b><span>${x.s}</span></span>
      ${x.due ? html`<span class="mono agentc">${countdown(x.due, now)}</span>` : ""}<${Icon} n="arrow"/></button>`)}</div>`}
    <div class="kpis">
      <div class="card pad kpi"><div class="small muted">${tr("Кошелёк")}</div><b class="mono" style="font-size:24px">${short(d.wallet.wallet)}</b>
        <div class="tiny muted">${d.wallet.blocked ? `${short(d.wallet.blocked)} в задатках · ` : ""}сум</div></div>
      <div class="card pad kpi"><div class="small muted">${tr("Сэкономлено агентом")}</div><b class="mono ${d.saved >= 0 ? "up" : "down"}" style="font-size:24px">${d.saved >= 0 ? "+" : ""}${short(d.saved)}</b>
        <div class="tiny muted">против средней цены сессий того же часа</div></div>
      <div class="card pad kpi"><div class="small muted">Через агента</div><b class="mono" style="font-size:24px">${nf(d.bought_t + d.sold_t)} т</b>
        <div class="tiny muted">куплено ${nf(d.bought_t)} т · продано ${nf(d.sold_t)} т · ${d.deals_total} сделок</div></div>
      <${IndexCard} ix=${d.index}/>
    </div>
    <div class="grid two">
      <div class="card pad"><h3>${tr("Активные сделки")}</h3>
        ${!d.active_deals.length ? html`<p class="muted small">Нет активных сделок. Поручите агенту купить или продать — сделка появится после ближайших торгов.</p>` :
          d.active_deals.map(x => html`<div class="lrow click" onClick=${() => go("/deals/" + x.id)}>
            <span><b>${nf(x.qty)} т ${nm(x.instrument)}</b><span class="tiny muted"> · ${x.role === "buyer" ? "покупка у " + x.seller_info?.name : "продажа " + x.buyer_info?.name}</span></span>
            <span class="sp"/><${Status} s=${x.status}/></div>`)}</div>
      <div class="card pad"><h3>${tr("Ближайшие торги по вашим товарам")}</h3>
        ${d.upcoming.map(x => html`<div class="lrow click" onClick=${() => go("/market/" + x.instrument)}>
          <span class="mono" style="width:56px">${x.status === "open" ? html`<span class="up pulse">идут</span>` : countdown(x.opens_at, now)}</span>
          <span><b>${nm(x.instrument)}</b><span class="tiny muted"> · ${x.seller} · ${nf(x.offered)} т</span></span><span class="sp"/><span class="mono small">${nf(x.start_price)}</span></div>`)}
        <button class="btn ghost sm" style="margin-top:8px" onClick=${() => go("/market")}><${Icon} n="bellplus" s=${15}/> Подписаться на товар</button></div>
    </div>
  </div>`;
}
