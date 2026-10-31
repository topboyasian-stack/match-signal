"""Live-experimental NBA + Eredivisie pipeline.

Keeps the independent model separate from market prices while allowing the
current-season competitions to generate real, timestamped experimental signals.
The outputs are explicitly LIVE_EXPERIMENTAL, never live-trading approved.
"""
import csv, hashlib, io, json, math, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

from expansion_pipeline import collect, current, nba_predict, NBA_START, NBA_TOTALS_MODEL_VERSION, NOW
from independent_football_model import independent_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
NBA_TOTAL_SNAPSHOTS = DATA / "nba_totals_publication_snapshots.json"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (compatible; MatchSignal/1.0)"})


def sportybet_basketball_feed():
    """Read SportyBet Nigeria pre-match NBA markets through the existing regional proxy."""
    url = "https://match-signal.pages.dev/api/sportybet-basketball"
    try:
        response = S.get(url, params={"pageSize": 100, "timeline": 96}, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok") is not True:
            return [], f"SportyBet source response failed: {payload.get('error') or 'ok flag was not true'}"
        if not isinstance(payload.get("events"), list):
            return [], "SportyBet source response omitted the events array"
        events = payload["events"]
        if not events:
            return [], "SportyBet source returned zero upcoming basketball events"
        return events, None
    except Exception as exc:
        return [], f"SportyBet feed unavailable: {exc}"


def nba_team_key(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(la) ", "los angeles ", text)
    text = re.sub(r"^(ny) ", "new york ", text)
    return text


def sportybet_total_for_fixture(fixture, feed, expected_total=None):
    """Select an exact-fixture, fresh market-225 line with both observed prices."""
    fixture_home = nba_team_key(fixture.get("home"))
    fixture_away = nba_team_key(fixture.get("away"))
    fixture_start = dt(fixture.get("date"))
    if not fixture_home or not fixture_away or not fixture_start:
        return None
    now = datetime.now(timezone.utc)
    candidates = []
    for event in feed or []:
        event_home = nba_team_key(event.get("home"))
        event_away = nba_team_key(event.get("away"))
        if not ((fixture_home == event_home and fixture_away == event_away) or
                (fixture_home == event_away and fixture_away == event_home)):
            continue
        event_start = dt(event.get("start_time"))
        if not event_start or abs((event_start - fixture_start).total_seconds()) > 45 * 60:
            continue
        fetched_at = dt(event.get("fetched_at"))
        if not fetched_at or fetched_at > now + timedelta(minutes=2) or now - fetched_at > timedelta(minutes=15):
            continue
        for market in event.get("markets") or []:
            if str(market.get("id")) != "225":
                continue
            market_status = str(market.get("status") or "").strip().lower()
            if re.search(r"suspend|closed|inactive|settled|unavailable|stop", market_status):
                continue
            if market_status.isdigit() and market_status != "0":
                continue
            specifier = str(market.get("specifier") or "")
            match = re.search(r"(?:^|[,;|&\s])(?:total|line)\s*=\s*(\d+(?:\.\d+)?)(?=$|[,;|&\s])", specifier, re.I)
            if match:
                line = float(match.group(1))
            else:
                try:
                    line = float(market.get("line"))
                except (TypeError, ValueError):
                    continue
            if not 100 <= line <= 300:
                continue
            outcomes = market.get("outcomes") or []
            over = next((o for o in outcomes if re.search(r"\bover\b", str(o.get("name") or ""), re.I)
                         and o.get("active", True) is not False), None)
            under = next((o for o in outcomes if re.search(r"\bunder\b", str(o.get("name") or ""), re.I)
                          and o.get("active", True) is not False), None)
            if not over or not under:
                continue
            try:
                over_odds, under_odds = float(over.get("odds")), float(under.get("odds"))
            except (TypeError, ValueError):
                continue
            if not all(math.isfinite(x) and x > 1 for x in (over_odds, under_odds)):
                continue
            balance = abs(math.log(over_odds / under_odds)) + 0.05 * abs((over_odds + under_odds) / 2 - 1.9)
            distance = abs(line - float(expected_total)) if expected_total is not None else 0.0
            candidates.append({
                "line": line, "over_odds": over_odds, "under_odds": under_odds,
                "market_id": "225", "source": "SportyBet Nigeria",
                "sportybet_event_id": str(event.get("event_id") or ""),
                "quote_timestamp": fetched_at.isoformat(),
                "quote_capture_basis": "SportyBet API response observed_at",
                "market_selection_score": round(balance, 6),
                "settlement": "Official final score including overtime",
                "_balance": balance, "_distance": distance,
            })
    if not candidates:
        return None
    # Prefer the balanced/main price pair; forecast proximity only breaks a tie.
    chosen = min(candidates, key=lambda x: (x["_balance"], x["_distance"], x["line"]))
    chosen.pop("_balance", None)
    chosen.pop("_distance", None)
    return chosen

def apply_sportybet_total_snapshot(prediction, fixture, feed):
    """Attach a timestamped pre-game quote without allowing market odds into the model."""
    start = dt(prediction.get("start_time"))
    now = datetime.now(timezone.utc)
    if not start or now >= start:
        return prediction
    quote = sportybet_total_for_fixture(fixture, feed, expected_total=prediction.get("expected_total"))
    if not quote or dt(quote.get("quote_timestamp")) is None or dt(quote["quote_timestamp"]) >= start:
        return prediction
    markets = prediction.get("markets") if isinstance(prediction.get("markets"), dict) else {}
    existing = markets.get("total_ou") if isinstance(markets.get("total_ou"), dict) else {}
    # Keep a previously captured pre-game snapshot if a refresh does not yield a newer valid quote.
    previous = dt(existing.get("quote_timestamp"))
    current = dt(quote.get("quote_timestamp"))
    if previous and current and previous >= current:
        return prediction
    expected = prediction.get("expected_total")
    try:
        edge_points = float(expected) - float(quote["line"])
    except (TypeError, ValueError):
        edge_points = None
    lean = "NO_CLEAR_LEAN"
    pick = None
    if edge_points is not None and edge_points >= 3.0:
        lean, pick = "OVER", "over"
    elif edge_points is not None and edge_points <= -3.0:
        lean, pick = "UNDER", "under"
    quote.update({
        "expected_total": float(expected) if expected is not None else None,
        "projection_edge_points": round(edge_points, 2) if edge_points is not None else None,
        "lean": lean, "pick": pick, "prediction_status": "LIVE_EXPERIMENTAL_NOT_QUALIFIED",
        "model_is_market_blind": True,
    })
    markets["total_ou"] = quote
    prediction["markets"] = markets
    signal_quality = prediction.get("signal_quality") if isinstance(prediction.get("signal_quality"), dict) else {}
    signal_quality["total_market_available"] = True
    signal_quality["total_market_source"] = "SportyBet Nigeria market 225 (Over/Under incl. overtime)"
    prediction["signal_quality"] = signal_quality
    return prediction


def dt(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        for f in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(v), f).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def football_data_fixtures():
    """Fallback/current Eredivisie fixture source with free odds.

    The season result CSV is intentionally not used for upcoming fixtures:
    Football-Data publishes a separate fixtures feed. This avoids treating a
    result archive as a future schedule and avoids the redirect problem seen
    on the season CSV from the GitHub Actions runner.
    """
    urls = (
        "https://football-data.co.uk/fixtures.csv",
        "https://www.football-data.co.uk/fixtures.csv",
        "https://www.football-data.co.uk/matches/resources/fixtures.csv",
    )
    last_error = None
    text = None
    source_url = None
    for url in urls:
        try:
            r = S.get(url, timeout=45, allow_redirects=False)
            if r.status_code == 200 and r.text.strip():
                text = r.text
                source_url = url
                break
            last_error = f"{url}: HTTP {r.status_code}"
        except Exception as exc:
            last_error = f"{url}: {exc}"
    if text is None:
        raise RuntimeError(f"Football-Data fixtures feed unavailable: {last_error}")

    rows = []
    for x in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if (x.get("Div") or "").strip().upper() != "N1":
            continue
        d = dt(x.get("Date"))
        h = (x.get("HomeTeam") or "").strip()
        a = (x.get("AwayTeam") or "").strip()
        if not d or not h or not a:
            continue
        time_value = (x.get("Time") or "").strip()
        if time_value:
            try:
                hh, mm = time_value.split(":", 1)
                d = d.replace(hour=int(hh), minute=int(mm))
            except Exception:
                pass
        if d < NOW - timedelta(hours=6) or d > NOW + timedelta(days=10):
            continue

        def num(k):
            try:
                return float(x[k]) if x.get(k) not in (None, "") else None
            except Exception:
                return None

        odds = {
            "home": num("B365H") or num("AvgH"),
            "draw": num("B365D") or num("AvgD"),
            "away": num("B365A") or num("AvgA"),
            "over_2_5": num("B365>2.5") or num("Avg>2.5"),
            "under_2_5": num("B365<2.5") or num("Avg<2.5"),
        }
        rows.append({
            "event_id": f"fd-fixture|N1|{d.isoformat()}|{h}|{a}",
            "date": d.isoformat(), "home": h, "away": a,
            "markets": {"odds": odds, "source": "football-data.co.uk", "source_url": source_url},
            "source": "football-data.co.uk",
        })
    return sorted(rows, key=lambda z: z["date"])


def sofascore_fixtures():
    """Second current-fixture fallback using SofaScore's public daily schedule."""
    base = "https://api.sofascore.com/api/v1/sport/football/scheduled-events/{}"
    rows = []
    errors = []
    for i in range(0, 11):
        day = (NOW + timedelta(days=i)).date().isoformat()
        try:
            r = S.get(base.format(day), timeout=45)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            errors.append(f"{day}: {exc}")
            continue
        for e in payload.get("events", []):
            tournament = e.get("tournament") or {}
            unique = tournament.get("uniqueTournament") or {}
            if unique.get("id") != 37 and str(unique.get("slug") or "").lower() != "eredivisie":
                continue
            status = (e.get("status") or {}).get("type")
            if status in {"finished", "canceled", "postponed"}:
                continue
            ts = e.get("startTimestamp")
            if not ts:
                continue
            d = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            if d < NOW - timedelta(hours=6) or d > NOW + timedelta(days=10):
                continue
            home = (e.get("homeTeam") or {}).get("name")
            away = (e.get("awayTeam") or {}).get("name")
            if not home or not away:
                continue
            rows.append({
                "event_id": f"sofa|{e.get('id')}",
                "date": d.isoformat(), "home": home, "away": away,
                "markets": {"odds": {}, "source": "sofascore"},
                "source": "sofascore",
            })
    if not rows:
        raise RuntimeError("SofaScore Eredivisie fixture fallback returned no rows; " + "; ".join(errors[-3:]))
    return sorted({r["event_id"]: r for r in rows}.values(), key=lambda z: z["date"])


def current_ere():
    try:
        rows = current("Eredivisie")
        if rows:
            return rows
    except Exception:
        pass
    try:
        return football_data_fixtures()
    except Exception:
        return sofascore_fixtures()


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def goals_markets(xg_home, xg_away):
    total = max(0.05, xg_home + xg_away)
    under25 = sum(poisson_pmf(k, total) for k in range(3))
    over25 = max(0.0, 1.0 - under25)
    btts_yes = 1 - math.exp(-xg_home) - math.exp(-xg_away) + math.exp(-total)
    return {
        "over_under": {
            "line": 2.5, "over": round(over25, 6), "under": round(under25, 6),
            "pick": "over" if over25 >= under25 else "under"
        },
        "btts": {
            "yes": round(btts_yes, 6), "no": round(1-btts_yes, 6),
            "pick": "yes" if btts_yes >= 0.5 else "no"
        }
    }


def market_value(prob, odds):
    if not odds or odds <= 1:
        return None
    return round(prob * odds - 1, 5)


def ere_prediction(fixture, history):
    event = {
        "id": fixture["event_id"],
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": fixture["home"]}},
            {"homeAway": "away", "team": {"displayName": fixture["away"]}},
        ]}],
    }
    p = independent_prediction(event, "Eredivisie", history, cutoff=fixture["date"])
    if not p:
        return None
    markets = goals_markets(p["xg_home"], p["xg_away"])
    odds = (fixture.get("markets") or {}).get("odds") or {}
    probs = {"p1": p["p1"], "draw": p["draw"], "p2": p["p2"]}
    odds_values = {k: market_value(probs[k], odds.get(k)) for k in ("home", "draw", "away")}
    value_candidates = {"home": odds_values["home"], "draw": odds_values["draw"], "away": odds_values["away"]}
    value_candidates = {k:v for k,v in value_candidates.items() if v is not None}
    best_value = max(value_candidates.items(), key=lambda z:z[1]) if value_candidates else None
    return {
        "sport": "football", "league": "Eredivisie", "event_id": fixture["event_id"],
        "start_time": fixture["date"], "player_1": fixture["home"], "player_2": fixture["away"],
        "probabilities": probs, "pick": max(probs, key=probs.get),
        "confidence": round(max(probs.values()), 6),
        "expected_goals": {"p1": p["xg_home"], "p2": p["xg_away"], "total": round(p["xg_home"]+p["xg_away"],4)},
        "markets": markets,
        "market": {"odds": odds, "value_by_outcome": odds_values, "best_value": best_value},
        "model": p["method"],
        "signal_quality": {"effective_sample": p["effective_sample"], "home_sample": p["sample_home"], "away_sample": p["sample_away"], "status": "LIVE_EXPERIMENTAL"},
        "prediction_status": "live_experimental", "paper_only": False, "live_experimental": True,
    }


