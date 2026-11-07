import { html, render, useState, useEffect, useStore, store, set, api, refreshMe, connectStream, Icon, nf, short, t, tr, setLang, setToken, go, usePoll, pct, insName } from "./lib.js";
import { Onboarding } from "./onboarding.js";
import { AgentScreen } from "./agent.js";
import { MarketScreen } from "./market.js";
import { DealsScreen } from "./deals.js";
import { WalletScreen, ProfileScreen, OpsScreen } from "./screens.js";
import { HomeScreen } from "./home.js";
import { LegalScreen } from "./legal.js";

function useRoute() {
  const [r, setR] = useState(location.hash.slice(1) || "/home");
  useEffect(() => { const f = () => setR(location.hash.slice(1) || "/home"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return r.split("/").filter(Boolean);
}

const NAV = [["home", "home", "Главная"], ["agent", "agent", "Агент"], ["market", "market", "Рынок"], ["deals", "deals", "Сделки"],
  ["legal", "law", "Юрист"], ["wallet", "wallet", "Кошелёк"], ["profile", "profile", "Мой агент"], ["ops", "ops", "Пульт биржи"]];
const TABS = ["home", "agent", "market", "deals", "profile"];

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
  const P = { home: HomeScreen, agent: AgentScreen, market: MarketScreen, deals: DealsScreen, legal: LegalScreen, wallet: WalletScreen, profile: ProfileScreen, ops: OpsScreen }[page] || HomeScreen;
  const props = page === "market" ? { key_: arg } : page === "deals" ? { id: arg } : {};
  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><div class="mk"><svg width="18" height="18" viewBox="0 0 32 32"><path d="M5 23l7-8 6 4 9-12" stroke="#F5B93D" stroke-width="3.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><b>UZEX 2035</b><span>биржа агентов</span></div></div>
      <nav class="nav">${NAV.map(([k, ic, l]) => html`<button class=${page === k || (!page && k === "home") ? "on" : ""} onClick=${() => location.hash = "#/" + k}><${Icon} n=${ic}/>${tr(l)}
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
    <nav class="tabbar">${NAV.filter(x => TABS.includes(x[0])).map(([k, ic, l]) => html`<button class=${page === k ? "on" : ""} onClick=${() => location.hash = "#/" + k}><${Icon} n=${ic} s=${21}/>${tr(l)}${k === "agent" && s.unread > 0 ? html`<span class="badge">${s.unread}</span>` : ""}</button>`)}</nav>
    <${Toasts}/>
  </div>`;
}

function App() {
  const s = useStore();
  const [ready, setReady] = useState(false);
  useEffect(() => { (async () => { if (s.token) { try { await refreshMe(); } catch (e) {} } setReady(true); })(); }, []);
  useEffect(() => { if (s.me?.agent) connectStream(); }, [s.me?.agent]);
  if (!ready) return html`<div class="empty" style="padding-top:30vh"><span class="spin"/></div>`;
  if (location.hash.startsWith("#/ops") && !s.token) return html`<div class="page"><${OpsScreen}/><${Toasts}/></div>`;
  if (!s.token || !s.me?.agent || s.onboarding) return html`<${Onboarding} onDone=${async () => { set({ onboarding: false }); await refreshMe(); location.hash = "#/home"; connectStream(); }}/>`;
  return html`<${Shell}/>`;
}

render(html`<${App}/>`, document.getElementById("app"));
