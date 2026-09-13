/* Match Signal live model trace + next-match behavior context — PAPER ONLY. */
(function(){'use strict';
const qs=new URLSearchParams(location.search),eventId=qs.get('event_id');
const esc=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML};
const pct=v=>Math.round((Number(v)||0)*1000)/10;
const leagues={EPL:'eng.1','La Liga':'esp.1',Bundesliga:'ger.1',Serie A:'ita.1',Ligue 1:'fra.1',Champions League:'uefa.champions',MLS:'usa.1',Primeira Liga:'por.1',NBA:'nba',WNBA:'wnba',NCAAM:'mens-college-basketball',NCAAW:'womens-college-basketball',Euroleague:'euroleague',ACB:'acb',BBL:'eng.1',BSL:'tur.1'};
async function get(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
function totalMarkup(t){if(!t)return '';const exp=t.expected==null?'—':Number(t.expected).toFixed(2),line=t.line==null?'—':Number(t.line).toFixed(1),lean=t.lean||'Unavailable';const over=t.over_prob==null?'':(' · Over '+pct(t.over_prob)+'%');return '<div class="analysis" style="margin-top:10px"><small style="color:#9eb0d4;text-transform:uppercase">Expected O/U</small><br><b>'+esc(t.market)+' '+esc(line)+'</b> · Expected '+esc(exp)+' · <b>'+esc(lean)+'</b>'+over+'<br><span class="notice">'+esc(t.source||'Model total')+'. Live total is paper-only and not a validated betting edge.</span></div>';}
async function run(){
 try{
  const preds=await get('./data/predictions.json?v='+Date.now());const p=(Array.isArray(preds)?preds:[]).find(x=>String(x.event_id)===String(eventId));if(!p)return;
  let e=null;
  if(p.sport==='football'){
   const s=leagues[p.league];if(s){const d=await get('https://site.api.espn.com/apis/site/v2/sports/soccer/'+s+'/scoreboard');e=(d.events||[]).find(x=>String(x.id)===String(eventId));}
  } else if(p.sport==='basketball'){
   const s=leagues[p.league]||String(p.league||'').toLowerCase().replace(/\s+/g,'.');const d=await get('https://site.api.espn.com/apis/site/v2/sports/basketball/'+s+'/scoreboard');e=(d.events||[]).find(x=>String(x.id)===String(eventId));
  } else if(p.sport==='tennis'){
   for(const t of ['atp','wta']){try{const d=await get('https://site.api.espn.com/apis/site/v2/sports/tennis/'+t+'/scoreboard');for(const g of d.events||[]) for(const z of g.groupings||[]) for(const c of z.competitions||[]) if(String(c.id)===String(eventId)) e={id:eventId,status:c.status,competitions:[c]};if(e)break;}catch(_){} }
  }
  if(!e)return;
  const a=window.MatchSignalLiveAnalysis?.[p.sport]?.(p,e);if(!a)return;
  const key='ms-live-trace:'+eventId,now=Date.now(),prev=JSON.parse(localStorage.getItem(key)||'null');
  const cur={at:now,prob:a.live_probabilities,score:a.score,period:a.period||a.round||'',state:a.state||a.status||''};
  const deltas={};for(const k of Object.keys(a.live_probabilities||{}))deltas[k]=prev?.prob?.[k]!=null?(a.live_probabilities[k]-prev.prob[k]):null;
  localStorage.setItem(key,JSON.stringify(cur));renderTrace(a,deltas,prev);renderLiveCard(a,eventId);await renderBehavior(p);
 }catch(err){console.debug('live trace',err)}
}
function renderTrace(a,d,prev){
 let box=document.getElementById('ms-live-trace');if(!box){box=document.createElement('section');box.id='ms-live-trace';box.className='panel';const anchor=document.getElementById('app')||document.querySelector('.app');if(anchor)anchor.appendChild(box);}
 if(!box)return;
 const rows=Object.entries(a.live_probabilities||{}).map(([k,v])=>{const dlt=d[k];const sign=dlt==null?'':(dlt>=0?'+':'');return '<div class="heroMetric"><small>'+esc(k)+' probability</small><b>'+pct(v)+'% <span style="font-size:11px;color:'+(dlt==null?'#9eb0d4':dlt>=0?'#19e6a2':'#ff4d6d')+'">'+(dlt==null?'first snapshot':sign+pct(dlt)+' pp')+'</span></b></div>'}).join('');
 box.innerHTML='<h2>Live model change trace</h2><div class="heroGrid">'+rows+'</div>'+totalMarkup(a.totals)+'<div class="notice">'+(prev?'Compared with the previous tracker snapshot.':'First tracker snapshot recorded; subsequent refreshes will show probability movement.')+' Current state: <b>'+esc(a.trajectory||'')+'</b></div><div class="paper">PAPER LIVE ANALYSIS — UNVALIDATED</div>';
}
function renderLiveCard(a,id){const cards=[...document.querySelectorAll('.card[href*="event_id="]')];const card=cards.find(x=>decodeURIComponent(x.getAttribute('href')||'').includes('event_id='+id));if(!card)return;let box=card.querySelector('.ms-card-ou');if(!box){box=document.createElement('div');box.className='ms-card-ou';card.appendChild(box);}box.innerHTML=totalMarkup(a.totals);}
async function renderBehavior(p){
 const d=await get('./data/behavior_profiles.json?v='+Date.now()).catch(()=>null);if(!d)return;const teams=d.teams||{};const matches=[];for(const [side,name] of [['p1',p.player_1],['p2',p.player_2]]){const x=teams[(p.league||'global')+'|'+name];if(x)matches.push({side,name,x});}if(!matches.length)return;
 let box=document.getElementById('ms-behavior-context');if(!box){box=document.createElement('section');box.id='ms-behavior-context';box.className='panel';const anchor=document.getElementById('app')||document.querySelector('.app');if(anchor)anchor.appendChild(box);}
 if(!box)return;
 box.innerHTML='<h2>Observed behavior context</h2><div class="notice">Provider-backed historical context available for the next-match analytics layer. It is descriptive and does not alter live probabilities yet.</div><div class="stats">'+matches.map(m=>'<div class="stat"><div class="statName">'+esc(m.side==='p1'?'Home / Player 1':'Away / Player 2')+' · '+esc(m.name)+'</div><div class="statValue">'+esc(m.x.matches)+' matches</div><div class="notice">Win '+pct(m.x.win_rate)+'% · GF '+esc(m.x.avg_goals_for??'—')+' · GA '+esc(m.x.avg_goals_against??'—')+'</div><div class="notice">Shots '+esc(m.x.provider_shots_per_match??'—')+' · SOT '+esc(m.x.provider_sot_per_match??'—')+' · Cards '+esc(m.x.provider_cards_per_match??'—')+'</div></div>').join('')+'</div><div class="notice" style="margin-top:10px">Individual player behavior is only promoted to model features after verified provider athlete identity/statistics are available.</div>';
}
window.addEventListener('load',()=>{run();setInterval(run,15000)});
if(eventId&&!document.getElementById('ms-tracker-fix-loader')){const s=document.createElement('script');s.id='ms-tracker-fix-loader';s.src='./match-tracker-fix.js?v='+Date.now();s.async=true;document.head.appendChild(s);}
})();