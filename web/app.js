/* Hamiz Pulse app. Ported from reference/index.html; data now comes from the Pulse API. */
(function(){
"use strict";
const C=window.PulseCalc;
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=(n,d=0)=>n==null||!isFinite(n)?"–":Number(n).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d});
const da=n=>{if(n==null||!isFinite(n))return"–";const a=Math.abs(n);if(a>=1e6)return fmt(n/1e6,a>=1e7?1:2)+"M DA";if(a>=1e4)return fmt(n/1e3,0)+"k DA";return fmt(n)+" DA"};
const pct=(n,d=1)=>n==null||!isFinite(n)?"–":(n*100).toFixed(d)+"%";
const usd=(n,d=2)=>n==null||!isFinite(n)?"–":"$"+fmt(n,d);
const store={get(k,f){try{const v=localStorage.getItem("hp."+k);return v==null?f:JSON.parse(v)}catch(e){return f}},set(k,v){try{localStorage.setItem("hp."+k,JSON.stringify(v))}catch(e){}}};

const TABS={sales:[["overview","Overview"],["trend","Trend"],["sellers","Sellers"],["products","Products"],["channels","Channels"],["orders","Orders"]],
            ads:[["budget","CAC budget"],["plan","Scaling plan"],["review","Ad review"]]};
const STAGES=[["pending","Pending"],["confirmed","Confirmed"],["delivered","Delivered"],["returned","Returned"],["cancelled","Cancelled"]];
const STAGE_PILL={pending:"p-idle",confirmed:"p-info",delivered:"p-good",returned:"p-warn",cancelled:"p-bad"};
const DECISION_PILL={promote:"p-good",kill:"p-bad",wait:"p-idle",fix:"p-info"};

const S={section:store.get("section","sales"),tab:store.get("tab",{sales:"overview",ads:"budget"}),
  data:{summary:null,sellers:null,products:null,orders:null},sync:null,net:"wait",
  period:store.get("period","last7"),trend:{days:30,metric:"o"},lists:{sellers:{q:"",sort:"gmv",n:25},products:{q:"",sort:"revenue",n:25}},
  orders:{q:"",stage:"all",n:40},
  ads:Object.assign({aov:null,cr:null,dr:null,fx:250,cac:5,basis:"raw",low:200,high:250,cpm:"0.5,1,1.5,2",ctr:"1.5,2.5,4",
    creatives:6,testBudget:18,minSpend:3,scaleStart:20,step:20,calls:500,stock:6000,remit:10,gap:2},store.get("ads",{})),
  review:{mode:store.get("reviewMode","live"),window:store.get("reviewWindow","today"),live:{},loading:false,
    meta:store.get("metaCsv",""),orders:store.get("ordersCsv","")}};
if(!TABS[S.section])S.section="sales";

/* ---------------- data ---------------- */
function meta(){return S.data.summary&&S.data.summary.meta}
async function api(path){
  const r=await fetch(path,{credentials:"same-origin",headers:{Accept:"application/json"}});
  if(r.status===401){location.href="/login";throw new Error("login required")}
  if(!r.ok)throw new Error("HTTP "+r.status);
  return r.json();
}
function ageText(mins){return mins==null?"":mins<1?"just now":mins<60?mins+" min ago":mins<1440?Math.round(mins/60)+" h ago":Math.round(mins/1440)+" d ago"}
function ageMinutes(){const m=meta();return m?Math.max(0,Math.round((Date.now()-new Date(m.generated_at))/6e4)):null}
function setSync(){
  const dot=$("#syncDot"),t=$("#syncText"),sy=S.sync,m=meta(),mins=ageMinutes();
  if(S.net==="off"&&!m){dot.className="dot off";t.textContent="Can't load data";return}
  if(!m){dot.className="dot";t.textContent=S.net==="wait"?"Connecting…":"Waiting for first sync";return}
  const stale=sy?mins>sy.stale_after_minutes:mins>150,failed=sy&&sy.odoo&&sy.odoo.last&&sy.odoo.last.ok===false;
  if(m.example){dot.className="dot ex";t.textContent="Example data";return}
  if(failed){dot.className="dot off";t.textContent="Last sync failed";return}
  dot.className="dot "+(stale||S.net==="off"?"off":"live");
  t.textContent="Odoo · "+ageText(mins);
}
async function loadReports(){
  try{const d=await api("/api/reports");["summary","sellers","products","orders"].forEach(k=>S.data[k]=d[k]||null);S.sync=d.sync;S.net="ok"}
  catch(e){S.net="off"}
  setSync();render();
}
async function pollStatus(){
  try{const s=await api("/api/status");const changed=!S.sync||s.generated_at!==S.sync.generated_at;S.sync=s;S.net="ok";
    if(changed)return loadReports();if(S.section==="ads"&&S.tab.ads==="review"&&S.review.mode==="live"){S.review.live={};loadAds()}}
  catch(e){S.net="off"}
  setSync();
}
async function loadAds(){
  const w=S.review.window;if(S.review.loading===w)return;S.review.loading=w;
  try{S.review.live[w]=await api("/api/ads?window="+w)}catch(e){S.review.live[w]={error:e.message}}
  S.review.loading=false;
  if(S.section==="ads"&&S.tab.ads==="review")rerenderKeep(null);
}

