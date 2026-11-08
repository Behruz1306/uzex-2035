import { html, render, useState, useEffect, useStore, store, set, api, refreshMe, connectStream, Icon, nf, short, t, tr, setLang, setToken, go, usePoll, pct, insName } from "./lib.js";
import { Onboarding } from "./onboarding.js";
import { AgentScreen } from "./agent.js";
import { MarketScreen } from "./market.js";
import { DealsScreen } from "./deals.js";
import { WalletScreen, ProfileScreen, OpsScreen } from "./screens.js";
import { HomeScreen } from "./home.js";
import { LegalScreen } from "./legal.js";
import { FindScreen, MarketsScreen, BusinessScreen } from "./insights.js";
import { DemoScreen } from "./demo.js";

function useRoute() {
  const [r, setR] = useState(location.hash.slice(1) || "/business");
  useEffect(() => { const f = () => setR(location.hash.slice(1) || "/business"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return r.split("/").filter(Boolean);
}

const NAV = [["demo", "spark", "Демо"], ["business", "home", "Мой бизнес"], ["markets", "market", "Рынки"], ["find", "send", "Найти товар"], ["agent", "agent", "ИИ-брокер"],
  ["market", "calendar", "Торги"], ["deals", "deals", "Сделки"], ["wallet", "wallet", "Кошелёк"], ["profile", "profile", "Профиль"]];
const MORE = [["home", "home", "Сводка агента"], ["legal", "law", "Юрист"], ["ops", "ops", "Пульт биржи"]];
const TABS = ["business", "markets", "find", "agent", "deals"];
const PUBLIC = [["demo", "Демо"], ["find", "Найти товар"], ["markets", "Рынки"], ["business", "Мой бизнес"]];

function PublicShell({ page, arg }) {
  const P = { demo: DemoScreen, find: FindScreen, markets: MarketsScreen, business: BusinessScreen }[page] || FindScreen;
  return html`<div><header class="pub-top">
      <div class="brand" style="padding:0"><div class="mk"><svg width="18" height="18" viewBox="0 0 32 32"><path d="M5 23l7-8 6 4 9-12" stroke="#F5B93D" stroke-width="3.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><b>UZEX</b><span>ИИ-брокер биржи</span></div></div>
      <nav>${PUBLIC.map(([k, l]) => html`<button class=${page === k ? "on" : ""} onClick=${() => go("/" + k)}>${l}</button>`)}</nav>
      <span class="sp"/><button class="btn sm" onClick=${() => go("/start")}>Войти / Начать</button></header>
    <main class="pub-page"><${P} arg=${arg}/></main><${Toasts}/></div>`;
}

function Tape() {
  const s = useStore();
  usePoll(() => api("/api/market").then(d => set({ market: d.instruments })), 15000, []);
  if (!s.market.length) return html`<div class="tape"/>`;
  const items = s.market.map(i => html`<span class="it"><b>${insName(i)}</b><span class="mono">${nf(i.price)}</span> <span class="mono ${i.change_pct >= 0 ? "up" : "down"}">${pct(i.change_pct)}</span></span>`);
  return html`<div class="tape"><div class="tr">${items}${items}</div></div>`;
}

function Toasts() {
  const s = useStore();
  return html`<div class="toastbox">${s.toasts.map(x => html`<div class="toast" onClick=${() => go(x.link)}><b>${x.title}</b><span>${x.body}</span></div>`)}</div>`;
}

function Shell() {
  const s = useStore();
  const [page, arg] = useRoute();
  const [pg, qs] = (page || "business").split("?");
  const P = { home: HomeScreen, agent: AgentScreen, market: MarketScreen, deals: DealsScreen, legal: LegalScreen, wallet: WalletScreen, profile: ProfileScreen, ops: OpsScreen,
    find: FindScreen, markets: MarketsScreen, business: BusinessScreen, demo: DemoScreen }[pg] || BusinessScreen;
  const props = pg === "market" ? { key_: arg } : pg === "deals" ? { id: arg } : pg === "find" ? { arg: qs } : pg === "markets" || pg === "demo" ? { arg } : {};
  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><div class="mk"><svg width="18" height="18" viewBox="0 0 32 32"><path d="M5 23l7-8 6 4 9-12" stroke="#F5B93D" stroke-width="3.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><b>UZEX</b><span>ИИ-брокер биржи</span></div></div>
      <nav class="nav">${[...NAV, ...MORE].map(([k, ic, l], i) => html`${i === NAV.length ? html`<div class="tiny muted" style="padding:14px 10px 4px">Ещё</div>` : ""}<button class=${pg === k ? "on" : ""} onClick=${() => location.hash = "#/" + k}><${Icon} n=${ic}/>${tr(l)}
        ${k === "agent" && s.unread > 0 ? html`<span class="badge">${s.unread}</span>` : ""}</button>`)}</nav>
      <div class="foot">Агент: <b style="color:var(--text)">${s.me?.agent?.name}</b><br/>${s.me?.name}<br/>
        <button class="btn ghost sm" style="padding:4px 0;margin-top:6px" onClick=${() => { setToken(null); location.hash = ""; location.reload(); }}>Выйти</button></div>
    </aside>
    <div class="main">
      <header class="top"><${Tape}/><span class="sp" style="flex:0"/>
        <div class="lang">${["ru", "uz"].map(l => html`<button class=${s.lang === l ? "on" : ""} onClick=${() => setLang(l)}>${l.toUpperCase()}</button>`)}</div>
        <button class="wal" onClick=${() => location.hash = "#/wallet"}><b>${short(s.wallet.wallet)}</b><span>${t("available")}${s.wallet.blocked ? ` · ${short(s.wallet.blocked)} ${t("blocked")}` : ""}</span></button>
        <button class="bell" onClick=${() => location.hash = "#/agent"} aria-label="Уведомления"><${Icon} n="bell"/>${s.unread > 0 && html`<i/>`}</button>
      </header>
      <main class="page"><${P} ...${props}/></main>
    </div>
    <nav class="tabbar">${NAV.filter(x => TABS.includes(x[0])).map(([k, ic, l]) => html`<button class=${pg === k ? "on" : ""} onClick=${() => location.hash = "#/" + k}><${Icon} n=${ic} s=${21}/>${tr(l)}${k === "agent" && s.unread > 0 ? html`<span class="badge">${s.unread}</span>` : ""}</button>`)}</nav>
    <${Toasts}/>
  </div>`;
}

function App() {
  const s = useStore();
  useRoute();
  const [ready, setReady] = useState(false);
  useEffect(() => { (async () => { if (s.token) { try { await refreshMe(); } catch (e) {} } setReady(true); })(); }, []);
  useEffect(() => { if (s.me?.agent) connectStream(); }, [s.me?.agent]);
  if (!ready) return html`<div class="empty" style="padding-top:30vh"><span class="spin"/></div>`;
  const [pp, pa] = location.hash.slice(2).split("/");
  const pubPage = (pp || "").split("?")[0];
  if (!s.token && ["demo", "find", "markets", "business"].includes(pubPage)) return html`<${PublicShell} page=${pubPage} arg=${pubPage === "find" ? (pp.split("?")[1] || "") : pa}/>`;
  if (!s.token || !s.me?.agent || s.onboarding) return html`<${Onboarding} onDone=${async () => { set({ onboarding: false }); await refreshMe(); location.hash = store.pendingAsk ? "#/agent" : "#/business"; connectStream(); }}/>`;
  return html`<${Shell}/>`;
}

render(html`<${App}/>`, document.getElementById("app"));