def nba_total_publication_snapshot(prediction, published_at=None):
    """Freeze the first price-auditable pre-match NBA total generated for an event.

This is a complete research cohort, not a claim that the model signal passed a
separate confidence/qualification threshold.
"""
    published_at = dt(published_at or NOW.isoformat())
    start = dt(prediction.get("start_time"))
    market = ((prediction.get("markets") or {}).get("total_ou") or {})
    quote_time = dt(market.get("quote_timestamp"))
    if not published_at or not start or published_at >= start:
        return None
    if str(market.get("market_id") or "") != "225":
        return None
    if str(market.get("source") or "").strip().lower() != "sportybet nigeria":
        return None
    if not quote_time or quote_time > published_at or quote_time >= start:
        return None
    if (published_at - quote_time).total_seconds() > 15 * 60:
        return None
    # Freeze line and both prices even when the model has no directional lean.
    # Only picked/settled rows can later enter ROI qualification.
    try:
        line = float(market.get("line"))
        over_odds = float(market.get("over_odds"))
        under_odds = float(market.get("under_odds"))
    except (TypeError, ValueError):
        return None
    if not 100 <= line <= 300 or not all(math.isfinite(x) and x > 1 for x in (over_odds, under_odds)):
        return None
    if not market.get("sportybet_event_id"):
        return None

    snapshot = json.loads(json.dumps(prediction))
    snapshot["published_at"] = published_at.isoformat()
    snapshot["publication_snapshot_verified"] = True
    snapshot["publication_snapshot_kind"] = "first_price_auditable_pre_match_nba_total"
    identity = "|".join([
        str(snapshot.get("event_id") or ""), snapshot["published_at"],
        str(line), str(market.get("pick") or "no_clear_lean"), str(market.get("quote_timestamp")),
        str(over_odds), str(under_odds),
    ])
    snapshot["publication_snapshot_id"] = "nba-total-pub:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    snapshot["paper_only"] = True
    return snapshot