/* ---------------- shell ---------------- */
function renderTabs(){
  $("#secSales").setAttribute("aria-pressed",S.section==="sales");
  $("#secAds").setAttribute("aria-pressed",S.section==="ads");
  $("#tabs").innerHTML=TABS[S.section].map(([id,l])=>`<button role="tab" data-tab="${id}" aria-selected="${S.tab[S.section]===id}">${l}</button>`).join("");
}
function banners(){
  const m=meta(),sy=S.sync,mins=ageMinutes();let h="";
  if(S.net==="off")h+=`<div class="banner bad"><b>Can't reach the Pulse server.</b> ${m?"Showing the last data loaded on this phone.":"Check your connection and pull to refresh."}</div>`;
  if(m&&m.example)h+=`<div class="banner"><b>Example data.</b> These are made-up orders so you can see every tab. They are replaced by your real Odoo numbers on the first sync.</div>`;
  else if(sy&&sy.odoo&&sy.odoo.last&&sy.odoo.last.ok===false)h+=`<div class="banner bad"><b>Last sync failed</b> ${esc(ageText(_ago(sy.odoo.last.finished_at)))}. Showing the last good data from ${esc(ageText(mins))}.${sy.odoo.last.error?`<br><span class="hint">${esc(sy.odoo.last.error)}</span>`:""}</div>`;
  else if(m&&sy&&mins>sy.stale_after_minutes)h+=`<div class="banner warn"><b>Data is ${esc(ageText(mins))}.</b> The hourly sync has not run since then.</div>`;
  return h;
}
function _ago(iso){return iso?Math.max(0,Math.round((Date.now()-new Date(iso))/6e4)):null}
function render(){
  renderTabs();
  const t=S.tab[S.section],main=$("#main");
  let h=banners();
  const fn={overview,trend,sellers:()=>ranked("sellers"),products:()=>ranked("products"),channels,orders,budget,plan,review}[t]||overview;
  try{h+=fn()}catch(e){h+=`<section class="card"><p class="hint">This tab could not render: ${esc(e.message)}</p></section>`}
  const m=meta();
  h+=`<div class="foot">${m?`<span>Odoo data from ${esc(m.generated_at.replace("T"," ").slice(0,16))} Algiers</span>`:""}<button data-logout="1">Sign out</button></div>`;
  main.innerHTML=h;
  bind();
}
function noData(k){return !S.data[k]?`<section class="card"><div class="empty">${S.net==="off"?"Live Odoo data shows here once the server is reachable.":S.net==="wait"?"Loading…":"Waiting for the first Odoo sync. Data appears automatically."}</div></section>`:null}

/* ---------------- sales: overview ---------------- */
const PERIODS=[["today","Today","yesterday","vs yesterday"],["yesterday","Yesterday",null,null],["last7","7 days","prev7","vs prior 7 days"],["last30","30 days","prev30","vs prior 30 days"]];
function delta(cur,prev,inverse){
  if(prev==null||!prev)return`<span class="d flat">no comparison</span>`;
  const ch=(cur-prev)/Math.abs(prev);if(!isFinite(ch))return"";
  const good=inverse?ch<0:ch>0,cls=Math.abs(ch)<.005?"flat":good?"up":"down";
  return`<span class="d ${cls}">${ch>0?"▲":ch<0?"▼":"■"} ${Math.abs(ch*100).toFixed(1)}%</span>`;
}
function overview(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary,p=PERIODS.find(x=>x[0]===S.period)||PERIODS[2],k=s.kpis[p[0]],pv=p[2]?s.kpis[p[2]]:null;
  const ppdRate=s.kpis.last7.orders_per_day,low=+S.ads.low,high=+S.ads.high,scaleMax=Math.max(high*1.2,ppdRate*1.1);
  const st=k.stages||{},tot=k.orders||1;
  let h=`<div class="chips" role="group" aria-label="Period">${PERIODS.map(x=>`<button class="chip" data-period="${x[0]}" aria-pressed="${x[0]===p[0]}">${x[1]}</button>`).join("")}</div>`;
  h+=`<div class="kpis">
    ${kpi("Orders",fmt(k.orders),pv&&delta(k.orders,pv.orders))}
    ${kpi("GMV",da(k.gmv),pv&&delta(k.gmv,pv.gmv))}
    ${kpi("Avg order value",da(k.aov),pv&&delta(k.aov,pv.aov))}
    ${kpi("Cancel rate",pct(k.cancel_rate),pv&&delta(k.cancel_rate,pv.cancel_rate,true))}
    ${kpi("Net GMV (excl. cancelled)",da(k.net_gmv),pv&&delta(k.net_gmv,pv.net_gmv))}
    ${kpi("Orders per day",fmt(k.orders_per_day,1),pv&&delta(k.orders_per_day,pv.orders_per_day))}
  </div>`;
  if(pv)h+=`<p class="hint" style="margin-top:-4px">Changes are ${p[3]}.</p>`;
  h+=`<section class="card"><h2>Daily orders goal <small>${low}–${high} placed/day</small></h2>
    <div class="gauge"><div class="row2"><span><span class="big">${fmt(ppdRate,1)}</span> / day, last 7 days</span><span class="pill ${ppdRate>=low?"p-good":ppdRate>=low*.6?"p-warn":"p-bad"}">${ppdRate>=low?"On target":fmt(low-ppdRate,0)+" short"}</span></div>
    <div class="track"><i class="fill" style="width:${Math.min(100,ppdRate/scaleMax*100)}%"></i><i class="band" style="left:${low/scaleMax*100}%;width:${(high-low)/scaleMax*100}%"></i></div>
    <div class="row2"><span>0</span><span>Target band ${low}–${high}</span><span>${fmt(scaleMax,0)}</span></div></div></section>`;
  h+=`<section class="card"><h2>Order status <small>${fmt(k.orders)} orders</small></h2>
    <div class="stack">${STAGES.map(([id])=>`<i class="s-${id}" style="width:${(st[id]||0)/tot*100}%"></i>`).join("")}</div>
    <div class="legend">${STAGES.map(([id,l])=>`<span><i class="s-${id}"></i>${l} <b class="num">${fmt(st[id]||0)}</b></span>`).join("")}</div>
    <div class="stats">
      <div class="stat"><div class="l">Confirmed</div><div class="v">${pct(k.confirm_rate,0)}</div><div class="u">of resolved orders</div></div>
      <div class="stat"><div class="l">Delivered</div><div class="v">${pct(k.delivery_rate,0)}</div><div class="u">of shipped parcels</div></div>
      <div class="stat"><div class="l">Lost value</div><div class="v">${pct(k.cancel_rate_value,0)}</div><div class="u">GMV cancelled</div></div>
    </div></section>`;
  h+=`<section class="card"><h2>When orders arrive <small>last 30 days, Algiers time</small></h2>${hourChart(s.hours)}<p class="hint">Use the peak hours to plan ad budget and confirmation-call shifts.</p></section>`;
  return h;
}
function kpi(l,v,d){return`<div class="kpi"><span class="l">${l}</span><span class="v">${v}</span>${d||'<span class="d flat">&nbsp;</span>'}</div>`}
function hourChart(hours){
  const W=340,H=120,max=Math.max(1,...hours),bw=W/24;
  let b="";hours.forEach((v,i)=>{const h=v/max*(H-22);b+=`<rect x="${i*bw+1.5}" y="${H-16-h}" width="${bw-3}" height="${h}" rx="2" fill="var(--accent)" opacity="${v===max?1:.55}"><title>${i}:00 · ${v} orders</title></rect>`});
  [0,6,12,18,23].forEach(i=>b+=`<text x="${i*bw+bw/2}" y="${H-3}" text-anchor="middle">${i}h</text>`);
  const peak=hours.indexOf(Math.max(...hours));
  return`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Orders by hour, peak at ${peak}:00">${b}</svg>`;
}

