#!/usr/bin/env python3
"""Daily Jev sports picks for odds.socialnews.xyz.

Fetches upcoming games from ESPN's core API (date-dynamic: no hardcoded
dates), runs each through the Jev CLIs, and writes data.json for the
static site. Designed for a daily morning cron.

Safeguards (borrowed from the elections pipeline):
- ESPN failures never become fake picks: a league whose fetch fails gets
  an honest empty state, and if *nothing* fetches, the old data.json is
  kept untouched and the run aborts.
- Jev calls are retried (3x); a game with no successful call is skipped,
  never invented.
- Calls are staggered and lightly threaded to stay under rate limits.

Usage: ./make_sports_data.py [--out DIR] [--dry-run]
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
JEV_2WAY = "/home/hatch/workspace/skills/typesafe/bin/jev-sports-pick"
JEV_3WAY = "/home/hatch/workspace/sports-calls/jev-soccer-pick"
CRICKET_FIXTURES = os.path.join(REPO, "cricket_fixtures.json")

BASE = "https://sports.core.api.espn.com/v2/sports"

# (tab id, short label, title, sport path, league path, date window, kind)
# date window: "today" | "week" (today..+7) | "soccer" (today..+2)
LEAGUES = [
    ("nfl", "NFL", "NFL — this week", "football", "nfl", "week", "2way"),
    ("mlb", "MLB", "MLB — today", "baseball", "mlb", "today", "2way"),
    ("nba", "NBA", "NBA", "basketball", "nba", "today", "2way"),
    ("nhl", "NHL", "NHL", "hockey", "nhl", "today", "2way"),
    ("mls", "MLS", "MLS", "soccer", "usa.1", "soccer", "3way"),
    ("epl", "EPL", "Premier League", "soccer", "eng.1", "soccer", "3way"),
    ("laliga", "LaLiga", "La Liga", "soccer", "esp.1", "soccer", "3way"),
    ("seriea", "Serie A", "Serie A", "soccer", "ita.1", "soccer", "3way"),
    ("bundesliga", "Bundesliga", "Bundesliga", "soccer", "ger.1", "soccer", "3way"),
    ("ligue1", "Ligue 1", "Ligue 1", "soccer", "fra.1", "soccer", "3way"),
]

_team_cache = {}


def log(msg):
    print(f"[sports] {msg}", file=sys.stderr, flush=True)


def espn_get(url):
    out = subprocess.run(["curl", "-s", "-m", "25", url],
                         capture_output=True, text=True, timeout=35)
    return json.loads(out.stdout)


def team_info(ref):
    if ref in _team_cache:
        return _team_cache[ref]
    try:
        d = espn_get(ref)
        info = {"abbr": d.get("abbreviation", "?"), "name": d.get("displayName", "?")}
    except Exception:
        info = {"abbr": "?", "name": "?"}
    _team_cache[ref] = info
    return info


def record_summary(t):
    ref = (t.get("record") or {}).get("$ref")
    if not ref:
        return ""
    if ref in _team_cache and isinstance(_team_cache[ref], str):
        return _team_cache[ref]
    try:
        d = espn_get(ref)
        s = ""
        for it in d.get("items") or []:
            if it.get("type") == "total" or not s:
                s = it.get("summary", "")
                if it.get("type") == "total":
                    break
        _team_cache[ref] = s
        return s
    except Exception:
        return ""


def fmt_amer(v):
    if v is None or v == "":
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("+" if v >= 0 else "") + str(int(v))


def parse_odds_2way(comp):
    odds_ref = (comp.get("odds") or {}).get("$ref")
    line, total, book = "", "", ""
    if odds_ref:
        try:
            od = espn_get(odds_ref)
            items = od.get("items") or []
            o = items[0] if items else {}
            if isinstance(o, dict) and o.get("$ref") and "details" not in o:
                o = espn_get(o["$ref"])
            line = o.get("details", "")
            total = o.get("overUnder", "")
            book = (o.get("provider") or {}).get("name", "")
        except Exception as exc:
            log(f"odds fetch failed: {exc}")
    return line, total, book


def parse_odds_3way(comp):
    odds_ref = (comp.get("odds") or {}).get("$ref")
    mh, md, ma, total, book = "", "", "", "", ""
    if odds_ref:
        try:
            od = espn_get(odds_ref)
            items = od.get("items") or []
            o = None
            for it in items:
                if isinstance(it, dict) and it.get("$ref"):
                    it = espn_get(it["$ref"])
                prov = (it.get("provider") or {}).get("id") or (it.get("provider") or {}).get("name")
                if str(prov) == "58":  # DraftKings
                    o = it
                    break
            if o is None and items:
                o = items[0]
                if isinstance(o, dict) and o.get("$ref"):
                    o = espn_get(o["$ref"])
            if o:
                book = (o.get("provider") or {}).get("name", "")
                mh = fmt_amer((o.get("homeTeamOdds") or {}).get("moneyLine"))
                ma = fmt_amer((o.get("awayTeamOdds") or {}).get("moneyLine"))
                md = fmt_amer((o.get("drawOdds") or {}).get("moneyLine"))
                if not md:
                    md = ((o.get("current") or {}).get("draw") or {}).get("alternateDisplayValue", "")
                total = o.get("overUnder", "")
        except Exception as exc:
            log(f"odds fetch failed: {exc}")
    return mh, md, ma, total, book


def parse_event(tab_id, short, kind, ev):
    try:
        d = espn_get(ev["$ref"])
    except Exception as exc:
        log(f"event fetch failed: {exc}")
        return None
    comp = (d.get("competitions") or [{}])[0]
    sides = {}
    for t in comp.get("competitors", []):
        info = team_info((t.get("team") or {}).get("$ref", ""))
        sides[t.get("homeAway")] = {**info, "record": record_summary(t)}
    if "home" not in sides or "away" not in sides:
        return None
    g = {
        "tab": tab_id, "league": short,
        "date": (d.get("date") or "")[:16],
        "name": d.get("name", ""),
        "away": sides["away"], "home": sides["home"],
    }
    if kind == "3way":
        mh, md, ma, total, book = parse_odds_3way(comp)
        g.update(moneyline_home=mh, moneyline_draw=md, moneyline_away=ma,
                 total=total, book=book)
    else:
        line, total, book = parse_odds_2way(comp)
        g.update(line=line, total=total, book=book)
    return g


def fetch_league(tab_id, short, title, sport, league, window, kind):
    today = datetime.date.today()
    if window == "week":
        dates = f"{today:%Y%m%d}-{today + datetime.timedelta(days=7):%Y%m%d}"
    elif window == "soccer":
        dates = f"{today:%Y%m%d}-{today + datetime.timedelta(days=4):%Y%m%d}"
    else:
        dates = f"{today:%Y%m%d}"
    url = (f"{BASE}/{sport}/leagues/{league}/events"
           f"?lang=en&region=us&dates={dates}&limit=50")
    try:
        data = espn_get(url)
    except Exception as exc:
        log(f"{short} list failed: {exc}")
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    games = []
    for ev in data.get("items", []):
        g = parse_event(tab_id, short, kind, ev)
        if not g:
            continue
        try:
            dt = datetime.datetime.fromisoformat(g["date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        if dt < now - datetime.timedelta(hours=1):
            continue  # already started/finished
        games.append(g)
    # NFL/MLB/etc: cap at a sane number, soonest first
    games.sort(key=lambda g: g["date"])
    log(f"{short}: {len(games)} upcoming")
    return {"id": tab_id, "short": short, "title": title, "kind": kind,
            "games": games, "fetch_ok": True}


def describe_2way(g):
    a, h = g["away"], g["home"]
    parts = [f"{g['league']}: {a['name']} ({a['record']}) at {h['name']} ({h['record']}).",
             f"Game time {g['date']} UTC."]
    if g.get("line"):
        book = f" ({g['book']})" if g.get("book") else ""
        parts.append(f"Market line{book}: {g['line']}.")
    if g.get("total"):
        parts.append(f"Total {g['total']}.")
    return " ".join(parts)


def describe_3way(g):
    a, h = g["away"], g["home"]
    parts = [f"{g['league']}: {a['name']} ({a['record']}) at {h['name']} ({h['record']}).",
             f"Kickoff {g['date']} UTC."]
    if g.get("moneyline_home"):
        book = f" ({g['book']})" if g.get("book") else ""
        parts.append(f"Market 3-way moneyline{book}: {h['abbr']} {g['moneyline_home']}, "
                     f"draw {g['moneyline_draw']}, {a['abbr']} {g['moneyline_away']}.")
    if g.get("total"):
        parts.append(f"Total {g['total']}.")
    return " ".join(parts)


def run_cli(cli, state, tries=3):
    err = "?"
    for attempt in range(tries):
        try:
            proc = subprocess.run([cli, "--state", state],
                                  capture_output=True, text=True, timeout=120)
            ans = json.loads(proc.stdout.strip().splitlines()[-1])
            if ans.get("ok") and ans.get("pick"):
                return ans
            err = ans.get("error", "?")
        except Exception as exc:
            err = str(exc)[:200]
        log(f"jev retry {attempt + 1}/{tries}: {err}")
        time.sleep(2)
    return {"ok": False, "error": err}


def pick_2way(g):
    ans = run_cli(JEV_2WAY, describe_2way(g))
    if not ans.get("ok"):
        return None
    pick, hwp = ans.get("pick"), ans.get("home_win_pct")
    win_pct = (hwp if pick == "home_win"
               else 100 - hwp if isinstance(hwp, (int, float)) else None)
    if win_pct is None:
        return None
    return {
        "pick": pick, "pick_label": f"{g['home']['abbr']} wins" if pick == "home_win" else f"{g['away']['abbr']} wins",
        "pct": round(win_pct), "conf": ans.get("confidence", 0),
        "side": "home" if pick == "home_win" else "away",
    }


def pick_3way(g):
    ans = run_cli(JEV_3WAY, describe_3way(g))
    if not ans.get("ok"):
        return None
    pick = ans.get("pick")  # home_win / draw / away_win
    probs = {"h": round(ans.get("home_win_pct") or 0),
             "d": round(ans.get("draw_pct") or 0),
             "a": round(ans.get("away_win_pct") or 0)}
    pct = ans.get("probability") or max(probs.values())
    label = {"home_win": f"{g['home']['abbr']} wins", "away_win": f"{g['away']['abbr']} wins",
             "draw": "Draw"}.get(pick, pick)
    return {
        "pick": pick, "pick_label": label,
        "pct": round(pct), "probs": probs, "conf": ans.get("confidence", 0),
        "side": "home" if pick == "home_win" else "away",
    }


def fmt_et(iso):
    try:
        dt = datetime.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        et = dt.astimezone(datetime.timezone(datetime.timedelta(hours=-4), "ET"))
        return et.strftime("%a, %b %-d · %-I:%M %p ET")
    except Exception:
        return iso


def build_card(g, res):
    a, h = g["away"], g["home"]
    card = {
        "away": a["name"], "ar": a["record"], "home": h["name"], "hr": h["record"],
        "time": fmt_et(g["date"]),
        "pick": res["pick"], "pick_label": res["pick_label"], "pct": res["pct"],
        "conf": res["conf"], "side": res["side"],
    }
    if g.get("total"):
        card["total"] = g["total"]
    if g.get("book"):
        card["book"] = g["book"]
    if "moneyline_home" in g:
        mh, md, ma = g["moneyline_home"], g["moneyline_draw"], g["moneyline_away"]
        if mh or md or ma:
            card["line"] = f"{h['abbr']} {mh or '—'} / Draw {md or '—'} / {a['abbr']} {ma or '—'}"
        card["probs"] = res["probs"]
        card["event"] = g["league"]
        card["inputText"] = "Inputs: current records and 3-way moneyline."
    else:
        if g.get("line"):
            card["line"] = g["line"]
        card["inputText"] = ("Inputs: listed market, team records and matchup context."
                             if g.get("line") or g.get("total")
                             else "Inputs: matchup context; detailed market not shown.")
    return card


def load_cricket():
    if not os.path.exists(CRICKET_FIXTURES):
        return []
    try:
        fixtures = json.load(open(CRICKET_FIXTURES))
    except Exception as exc:
        log(f"cricket fixtures unreadable: {exc}")
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    upcoming = []
    for f in fixtures:
        try:
            dt = datetime.datetime.fromisoformat(f["date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        if dt < now - datetime.timedelta(hours=1):
            continue
        upcoming.append(f)
    return upcoming


def pick_cricket(f):
    a, h = f["away"], f["home"]
    state = (f"Cricket, {f['event']}: {a['name']} vs {h['name']}. "
             f"Venue: {f.get('venue', '')}. {f.get('note', '')} "
             f"No published betting line available.")
    ans = run_cli(JEV_2WAY, state)
    if not ans.get("ok"):
        return None
    pick, hwp = ans.get("pick"), ans.get("home_win_pct")
    win_pct = (hwp if pick == "home_win"
               else 100 - hwp if isinstance(hwp, (int, float)) else None)
    if win_pct is None:
        return None
    return {
        "away": a["name"], "ar": "", "home": h["name"], "hr": "",
        "time": fmt_et(f["date"]),
        "event": f["event"], "venue": f.get("venue", ""),
        "pick": pick,
        "pick_label": f"{h['abbr']} win" if pick == "home_win" else f"{a['abbr']} win",
        "pct": round(win_pct), "conf": ans.get("confidence", 0),
        "side": "home" if pick == "home_win" else "away",
        "inputText": "Inputs: series context and matchup notes; no published line.",
    }


def game_key(g):
    return (g.get("away"), g.get("home"), g.get("time"))


def compute_changes(old, new_leagues):
    """One-line notices for the site's 'Latest changes' box."""
    if not old:
        return []
    old_games = {}
    for lg in old.get("leagues", []):
        for g in lg.get("games", []):
            old_games[(lg["id"], g.get("away"), g.get("home"))] = g
    notes = []
    for lg in new_leagues:
        new_keys = {(lg["id"], g["away"], g["home"]) for g in lg.get("games", [])}
        old_keys = {k[1:] for k in old_games if k[0] == lg["id"]}
        added = len(new_keys - old_keys)
        if added:
            notes.append(f"{lg['short']}: {added} new matchup{'s' if added > 1 else ''} on the board.")
    return notes[:3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=REPO)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-games", type=int, default=0,
                    help="cap games per league (0 = no cap); for testing")
    args = ap.parse_args()

    out_path = os.path.join(args.out, "data.json")
    old = None
    if os.path.exists(out_path):
        try:
            old = json.load(open(out_path))
        except Exception:
            old = None

    # 1. Fetch every league.
    leagues = []
    for spec in LEAGUES:
        lg = fetch_league(*spec)
        if lg is None:
            lg = {"id": spec[0], "short": spec[1], "title": spec[2],
                  "kind": spec[6], "games": [], "fetch_ok": False}
        leagues.append(lg)

    total_games = sum(len(lg["games"]) for lg in leagues)
    if total_games == 0:
        log("ESPN returned zero upcoming games — keeping old data.json untouched.")
        return 2

    # 2. Jev picks, lightly threaded with stagger.
    def do_pick(item):
        lg, g = item
        time.sleep(1.0)
        try:
            res = pick_3way(g) if lg["kind"] == "3way" else pick_2way(g)
        except Exception as exc:
            log(f"pick crashed for {g['away']['abbr']}@{g['home']['abbr']}: {exc}")
            res = None
        return lg, g, res

    jobs = []
    for lg in leagues:
        games = lg["games"][:args.max_games] if args.max_games else lg["games"]
        for g in games:
            jobs.append((lg, g))
    log(f"running Jev for {len(jobs)} games…")
    cards = {lg["id"]: [] for lg in leagues}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for lg, g, res in ex.map(do_pick, jobs):
            if res:
                cards[lg["id"]].append(build_card(g, res))
            else:
                log(f"no pick: {g['away']['abbr']} @ {g['home']['abbr']} ({lg['short']})")

    # 3. Cricket from the fixtures file.
    cricket_cards = []
    for f in load_cricket():
        c = pick_cricket(f)
        if c:
            cricket_cards.append(c)
        else:
            log(f"no pick: cricket {f.get('event', '?')[:60]}")

    # 4. Assemble leagues for the page.
    new_leagues = []
    for lg in leagues:
        games = cards[lg["id"]]
        if not games and not lg["fetch_ok"]:
            note = "This league didn't load this morning — check back tomorrow."
        elif not games:
            note = "No upcoming games — check back tomorrow."
        else:
            note = ""
        new_leagues.append({
            "id": lg["id"], "short": lg["short"], "title": lg["title"],
            "count": (f"{len(games)} game{'s' if len(games) != 1 else ''} · "
                      + ("Three-way probabilities shown" if lg["kind"] == "3way"
                         else "Winner probability shown")) if games else "",
            "games": games,
            "empty": "No games today" if games else "Couldn't load today",
            "note": note or "Check back tomorrow — the board refreshes every morning.",
        })
    if cricket_cards:
        new_leagues.append({
            "id": "cricket", "short": "Cricket", "title": "Cricket — upcoming fixtures",
            "count": f"{len(cricket_cards)} matches · Winner probability shown",
            "games": cricket_cards, "empty": "No fixtures",
            "note": "Check back tomorrow — the board refreshes every morning.",
        })

    now_et = (datetime.datetime.now(datetime.timezone.utc)
              .astimezone(datetime.timezone(datetime.timedelta(hours=-4), "ET")))
    data = {
        "generated_et": now_et.strftime("%B %-d, %Y · %-I:%M %p ET"),
        "subtitle": ("Jev's picks for " + now_et.strftime("%A, %B %-d") +
                     " — refreshed every morning."),
        "changes": compute_changes(old, new_leagues),
        "leagues": new_leagues,
    }

    if args.dry_run:
        print(json.dumps(data, indent=1)[:2000])
        log("dry run — not written")
        return 0

    json.dump(data, open(out_path, "w"), indent=1)
    picked = sum(len(lg["games"]) for lg in new_leagues)
    log(f"wrote {out_path} ({picked} picks across {len(new_leagues)} tabs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