def append_nba_totals_publication_snapshots(predictions, path=None, published_at=None):
    """Append one immutable, first-qualified snapshot per event; never overwrite prior picks."""
    path = Path(path) if path else NBA_TOTAL_SNAPSHOTS
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except (OSError, json.JSONDecodeError):
        existing = []
    known = {str(row.get("event_id")) for row in existing if isinstance(row, dict) and row.get("event_id")}
    added = 0
    for prediction in predictions:
        event_id = str(prediction.get("event_id") or "")
        if not event_id or event_id in known:
            continue
        snapshot = nba_total_publication_snapshot(prediction, published_at)
        if snapshot:
            existing.append(snapshot)
            known.add(event_id)
            added += 1
    existing.sort(key=lambda row: (str(row.get("published_at") or ""), str(row.get("event_id") or "")))
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
    return {"added": added, "total": len(existing)}

def should_refresh_nba_prediction(old, start, now=None, max_age_hours=6):
    """Refresh old projections only while the fixture is still pre-game."""
    now = now or NOW
    if not old:
        return True
    if not start or start <= now:
        return False
    if old.get("totals_model_version") != NBA_TOTALS_MODEL_VERSION:
        return True
    stamp = dt(old.get("generated_at") or old.get("prediction_created_at"))
    if not stamp or stamp >= start:
        return True
    return now - stamp >= timedelta(hours=max_age_hours)