/* ---------------- sales: trend ---------------- */
function trend(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary,days=s.daily.slice(-S.trend.days),M=S.trend.metric;
  const W=360,H=190,pad=34,cw=W-pad-6,ch=H-38,bw=cw/days.length;
  const val=d=>M==="o"?d.o:d.g,cval=d=>M==="o"?d.c:d.cg;
  const max=Math.max(1,...days.map(val),M==="o"?+S.ads.low:0),nice=niceMax(max);
  let g="";
  [0,.5,1].forEach(f=>{const y=10+ch-ch*f;g+=`<line x1="${pad}" x2="${W-6}" y1="${y}" y2="${y}" stroke="var(--line)"/><text x="${pad-5}" y="${y+3}" text-anchor="end">${M==="o"?fmt(nice*f):da(nice*f).replace(" DA","")}</text>`});
  days.forEach((d,i)=>{const v=val(d),c=cval(d),hv=v/nice*ch,hc=c/nice*ch,x=pad+i*bw;
    g+=`<rect x="${x+bw*.12}" y="${10+ch-hv}" width="${bw*.76}" height="${hv}" fill="var(--accent)" opacity=".8"><title>${d.date} · ${M==="o"?fmt(v)+" orders":da(v)}</title></rect>`;
    if(hc>0)g+=`<rect x="${x+bw*.12}" y="${10+ch-hc}" width="${bw*.76}" height="${hc}" fill="var(--bad)"/>`;});
  const step=Math.ceil(days.length/5);
  days.forEach((d,i)=>{if(i%step===0||i===days.length-1)g+=`<text x="${pad+i*bw+bw/2}" y="${H-8}" text-anchor="middle">${d.date.slice(5)}</text>`});
  if(M==="o"){const lo=+S.ads.low;if(lo<=nice){const y=10+ch-lo/nice*ch;g+=`<line x1="${pad}" x2="${W-6}" y1="${y}" y2="${y}" stroke="var(--good)" stroke-dasharray="4 3"/><text x="${W-8}" y="${y-4}" text-anchor="end" style="fill:var(--good)">${lo}/day goal</text>`}}
  const tot=days.reduce((a,d)=>a+val(d),0),canc=days.reduce((a,d)=>a+cval(d),0);
  let h=`<div class="chips">${[[7,"7 days"],[30,"30 days"],[90,"90 days"]].map(([n,l])=>`<button class="chip" data-tdays="${n}" aria-pressed="${S.trend.days===n}">${l}</button>`).join("")}
    <span style="flex:1"></span>${[["o","Orders"],["g","GMV"]].map(([m,l])=>`<button class="chip" data-tmetric="${m}" aria-pressed="${M===m}">${l}</button>`).join("")}</div>`;
  h+=`<section class="card"><h2>${M==="o"?"Orders per day":"GMV per day"} <small>red = cancelled</small></h2>
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily trend">${g}</svg>
    <div class="stats"><div class="stat"><div class="l">Total</div><div class="v">${M==="o"?fmt(tot):da(tot)}</div></div>
    <div class="stat"><div class="l">Daily avg</div><div class="v">${M==="o"?fmt(tot/days.length,1):da(tot/days.length)}</div></div>
    <div class="stat"><div class="l">Cancelled</div><div class="v">${pct(tot?canc/tot:0,0)}</div></div></div></section>`;
  h+=`<section class="card"><h2>Busy hours by weekday <small>last 30 days</small></h2>${heat(s.weekday_hours)}</section>`;
  return h;
}
function niceMax(v){const p=Math.pow(10,Math.floor(Math.log10(v)));return Math.ceil(v/p*2)/2*p}
function heat(m){
  const days=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],W=360,cw=(W-34)/24,chh=15,H=7*chh+18,max=Math.max(1,...m.flat());
  let g="";m.forEach((row,d)=>{g+=`<text x="0" y="${d*chh+11}">${days[d]}</text>`;row.forEach((v,hh)=>{g+=`<rect x="${34+hh*cw}" y="${d*chh}" width="${cw-1.5}" height="${chh-2}" rx="2" fill="var(--accent)" opacity="${v?(.08+.92*v/max).toFixed(2):.04}"><title>${days[d]} ${hh}:00 · ${v}</title></rect>`})});
  [0,6,12,18,23].forEach(hh=>g+=`<text x="${34+hh*cw+cw/2}" y="${H-2}" text-anchor="middle">${hh}h</text>`);
  return`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Orders by weekday and hour">${g}</svg>`;
}

