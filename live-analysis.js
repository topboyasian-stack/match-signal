/* Match Signal live analysis engine — PAPER ONLY.
 * Uses current ESPN scoreboard state and freezes no live bet. It produces
 * analytical probabilities/trajectory, not an executable betting signal.
 */
(function(){'use strict';
window.MatchSignalLiveAnalysis={
  clamp:function(x,a,b){return Math.max(a,Math.min(b,x));},
  football:function(p,e){
    const c=e&&e.competitions&&e.competitions[0], hs=Number(c&&c.competitors&&c.competitors.find(x=>x.homeAway==='home')?.score||0), as=Number(c&&c.competitors&&c.competitors.find(x=>x.homeAway==='away')?.score||0);
    const period=String(e?.status?.type?.description||'In progress');
    const minute=Number(e?.status?.clock||0)/60; const base=p.probabilities||{};
    let h=Number(base.p1||0), d=Number(base.draw||0), a=Number(base.p2||0);
    const margin=hs-as, late=this.clamp((minute-45)/45,0,1);
    if(margin>0){h+=0.12+0.08*late;d-=0.06;a-=0.06}else if(margin<0){a+=0.12+0.08*late;d-=0.06;h-=0.06}else{h+=0.02; a+=0.02; d-=0.04;}
    const s=h+d+a||1; h/=s;d/=s;a/=s;
    return {sport:'football',score:hs+' - '+as,clock:period,live_probabilities:{home:h,draw:d,away:a},trajectory: h>=d&&h>=a?'Home-favored from current state':a>=d&&a>=h?'Away-favored from current state':'Draw-favored from current state'};
  },
  basketball:function(p,e){
    const c=e&&e.competitions&&e.competitions[0], comps=c?.competitors||[], home=comps.find(x=>x.homeAway==='home'), away=comps.find(x=>x.homeAway==='away');
    const hs=Number(home?.score||0),as=Number(away?.score||0), period=e?.status?.period||0, clock=e?.status?.displayClock||e?.status?.clock||'—';
    const q=[]; comps.forEach(x=>(x.linescores||[]).forEach((l,i)=>{q[i]=q[i]||{};q[i][x.homeAway]=l.displayValue??l.value}));
    const base=p.probabilities||{}, margin=hs-as; let h=Number(base.p1||0.5),a=Number(base.p2||0.5); const adj=this.clamp(margin*0.012,-0.18,0.18);h+=adj;a-=adj;const s=h+a||1;
    return {sport:'basketball',score:hs+' - '+as,period:'Q'+period,clock:String(clock),linescores:q,live_probabilities:{home:h/s,away:a/s},trajectory:margin>0?'Home currently leading':margin<0?'Away currently leading':'Game tied'};
  },
  tennis:function(p,e){
    const c=e&&e.competitions&&e.competitions[0], comps=c?.competitors||[]; const sets=comps.map(x=>({side:x.homeAway,score:x.score||'0',linescores:(x.linescores||[]).map(l=>l.displayValue??l.value)}));
    return {sport:'tennis',score:sets.map(x=>x.score).join(' - '),status:e?.status?.type?.description||'In progress',sets:sets,trajectory:'Live set/match state tracked from current scoreboard'};
  }
};})();
