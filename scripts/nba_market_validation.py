"""Research-only NBA closing-market benchmark.

Downloads the public Kaggle MGM Grand NBA closing-line dataset and joins it to
our independently generated NBA walk-forward predictions. This is a benchmark
only: market prices are never fed into the independent model.
"""
import io, json, math, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
URL = 'https://www.kaggle.com/api/v1/datasets/download/caseydurfee/mgm-grand-nba-betting-data'
NOW = datetime.now(timezone.utc)


def american_to_prob(x):
    try:
        x = float(x)
        if x == 0 or math.isnan(x):
            return None
        return 100.0 / (x + 100.0) if x > 0 else (-x) / ((-x) + 100.0)
    except Exception:
        return None


def norm_team(x):
    s = re.sub(r'[^a-z0-9]', '', str(x).lower())
    aliases = {
        'lalakers':'losangeleslakers', 'lacippers':'losangelesclippers',
        'nyknicks':'newyorkknicks', 'gswarriors':'goldenstatewarriors',
        'okcthunder':'oklahomacitythunder', 'phxsuns':'phoenixsuns',
        'sas':'sanantoniospurs', 'sa':'sanantoniospurs', 'utahjazz':'utahjazz',
        'nopelicans':'neworleanspelicans', 'ny':'newyorkknicks',
    }
    return aliases.get(s, s)


def load_dataset():
    r = requests.get(URL, timeout=120, headers={'User-Agent':'MatchSignal/1.0'})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    candidates = [n for n in z.namelist() if n.lower().endswith('.csv')]
    if not candidates:
        raise RuntimeError('Kaggle archive contained no CSV files')
    chosen = None
    for n in candidates:
        try:
            head = pd.read_csv(z.open(n), nrows=5)
            cols = {str(c).strip().lower() for c in head.columns}
            if {'game_date','away_team','home_team'} <= cols and 'money_home_odds' in cols:
                chosen = n; break
        except Exception:
            continue
    if not chosen:
        raise RuntimeError(f'No compatible MGM CSV found; files={candidates}')
    df = pd.read_csv(z.open(chosen))
    df.columns = [str(c).strip() for c in df.columns]
    return df, chosen


def load_model_rows():
    p = DATA / 'nba_history.json'
    if not p.exists():
        raise RuntimeError('data/nba_history.json missing')
    return json.loads(p.read_text())


def model_probability(r, hist):
    from expansion_pipeline import nba_predict
    p = nba_predict(r, hist).get('moneyline', {})
    return float(p.get('home', .5)), float(p.get('away', .5))


def main():
    hist = load_model_rows()
    market, source_file = load_dataset()
    market['date_key'] = pd.to_datetime(market['game_date'], errors='coerce').dt.date.astype(str)
    market['home_key'] = market['home_team'].map(norm_team)
    market['away_key'] = market['away_team'].map(norm_team)
    idx = {}
    for _, r in market.iterrows():
        k = (r['date_key'], r['home_key'], r['away_key'])
        idx[k] = r

    rows = []
    for r in hist:
        d = str(r['date'])[:10]
        k = (d, norm_team(r['home']), norm_team(r['away']))
        m = idx.get(k)
        if m is None:
            continue
        hp = american_to_prob(m.get('money_home_odds'))
        ap = american_to_prob(m.get('money_away_odds'))
        if hp is None or ap is None:
            continue
        total = hp + ap
        if total <= 0:
            continue
        # Remove vig by normalizing the two implied probabilities.
        mh, ma = hp/total, ap/total
        rows.append({'event_id':r['event_id'],'date':r['date'],'home':r['home'],'away':r['away'],
                     'home_score':r['home_score'],'away_score':r['away_score'],
                     'market_home_prob':mh,'market_away_prob':ma,
                     'home_ml':m.get('money_home_odds'),'away_ml':m.get('money_away_odds')})

    # Recompute independent predictions with a strict pre-game cutoff.
    by_id = {r['event_id']:r for r in hist}
    evaluated=[]
    for r in rows:
        source = by_id[r['event_id']]
        hp, ap = model_probability(source, hist)
        actual_home = float(source['home_score']) > float(source['away_score'])
        model_pick = 'home' if hp >= ap else 'away'
        market_pick = 'home' if r['market_home_prob'] >= r['market_away_prob'] else 'away'
        # Fair-odds EV for a $1 stake at the recorded closing ML.
        ml = float(r['home_ml'] if model_pick == 'home' else r['away_ml'])
        if ml > 0: dec = 1 + ml/100
        else: dec = 1 + 100/(-ml)
        p_model = hp if model_pick == 'home' else ap
        ev = p_model * (dec-1) - (1-p_model)
        profit = (dec-1) if ((model_pick == 'home') == actual_home) else -1
        evaluated.append({**r,'model_home_prob':hp,'model_away_prob':ap,
                          'model_pick':model_pick,'market_pick':market_pick,
                          'model_correct':((model_pick=='home')==actual_home),
                          'market_correct':((market_pick=='home')==actual_home),
                          'model_edge_vs_market':p_model-(r['market_home_prob'] if model_pick=='home' else r['market_away_prob']),
                          'closing_ev':ev,'unit_profit':profit})

    def avg(key): return round(sum(float(x[key]) for x in evaluated)/len(evaluated),4) if evaluated else None
    model_acc=sum(x['model_correct'] for x in evaluated)/len(evaluated) if evaluated else None
    market_acc=sum(x['market_correct'] for x in evaluated)/len(evaluated) if evaluated else None
    positive=[x for x in evaluated if x['closing_ev'] > 0.025]
    pos_profit=sum(x['unit_profit'] for x in positive) if positive else 0
    pos_roi=(pos_profit/len(positive)) if positive else None
    payload={'generated_at':NOW.isoformat(),'paper_only':True,'source':'Kaggle MGM Grand NBA betting data','source_file':source_file,
             'market_definition':'closing moneyline; vig-normalized implied probability; one-book benchmark',
             'coverage':{'model_history_events':len(hist),'market_rows':len(market),'matched_games':len(evaluated),'coverage_rate':round(len(evaluated)/len(hist),4) if hist else 0},
             'model_vs_market':{'model_accuracy':round(model_acc,4) if model_acc is not None else None,'market_accuracy':round(market_acc,4) if market_acc is not None else None,
                                'mean_model_edge':avg('model_edge_vs_market'),'mean_closing_ev':avg('closing_ev'),
                                'positive_ev_threshold':0.025,'positive_ev_games':len(positive),'positive_ev_roi':round(pos_roi,4) if pos_roi is not None else None},
             'release_decision':'RESEARCH_ONLY',
             'reason':'Market coverage is a closing-line benchmark, not proof of tradable edge; promotion still requires calibration, positive out-of-sample value and sufficient contemporaneous coverage.'}
    (DATA/'nba_market_validation.json').write_text(json.dumps(payload,indent=2))
    (DATA/'nba_market_matches.json').write_text(json.dumps(evaluated,indent=2))
    print(json.dumps(payload,indent=2))

if __name__=='__main__': main()