/* ---------------- sales: ranked lists ---------------- */
const cancelPill=c=>`<span class="pill ${c>.3?"p-bad":c>.15?"p-warn":"p-good"}">${pct(c,0)} cancel</span>`;
function ranked(kind){
  const e=noData(kind);if(e)return e;
  const doc=S.data[kind],L=S.lists[kind],isP=kind==="products";
  const sorts=isP?[["revenue","Revenue"],["qty","Units"],["cancel","Cancel %"]]:[["gmv","GMV"],["orders","Orders"],["cancel","Cancel %"]];
  let rows=doc.rows.filter(r=>!L.q||String(r.name).toLowerCase().includes(L.q.toLowerCase()));
  const cr=r=>r.orders?r.cancelled/r.orders:0,key=L.sort==="cancel"?cr:r=>r[L.sort];
  rows=rows.slice().sort((a,b)=>key(b)-key(a)||(b.orders-a.orders));
  const total=doc.rows.reduce((a,r)=>a+(isP?r.revenue:r.gmv),0),top=Math.max(1,...rows.map(r=>isP?r.revenue:r.gmv));
  let h=`<div class="search"><input id="q_${kind}" type="search" placeholder="Search ${kind}" value="${esc(L.q)}" aria-label="Search ${kind}">
    <select id="s_${kind}" aria-label="Sort">${sorts.map(([v,l])=>`<option value="${v}" ${L.sort===v?"selected":""}>${l}</option>`).join("")}</select></div>`;
  h+=`<section class="card"><h2>${isP?"Products":"Sellers"} <small>last 30 days · ${fmt(doc.rows.length)}${doc.meta&&doc.meta.trimmed?"+":""}</small></h2><div class="list">`;
  rows.slice(0,L.n).forEach(r=>{const v=isP?r.revenue:r.gmv,c=cr(r);
    h+=`<div class="item"><span class="n">${esc(r.name)}</span><span class="r">${da(v)}</span>
      <span class="s">${fmt(r.orders)} orders${isP?" · "+fmt(r.qty)+" units":""} · ${pct(total?v/total:0,1)} share</span>
      <span class="s" style="text-align:right">${cancelPill(c)}</span>
      <span class="share"><i style="width:${v/top*100}%"></i></span></div>`});
  if(!rows.length)h+=`<div class="empty">No match.</div>`;
  h+=`</div>${rows.length>L.n?`<button class="more" data-more="${kind}">Show ${Math.min(25,rows.length-L.n)} more</button>`:""}`;
  if(!isP&&doc.meta)h+=`<p class="hint">Seller value is based on ${esc(doc.meta.seller_basis)}.</p>`;
  if(doc.meta&&doc.meta.trimmed)h+=`<p class="hint">List trimmed to fit the size limit; the smallest ${kind} are left out.</p>`;
  return h+`</section>`;
}

/* ---------------- sales: channels ---------------- */
function channels(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary;
  const block=(title,rows,note)=>{if(!rows||!rows.length)return"";const tot=rows.reduce((a,r)=>a+r.gmv,0),top=Math.max(1,...rows.map(r=>r.gmv));
    return`<section class="card"><h2>${title} <small>last 30 days</small></h2><div class="list">${rows.slice(0,12).map(r=>{const c=r.orders?r.cancelled/r.orders:0;
      return`<div class="item"><span class="n">${esc(r.name)}</span><span class="r">${da(r.gmv)}</span><span class="s">${fmt(r.orders)} orders · ${pct(tot?r.gmv/tot:0,0)} share · ${pct(r.orders?r.delivered/r.orders:0,0)} delivered</span><span class="s" style="text-align:right">${cancelPill(c)}</span><span class="share"><i style="width:${r.gmv/top*100}%"></i></span></div>`}).join("")}</div>${note?`<p class="hint">${note}</p>`:""}</section>`};
  return block("Stores",s.stores)+block("Ad source / campaign",s.utm,"From the UTM source and campaign Odoo records on each order. Orders with no UTM show as Unknown.")+block("Wilayas",s.wilayas)+block("Salespeople",s.salespeople)||`<section class="card"><div class="empty">No channel fields found in Odoo yet.</div></section>`;
}

