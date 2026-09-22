function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*'}}
const BASE='https://www.sofascore.com/api/v1';
export async function onRequestGet(context){
  try{
    const seasons=await (await fetch(BASE+'/unique-tournament/13946/seasons',{headers:{'User-Agent':'MatchSignal/PDL-Live'}})).json();
    const current=(seasons.seasons||[])[0];
    if(!current)return new Response(JSON.stringify({ok:false,error:'NO_PDL_SEASON'}),{status:503,headers:headers()});
    const out=[];
    for(const endpoint of ['last','next']){
      const url=BASE+'/unique-tournament/13946/season/'+current.id+'/events/'+endpoint+'/0';
      const r=await fetch(url,{headers:{'User-Agent':'MatchSignal/PDL-Live'}});
      if(!r.ok)continue;
      const body=await r.json();
      for(const e of body.events||[]){
        const t=e.status||{};
        const state=t.type==='inprogress'||t.type==='in_progress'||t.code===6?'in':t.type==='finished'?'post':'pre';
        if(state!=='in')continue;
        const hs=e.homeScore?.current??e.homeScore?.normaltime??0;
        const as=e.awayScore?.current??e.awayScore?.normaltime??0;
        out.push({id:String(e.id),date:e.startTimestamp?new Date(e.startTimestamp*1000).toISOString():null,home:e.homeTeam?.name||'Home',away:e.awayTeam?.name||'Away',home_score:hs,away_score:as,status:{state:'in',description:'In Progress',shortDetail:t.description||'LIVE'},displayClock:t.period1Time??t.period2Time??t.time??null});
      }
    }
    return new Response(JSON.stringify({ok:true,competition:'England Amateur - U21 Professional Development League',events:out}),{headers:headers()});
  }catch(e){return new Response(JSON.stringify({ok:false,error:'PDL_LIVE_PROXY_FAILED',detail:String(e?.message||e)}),{status:502,headers:headers()});}
}