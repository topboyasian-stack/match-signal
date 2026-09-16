"""Research-only comparison with public event-market data. No orders are created."""
import json,re
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/"data";BASE="https://external-api.kalshi.com/trade-api/v2"
S=requests.Session();S.headers.update({"User-Agent":"MatchSignal/market-research-v2"})
def load(n,d):
    try:
        with open(DATA/n,encoding="utf-8") as f:return json.load(f)
    except (FileNotFoundError,json.JSONDecodeError):return d
def save(n,v):
    with open(DATA/n,"w",encoding="utf-8") as f:json.dump(v,f,indent=2,ensure_ascii=False)
def norm(s):return re.sub(r"[^a-z0-9 ]+"," ",str(s).lower()).strip()
def sim(a,b):
    aa,bb=set(norm(a).split()),set(norm(b).split());return len(aa&bb)/max(1,len(aa|bb))
def participant_score(name,title):
    a=norm(name);b=norm(title)
    if not a:return 0
    if a in b:return 1.0
    return sim(a,b)
def main():
    preds=load("predictions.json",[])
    out={"version":"event-market-research-v2","updated_at":datetime.now(timezone.utc).isoformat(),"status":"PAPER_RESEARCH_ONLY","kalshi":{"status":"NOT_QUERIED","matches":[],"errors":[],"comparison_count":0},"webull":{"status":"AUTH_REQUIRED_NOT_CONNECTED","reason":"Webull event-contract API requires authenticated account/app setup and sports agreement; credentials are intentionally not stored in Git."},"execution":"DISABLED","matching_policy":"Require both participants to match the same market title; exclude multivariate cross-category markets; never infer a market from one participant alone."}
    try:
        r=S.get(BASE+"/markets",params={"status":"open","limit":1000},timeout=20);r.raise_for_status();markets=r.json().get("markets",[]);out["kalshi"]["status"]="PUBLIC_MARKET_DATA_READ"
        for p in preds:
            if p.get("sport") not in {"football","tennis"}:continue
            a,b=p.get("player_1",""),p.get("player_2","");best=None
            for m in markets:
                ticker=str(m.get("ticker") or "")
                if "KXMVECROSSCATEGORY" in ticker:continue
                title=m.get("title") or m.get("subtitle") or "";sa,sb=participant_score(a,title),participant_score(b,title)
                if sa>=.70 and sb>=.70:
                    score=(sa+sb)/2
                    if best is None or score>best[0]:best=(score,m,sa,sb)
            if best:
                m=best[1];val=m.get("yes_bid_dollars") or m.get("yes_ask_dollars") or m.get("last_price_dollars")
                try:val=float(val)
                except (TypeError,ValueError):val=None
                if val is not None and 0<val<1:
                    out["kalshi"]["matches"].append({"event_id":p.get("event_id"),"sport":p.get("sport"),"model_probability":(p.get("probabilities") or {}).get(p.get("pick")),"market_ticker":m.get("ticker"),"market_title":m.get("title"),"market_probability_reference":val,"match_score":round(best[0],3),"participant_scores":[round(best[2],3),round(best[3],3)],"execution":"DISABLED"})
    except Exception as e:
        out["kalshi"]["status"]="PUBLIC_MARKET_DATA_UNAVAILABLE";out["kalshi"]["errors"].append(str(e))
    out["kalshi"]["comparison_count"]=len(out["kalshi"]["matches"]);save("market_research.json",out);print(f"Market research: {out['kalshi']['comparison_count']} high-confidence comparisons")
if __name__=="__main__":main()