def main():
    nba_history, nba_errors = collect("NBA")
    # Fit the pace contribution and residual correction strictly on the
    # evaluator's development window before emitting new forecasts.
    try:
        from nba_totals_walk_forward import evaluate as evaluate_nba_totals
        ledger_path = DATA / "nba_totals_ledger.json"
        ledger_payload = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
        ledger_rows = ledger_payload.get("records", []) if isinstance(ledger_payload, dict) else ledger_payload
        calibration_report = evaluate_nba_totals(nba_history, ledger_rows if isinstance(ledger_rows, list) else [])
        (DATA / "nba_totals_oos_value_test.json").write_text(
            json.dumps(calibration_report, indent=2) + "\n", encoding="utf-8"
        )
        model_calibration = calibration_report.get("model_calibration") or {}
        pace_blend_weight = float(model_calibration.get("selected_pace_blend_weight") or 0.0)
        bias_adjustment = float(model_calibration.get("production_bias_correction") or 0.0)
    except Exception as exc:
        print(json.dumps({"nba_totals_calibration_error": str(exc)}))
        pace_blend_weight = 0.0
        bias_adjustment = 0.0
    ere_history, ere_errors = collect("Eredivisie")
    nba_fixtures = [] if NOW < NBA_START else current("NBA")
    ere_fixtures = current_ere()

    ere_hist_for_model = [{
        "sport": "football", "settled": True,
        "final_score": [r["home_score"], r["away_score"]],
        "event_id": r["event_id"], "start_time": r["date"],
        "league": "Eredivisie", "player_1": r["home"], "player_2": r["away"]
    } for r in ere_history]

    ere_predictions = [p for f in ere_fixtures if (p := ere_prediction(f, ere_hist_for_model))]
    # Refresh stale upcoming projections before tip-off so the current desk does
    # not keep a multi-day-old forecast. Once a game starts, retain its last
    # pre-game snapshot unchanged for honest settlement and accuracy tracking.
    try:
        old_nba = json.loads((DATA/"nba_predictions.json").read_text(encoding="utf-8"))
        if not isinstance(old_nba, list): old_nba = []
    except Exception:
        old_nba = []
    old_by_id = {str(x.get("event_id")): x for x in old_nba if isinstance(x, dict)}
    nba_predictions = []
    seen_nba = set()
    sportybet_feed, sportybet_error = sportybet_basketball_feed()
    for f in nba_fixtures:
        eid = str(f["event_id"])
        start = dt(f.get("date"))
        old = old_by_id.get(eid)
        if old and not should_refresh_nba_prediction(old, start, NOW):
            row = dict(old)
        else:
            # If a fixture has already started and no pre-game snapshot exists,
            # leave it for live-score monitoring only; do not invent a prediction.
            if not start or start <= NOW:
                if old:
                    row = dict(old)
                else:
                    continue
            else:
                p = nba_predict(f, nba_history, pace_blend_weight=pace_blend_weight, bias_adjustment=bias_adjustment)
                if not p: continue
                probs = p["moneyline"]
                row = {
                    "sport": "basketball", "league": "NBA", "event_id": eid,
                    "start_time": f["date"], "player_1": f["home"], "player_2": f["away"],
                    "probabilities": {"p1": round(probs["home"],6), "p2": round(probs["away"],6)},
                    "pick": "p1" if probs["home"] >= probs["away"] else "p2",
                    "confidence": round(max(probs.values()),6), "expected_score": p["expected_score"],
                    "expected_total": p["expected_total"], "totals_model_version": p.get("totals_model_version"), "total_model_features": p.get("total_model_features"), "markets": {"moneyline": p["moneyline"]},
                    "model": p["model"], "signal_quality": {"status":"LIVE_EXPERIMENTAL","market_odds_available":False},
                    "generated_at": NOW.isoformat(), "prediction_created_at": NOW.isoformat(),
                    "accuracy_eligible": True, "prediction_status": "live_experimental",
                    "paper_only": True, "live_experimental": True,
                }
        row = apply_sportybet_total_snapshot(row, f, sportybet_feed)
        nba_predictions.append(row)
        seen_nba.add(eid)
    # Keep recent pre-game snapshots through the settlement grace window.
    for old in old_nba:
        if not isinstance(old, dict): continue
        eid = str(old.get("event_id") or "")
        start = dt(old.get("start_time"))
        stamp = dt(old.get("generated_at") or old.get("prediction_created_at"))
        if eid and eid not in seen_nba and start and stamp and stamp < start and start >= NOW-timedelta(hours=30):
            nba_predictions.append(dict(old))
            seen_nba.add(eid)
    nba_predictions.sort(key=lambda x: x.get("start_time", ""))

    # Freeze one first-qualified, fresh-price publication per event. Later desk refreshes
    # may change the visible quote, but cannot rewrite the historical performance cohort.
    snapshot_status = append_nba_totals_publication_snapshots(nba_predictions, published_at=datetime.now(timezone.utc).isoformat())

    (DATA/"ere_divisie_history.json").write_text(json.dumps(ere_history, indent=2), encoding="utf-8")
    (DATA/"nba_history.json").write_text(json.dumps(nba_history, indent=2), encoding="utf-8")
    (DATA/"ere_divisie_predictions.json").write_text(json.dumps(ere_predictions, indent=2), encoding="utf-8")
    (DATA/"nba_predictions.json").write_text(json.dumps(nba_predictions, indent=2), encoding="utf-8")

    status = {
        "updated_at": NOW.isoformat(), "release_mode": "LIVE_EXPERIMENTAL", "live_trading_approved": False,
        "competitions": {
            "NBA": {"historical_events": len(nba_history), "current_fixtures": len(nba_fixtures), "collection_errors": len(nba_errors), "status": "LIVE_EXPERIMENTAL" if nba_predictions else ("PRESEASON_READY" if NOW < NBA_START else "NO_CURRENT_FIXTURES"), "history_source": "llimllib/nba_data v2 team_game_logs pace and efficiency catalog; ESPN and NBA Elo fallbacks"},
            "Eredivisie": {"historical_events": len(ere_history), "current_fixtures": len(ere_fixtures), "published_predictions": len(ere_predictions), "collection_errors": len(ere_errors), "status": "LIVE_EXPERIMENTAL" if ere_predictions else "NO_CURRENT_FIXTURES", "fixture_source": "ESPN primary; Football-Data fixtures.csv; SofaScore daily schedule fallback"},
        },
        "source_diagnostics": {"NBA": nba_errors[:5], "Eredivisie": ere_errors[:5], "SportyBet_NBA_totals": ([sportybet_error] if sportybet_error else [])},
        "nba_totals_publication_snapshots": snapshot_status,
        "monitoring": {"settlement": "expansion_prediction_history.json", "promotion_rule": "live evidence + calibration + market benchmark; automatic demotion on data failure", "market_data_is_benchmark_only": True},
        "notes": ["Independent probabilities never consume market probabilities.", "LIVE_EXPERIMENTAL signals are real generated predictions, not guarantees or live-trading approval.", "NBA remains preseason-ready until 2026-10-20, then enters live experimental mode automatically.", "Eredivisie uses ESPN when available, Football-Data's current fixture feed as the first fallback, and SofaScore's daily schedule as the second fallback."],
    }
    (DATA/"expansion_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