/* ---------------- sales: orders ---------------- */
function orders(){
  const e=noData("orders");if(e)return e;
  const O=S.orders,q=O.q.toLowerCase();
  let rows=S.data.orders.rows.filter(r=>(O.stage==="all"||r.st===O.stage)&&(!q||[r.ref,r.mg,r.cu,r.se,r.so].some(x=>x&&String(x).toLowerCase().includes(q))));
  let h=`<div class="search"><input id="q_orders" type="search" placeholder="Order, Magento ID, customer, seller, store" value="${esc(O.q)}" aria-label="Search orders"></div>
    <div class="chips">${[["all","All"],...STAGES].map(([id,l])=>`<button class="chip" data-stage="${id}" aria-pressed="${O.stage===id}">${l}</button>`).join("")}</div>`;
  h+=`<section class="card"><h2>Latest orders <small>${fmt(rows.length)} shown of last ${fmt(S.data.orders.rows.length)}</small></h2><div class="list">`;
  rows.slice(0,O.n).forEach(r=>{h+=`<div class="ord"><span class="a">${esc(r.ref)}${r.mg?` <span style="color:var(--muted);font-weight:500">#${esc(r.mg)}</span>`:""}</span><span class="t">${da(r.t)}</span>
    <span class="c">${esc(r.dt)} · ${esc(r.cu||"Guest")}${r.se?" · "+esc(r.se):""}</span><span style="text-align:right"><span class="pill ${STAGE_PILL[r.st]}" title="${esc(r.raw||"")}">${esc((STAGES.find(x=>x[0]===r.st)||[0,r.st])[1])}</span></span></div>`});
  if(!rows.length)h+=`<div class="empty">No orders match.</div>`;
  h+=`</div>${rows.length>O.n?`<button class="more" data-more="orders">Show 40 more</button>`:""}</section>`;
  return h;
}

/* ---------------- ads math ---------------- */
function live(){const k=S.data.summary&&S.data.summary.kpis&&S.data.summary.kpis.last30;return k||null}
function odooDefaults(){const k=live();return{aov:k&&k.aov?k.aov:4500,cr:k&&k.confirm_rate!=null?+(k.confirm_rate*100).toFixed(0):70,dr:k&&k.delivery_rate!=null?+(k.delivery_rate*100).toFixed(0):75}}
function adsInputs(){
  const A=S.ads,D=odooDefaults();
  const aov=+(A.aov??D.aov)||4500,cr=(+(A.cr??D.cr))/100,dr=(+(A.dr??D.dr))/100;
  return{aov,c:Math.min(1,Math.max(.01,cr||.7)),d:Math.min(1,Math.max(.01,dr||.75)),fx:+A.fx||250,cac:(+A.cac||5)/100,basis:A.basis,low:+A.low||200,high:+A.high||250};
}
const LBL={raw:"placed",confirmed:"confirmed",delivered:"delivered"};
function field(id,label,val,opts){const src=opts&&opts.src;return`<label for="${id}">${label}${src?` <span class="src">${src}</span>`:""}
  ${opts&&opts.select?`<select id="${id}" data-ads="${id}">${opts.select.map(([v,l])=>`<option value="${v}" ${String(val)===v?"selected":""}>${l}</option>`).join("")}</select>`
  :`<input id="${id}" data-ads="${id}" inputmode="decimal" value="${esc(val)}">`}</label>`}

function budget(){
  const I=adsInputs(),k=live(),A=S.ads,D=odooDefaults();
  const B=C.cacBudget(I),perConf=B.perConf,perDeliv=B.perDeliv,perRaw=B.perRaw;
  const src=k&&!(meta()&&meta().example)?"from Odoo":k?"example":null;
  let h=`<section class="card"><h2>Your numbers <small>edit any value</small></h2><div class="form">
    ${field("aov","Avg order value (DA)",A.aov??D.aov,{src:A.aov==null&&src})}
    ${field("fx","DA paid per $1 of ads",A.fx)}
    ${field("cr","Confirmation rate %",A.cr??D.cr,{src:A.cr==null&&src})}
    ${field("dr","Delivery rate %",A.dr??D.dr,{src:A.dr==null&&src})}
    ${field("cac","CAC cap % of order value",A.cac)}
    ${field("basis","CAC counted per",A.basis,{select:[["raw","Order placed"],["confirmed","Order confirmed"],["delivered","Order delivered"]]})}
    ${field("low","Goal low (orders/day)",A.low)}
    ${field("high","Goal high (orders/day)",A.high)}
  </div>${A.aov!=null||A.cr!=null||A.dr!=null?`<button class="btn ghost" data-reset="1">Use Odoo values again</button>`:""}</section>`;
  h+=`<section class="card"><h2>Max ad cost allowed</h2><div class="stats">
    <div class="stat"><div class="l">Per placed</div><div class="v">${usd(perRaw/I.fx)}</div><div class="u">${fmt(perRaw)} DA</div></div>
    <div class="stat"><div class="l">Per confirmed</div><div class="v">${usd(perConf/I.fx)}</div><div class="u">${fmt(perConf)} DA</div></div>
    <div class="stat"><div class="l">Per delivered</div><div class="v">${usd(perDeliv/I.fx)}</div><div class="u">${fmt(perDeliv)} DA</div></div></div>
    ${I.basis!=="delivered"?`<p class="hint">Real cost per delivered order: ${fmt(perDeliv)} DA, or ${pct(perDeliv/I.aov)} of order value.</p>`:""}</section>`;
  h+=`<section class="card"><h2>Daily ad budget at your goal</h2><div class="list">${B.daily.map(v=>`<div class="item"><span class="n">${fmt(v.placed)} placed/day</span><span class="r">${usd(v.spend/I.fx,0)}/day</span><span class="s">~${fmt(v.conf)} confirmed · ~${fmt(v.deliv)} delivered · ${da(v.spend)}</span></div>`).join("")}</div>`;
  if(k)h+=`<p class="hint">Right now: ${fmt(k.orders_per_day,1)} orders/day over the last 30 days.</p>`;
  h+=`</section>`;
  const raw=perRaw/I.fx,cpms=String(A.cpm).split(",").map(Number).filter(x=>x>0),ctrs=String(A.ctr).split(",").map(Number).filter(x=>x>0);
  h+=`<section class="card"><h2>Landing conversion needed <small>Meta CPA ≤ ${usd(raw)}</small></h2>
    <div class="form">${field("cpm","CPM values ($)",A.cpm)}${field("ctr","Link CTR values (%)",A.ctr)}</div>
    <div class="scroll"><table><thead><tr><th>CPM</th>${ctrs.map(t=>`<th>CTR ${t}%</th>`).join("")}</tr></thead><tbody>${cpms.map(m=>`<tr><td>$${fmt(m,2)}</td>${ctrs.map(t=>{const need=C.landingNeeded(m,t,raw);return`<td class="${need<=.05?"ok":need<=.1?"mid":"no"}">${need>1?"impossible":pct(need)}</td>`}).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="hint">Share of link clicks that must place an order. Green is comfortable, amber is hard, red needs a higher order value or cheaper traffic.</p></section>`;
  return h;
}

function plan(){
  const I=adsInputs(),A=S.ads,cpa=C.capConfUsd(I.cac,I.aov,I.fx,I.basis,I.c,I.d);
  const hiD=C.toDeliv(I.high,"raw",I.c,I.d),hiSpend=hiD/I.d*cpa,calls=+A.calls||0,capD=calls*I.c*I.d;
  let ceiling=hiSpend;if(calls)ceiling=Math.min(ceiling,calls*I.c*cpa);
  const top=Math.max(ceiling-(+A.testBudget||0),+A.scaleStart||20);
  let h=`<section class="card"><h2>Test & scale settings</h2><div class="form">
    ${field("creatives","Creatives to test",A.creatives)}${field("testBudget","Test budget $/day",A.testBudget)}
    ${field("minSpend","Min spend per ad set $",A.minSpend)}${field("scaleStart","Scaling start $/day",A.scaleStart)}
    ${field("step","Budget step %",A.step)}${field("calls","Confirmation calls/day",A.calls)}
    ${field("stock","Units in stock",A.stock)}${field("remit","Days until COD cash",A.remit)}
  </div></section>`;
  const need=(+A.creatives)*(+A.minSpend),per=Math.max(1,Math.floor((+A.testBudget)/(+A.minSpend)));
  h+=`<section class="card"><h2>Rules for each ad</h2>
    <div class="verdict">Target cost per confirmed order: <b>${usd(cpa)}</b> (${pct(I.cac,0)} of ${fmt(I.aov)} DA per ${LBL[I.basis]} order)</div>
    <div class="list">
      <div class="item"><span class="n">Testing campaign</span><span class="r">${need<=+A.testBudget?`<span class="pill p-good">OK</span>`:`<span class="pill p-warn">Waves</span>`}</span><span class="s">${need<=+A.testBudget?`${esc(A.creatives)} ad sets × $${esc(A.minSpend)} = $${fmt(need)}/day fits the budget`:`$${fmt(need)} of minimums exceeds $${esc(A.testBudget)}. Raise the budget to $${fmt(need)}/day or test ${per} at a time.`}</span></div>
      <div class="item"><span class="n">Promote</span><span class="r"><span class="pill p-good">≤ ${usd(cpa)}</span></span><span class="s">cost per confirmed order, with 3+ confirmed, after 3 full days</span></div>
      <div class="item"><span class="n">Kill</span><span class="r"><span class="pill p-bad">&gt; ${usd(cpa*1.5)}</span></span><span class="s">or ${usd(cpa*2.5)} spent with no confirmed order, or under ${pct(Math.max(0,I.c-.2),0)} confirmation with 10+ resolved orders (junk orders)</span></div>
    </div></section>`;
  h+=`<section class="card"><h2>Capacity check <small>at ${fmt(I.high)} placed/day</small></h2><div class="list">
    <div class="item"><span class="n">Ad spend needed</span><span class="r">${usd(hiSpend,0)}/day</span><span class="s">${da(hiSpend*I.fx)}</span></div>
    <div class="item"><span class="n">Confirmation calls</span><span class="r"><span class="pill ${!calls||capD>=hiD-.5?"p-good":"p-bad"}">${!calls?"not set":capD>=hiD-.5?"OK":"Too few"}</span></span><span class="s">need ~${fmt(I.high)} calls/day plus retries; you have ${fmt(calls)}</span></div>
    <div class="item"><span class="n">Stock</span><span class="r">${fmt((+A.stock)/(hiD/I.d),0)} days</span><span class="s">${fmt(A.stock)} units at ~${fmt(hiD/I.d)} shipped/day</span></div>
    <div class="item"><span class="n">Cash to float ads</span><span class="r">${usd(hiSpend*(+A.remit),0)}</span><span class="s">${esc(A.remit)} days of spend before COD cash returns · ${da(hiSpend*(+A.remit)*I.fx)}</span></div></div></section>`;
  const gap=+A.gap||2;let bud=+A.scaleStart||20,day=1,step=0;const rows=[];
  while(true){rows.push({step,day,budget:bud});if(bud>=top||step>80)break;bud=Math.min(bud*(1+(+A.step||20)/100),top);step++;day+=gap}
  h+=`<section class="card"><h2>Scaling schedule <small>step only if the last 3 days hold the cap</small></h2>
    <div class="chips"><button class="chip" data-gap="2" aria-pressed="${gap===2}">Every 48h</button><button class="chip" data-gap="1" aria-pressed="${gap===1}">Every 24h</button></div>
    <div class="scroll"><table><thead><tr><th>Day</th><th>Budget</th><th>Placed</th><th>Confirmed</th><th>Delivered</th></tr></thead><tbody>
    ${rows.map(r=>{const conf=r.budget/cpa;return`<tr><td>${r.day}</td><td>${usd(r.budget,0)}</td><td>${fmt(conf/I.c)}</td><td>${fmt(conf)}</td><td>${fmt(conf*I.d)}</td></tr>`}).join("")}</tbody></table></div>
    <p class="hint">Reaches the top level around day ${day} (~${(day/7).toFixed(1)} weeks). Assumes cost per order holds as spend grows; it usually rises, and the cap wins.</p></section>`;
  return h;
}

/* ---------------- ads review ---------------- */
const WINDOWS=[["today","Today"],["yesterday","Yesterday"],["last7","Last 7 days"]];
function review(){
  const I=adsInputs(),R=S.review;
  let h=`<div class="chips" role="group" aria-label="Source"><button class="chip" data-rmode="live" aria-pressed="${R.mode==="live"}">Live from Meta</button><button class="chip" data-rmode="upload" aria-pressed="${R.mode==="upload"}">Upload CSV</button></div>`;
  return h+(R.mode==="live"?reviewLive(I):reviewUpload(I));
}
function reviewLive(I){
  const R=S.review,d=R.live[R.window];
  let h=`<div class="chips" role="group" aria-label="Day">${WINDOWS.map(([w,l])=>`<button class="chip" data-rwin="${w}" aria-pressed="${R.window===w}">${l}</button>`).join("")}</div>`;
  if(!d){if(!R.loading)setTimeout(loadAds,0);return h+`<section class="card"><div class="empty">Loading Meta spend…</div></section>`}
  if(d.error)return h+`<section class="card"><div class="empty">Could not load Meta spend (${esc(d.error)}). Use Upload CSV meanwhile.</div></section>`;
  const ms=d.sync&&d.sync.meta,last=ms&&ms.last;
  let note=last?`Meta synced ${esc(ageText(_ago(last.finished_at)))}${last.ok===false?` · <b style="color:var(--bad)">last Meta sync failed</b>`:""}`:"Meta has not synced yet";
  if(!d.has_spend&&!d.has_orders)return h+`<section class="card"><div class="empty">No Meta spend or attributed orders for ${esc(d.start)}${d.end!==d.start?" to "+esc(d.end):""}.<br><span class="hint">${note}</span></div></section>`;
  const res=C.review(d.spend,d.groups,I,d.days_running);
  h+=account(res,I,`${esc(d.start)}${d.end!==d.start?" → "+esc(d.end):""}`);
  h+=adList(res,true);
  h+=`<p class="hint">${note}. Orders are joined on utm_content = ad name${d.other_channels?`; ${fmt(d.other_channels)} orders from other channels are left out`:""}. Kills for CAC or no orders wait until an ad has run 3 full days.</p>`;
  return h;
}
function reviewUpload(I){
  const R=S.review;
  let h=`<section class="card"><h2>Load the data</h2>
    <label class="file">Meta Ads export (CSV with ad name and amount spent)<input type="file" id="fMeta" accept=".csv,text/csv"></label>
    <label class="file">Orders per ad (optional CSV: ad_name, status, value)<input type="file" id="fOrd" accept=".csv,text/csv"></label>
    <p class="hint">Without an orders file, ads are matched to Odoo orders by campaign name (UTM). Files stay on this phone.</p>
    ${R.meta?`<button class="btn ghost" data-clear="1">Clear loaded files</button>`:""}</section>`;
  if(!R.meta)return h+`<section class="card"><div class="empty">Load a Meta export to score each ad against the ${pct(I.cac,0)} CAC cap.</div></section>`;
  const spend=C.spendFromCsv(R.meta);let groups={};
  if(R.orders)groups=C.groupsFromCsv(R.orders);
  else if(S.data.summary){const utm=S.data.summary.utm||[];Object.keys(spend).forEach(n=>{const m=utm.filter(u=>u.name.toLowerCase().includes(n.toLowerCase())||n.toLowerCase().includes((u.name.split(" / ").pop()||"").toLowerCase()));
      if(m.length){const g=groups[n]=C.newGroup();g.approx=true;m.forEach(u=>{g.raw+=u.orders;g.conf+=u.confirmed;g.deliv+=u.delivered;g.val.push(u.gmv/u.orders)})}})}
  const res=C.review(spend,groups,I,null);
  h+=account(res,I,"uploaded files");
  h+=adList(res,false);
  h+=`<p class="hint">The upload can't see how long each ad has run. Don't kill anything before 3 full days unless it's clearly broken.</p>`;
  return h;
}
function account(res,I,label){
  const a=res.account;
  return`<section class="card"><h2>Account <small>${label}</small></h2><div class="stats">
    <div class="stat"><div class="l">Spend</div><div class="v">${usd(a.spAll,0)}</div><div class="u">${da(a.spAll*I.fx)}</div></div>
    <div class="stat"><div class="l">Orders</div><div class="v">${fmt(a.rawAll)}</div><div class="u">${fmt(a.confAll)} confirmed</div></div>
    <div class="stat"><div class="l">CAC</div><div class="v" style="color:var(${a.ok?"--good":"--bad"})">${isFinite(a.blended)?pct(a.blended):"–"}</div><div class="u">${a.ok?"OK":"OVER CAP"} · cap ${pct(I.cac,0)}/${LBL[I.basis]}</div></div></div>
    ${a.perDelivPct!=null&&I.basis!=="delivered"?`<p class="hint">Projected cost per delivered order: ${pct(a.perDelivPct)} of order value (information only).</p>`:""}</section>`;
}
function adList(res,liveMode){
  return`<section class="card"><h2>Ads <small>best CAC first</small></h2><div class="list">${res.rows.map(r=>`<div class="item"><span class="n">${esc(r.n)}</span><span class="r">${isFinite(r.cac)?pct(r.cac):"–"}</span>
    <span class="s">${usd(r.sp)} · ${fmt(r.g.raw)} placed · ${fmt(r.g.conf)} conf (${pct(r.rate,0)}) · AOV ${da(r.aov)}${r.g.approx?" · matched by campaign":""}${liveMode&&r.days!=null?` · ${r.days} full day${r.days===1?"":"s"}`:""}</span><span></span>
    <span class="s" style="grid-column:1/-1"><span class="pill ${DECISION_PILL[r.code]}">${esc(r.label)}</span></span></div>`).join("")||`<div class="empty">No ads in this window.</div>`}</div></section>`;
}

/* ---------------- events ---------------- */
function bind(){
  document.querySelectorAll("[data-period]").forEach(b=>b.onclick=()=>{S.period=b.dataset.period;store.set("period",S.period);render()});
  document.querySelectorAll("[data-tdays]").forEach(b=>b.onclick=()=>{S.trend.days=+b.dataset.tdays;render()});
  document.querySelectorAll("[data-tmetric]").forEach(b=>b.onclick=()=>{S.trend.metric=b.dataset.tmetric;render()});
  document.querySelectorAll("[data-stage]").forEach(b=>b.onclick=()=>{S.orders.stage=b.dataset.stage;S.orders.n=40;render()});
  document.querySelectorAll("[data-more]").forEach(b=>b.onclick=()=>{const k=b.dataset.more;if(k==="orders")S.orders.n+=40;else S.lists[k].n+=25;rerenderKeep(null)});
  document.querySelectorAll("[data-gap]").forEach(b=>b.onclick=()=>{S.ads.gap=+b.dataset.gap;saveAds();rerenderKeep(null)});
  document.querySelectorAll("[data-rmode]").forEach(b=>b.onclick=()=>{S.review.mode=b.dataset.rmode;store.set("reviewMode",S.review.mode);render()});
  document.querySelectorAll("[data-rwin]").forEach(b=>b.onclick=()=>{S.review.window=b.dataset.rwin;store.set("reviewWindow",S.review.window);render()});
  ["sellers","products"].forEach(k=>{const q=$("#q_"+k),s=$("#s_"+k);
    if(q)q.oninput=()=>{S.lists[k].q=q.value;S.lists[k].n=25;rerenderKeep("q_"+k)};
    if(s)s.onchange=()=>{S.lists[k].sort=s.value;render()}});
  const qo=$("#q_orders");if(qo)qo.oninput=()=>{S.orders.q=qo.value;S.orders.n=40;rerenderKeep("q_orders")};
  document.querySelectorAll("[data-ads]").forEach(el=>el.onchange=()=>{const k=el.dataset.ads;S.ads[k]=el.tagName==="SELECT"||k==="cpm"||k==="ctr"?el.value:(el.value===""?null:el.value);saveAds();rerenderKeep(null)});
  const r=$("[data-reset]");if(r)r.onclick=()=>{S.ads.aov=S.ads.cr=S.ads.dr=null;saveAds();render()};
  const fm=$("#fMeta"),fo=$("#fOrd");
  if(fm)fm.onchange=()=>readFile(fm,"meta");if(fo)fo.onchange=()=>readFile(fo,"orders");
  const cl=$("[data-clear]");if(cl)cl.onclick=()=>{S.review.meta="";S.review.orders="";store.set("metaCsv","");store.set("ordersCsv","");render()};
  const lo=$("[data-logout]");if(lo)lo.onclick=async()=>{try{await fetch("/auth/logout",{method:"POST",credentials:"same-origin"})}catch(e){}
    try{if(window.caches)for(const k of await caches.keys())await caches.delete(k)}catch(e){}location.href="/login"};
}
function readFile(input,key){const f=input.files&&input.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{S.review[key]=String(rd.result);store.set(key==="meta"?"metaCsv":"ordersCsv",S.review[key].length<400000?S.review[key]:"");render()};rd.readAsText(f)}
function saveAds(){const {aov,cr,dr,fx,cac,basis,low,high,cpm,ctr,creatives,testBudget,minSpend,scaleStart,step,calls,stock,remit,gap}=S.ads;store.set("ads",{aov,cr,dr,fx,cac,basis,low,high,cpm,ctr,creatives,testBudget,minSpend,scaleStart,step,calls,stock,remit,gap})}
function rerenderKeep(id){const y=window.scrollY,el=id&&$("#"+id),pos=el?el.selectionStart:null;render();if(id){const n=$("#"+id);if(n){n.focus();try{n.setSelectionRange(pos,pos)}catch(e){}}}window.scrollTo(0,y)}

$("#secSales").onclick=()=>{S.section="sales";store.set("section","sales");render();window.scrollTo(0,0)};
$("#secAds").onclick=()=>{S.section="ads";store.set("section","ads");render();window.scrollTo(0,0)};
$("#tabs").onclick=e=>{const b=e.target.closest("[data-tab]");if(!b)return;S.tab[S.section]=b.dataset.tab;store.set("tab",S.tab);render();window.scrollTo(0,0)};
setInterval(setSync,60000);
setInterval(pollStatus,5*60000);
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")pollStatus()});
if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
render();loadReports();
})();
