"""Stage 3B only: approved rank-drop derivatives and independent kyoku outcomes."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file
from dontsuka_v026_2b_replay import RELEASE, DB_SHA, ranks

STAGE3A_SHA = "da593920add867904fc82f8f51207a6fe318fa42a2945e1880c5653112fe4ce1"
STAGE2B_SHA = "a81dd53043b557edbccd1dcc4ab0db798a6c71db68aebbd12532272e600a2781"
EXPECTED = {"opponent_rows": 28060, "draws": 27578, "opponent_down": 13170,
            "opponent_same": 14890, "head_down": 12931,
            "games": 2068, "kyoku": 25238, "players": 56, "all_draws": 1257732}


def jdump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verified_zip(path, expected_sha):
    if sha256_file(path) != expected_sha:
        raise ValueError(f"approved input SHA-256 mismatch: {path.name}")
    z = zipfile.ZipFile(path)
    if z.testzip():
        raise ValueError(f"ZIP CRC mismatch: {path.name}")
    manifest = json.loads(z.read("manifest.json"))
    for name, digest in manifest["outputs"].items():
        with z.open(name) as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != digest:
                raise ValueError(f"input member hash mismatch: {name}")
    return z, manifest


def read_csv_zip(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig", newline="")))


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def rates(n, d):
    return "" if not d else f"{100*n/d:.9f}"


def average_ranks(scores):
    return ranks(scores)


def first_rank_drop_event(rows):
    qualifying = [r for r in rows if float(r["rank_drop"]) > 0]
    if not qualifying:
        return None
    first_order = min(int(r["event_order"]) for r in qualifying)
    first_rows = [r for r in qualifying if int(r["event_order"]) == first_order]
    if len({float(r["drawer_rank_before"]) for r in first_rows}) != 1:
        raise ValueError("first qualifying event has inconsistent per-opponent rank")
    return first_rows[0]


def kyoku_outcome(first_rank, end_rank, actual_ron):
    return dict(rank_maintained_or_improved=int(float(end_rank) <= float(first_rank)),
                actual_ron=int(bool(actual_ron)), ron_avoided=int(not actual_ron))


def dimension_keys(row):
    return [("all_period", "", ""),
            ("season", str(row["season_start_year"]), ""),
            ("stage", "", row["stage"]),
            ("season_stage", str(row["season_start_year"]), row["stage"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("stage3a_zip", type=Path)
    ap.add_argument("stage2b_zip", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    db = connect_readonly(args.db)
    db_manifest = verify_database(db, RELEASE)
    db_sha = sha256_file(args.db)
    if db_sha != DB_SHA:
        raise ValueError("fixed database SQLite SHA-256 mismatch")
    z3a, m3a = verified_zip(args.stage3a_zip, STAGE3A_SHA)
    z2b, m2b = verified_zip(args.stage2b_zip, STAGE2B_SHA)
    if m3a.get("database_sha256") != db_sha or m2b.get("database_sha256") != db_sha:
        raise ValueError("approved input database hash differs")
    if m3a.get("counts_3a") != {"opponent_rows": 28060, "draws": 27578,
                                  "opponent_down": 13170, "opponent_same": 14890,
                                  "head_down": 12931, "evaluation_failures": 0}:
        raise ValueError("stage 3A artifact does not match approved final counts")

    # Stage 2B full draw snapshots are the independent source for denominator and
    # the position at the first qualifying Stage 3A event.
    draw_meta = {}
    all_draw_ids = set()
    with z2b.open("draw_snapshots.csv.gz") as raw, gzip.GzipFile(fileobj=raw) as gz, \
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
        for r in csv.DictReader(text):
            eid = int(r["event_id"])
            if eid in all_draw_ids:
                raise ValueError("duplicate event_id in approved draw snapshots")
            all_draw_ids.add(eid)
            draw_meta[eid] = r
    if len(all_draw_ids) != EXPECTED["all_draws"]:
        raise ValueError("Stage 2B full draw count mismatch")
    if all_draw_ids != {int(r[0]) for r in db.execute("SELECT event_id FROM draw_event")}:
        raise ValueError("Stage 2B draw IDs differ from fixed database")

    # Actual point result at kyoku end and all recorded ron outcomes are read from
    # the approved database and checked against Stage 2B's independent replay.
    kyoku_end = {}
    stage2_kyoku = read_csv_zip(z2b, "kyoku_comparison.csv")
    if len(stage2_kyoku) != EXPECTED["kyoku"]:
        raise ValueError("Stage 2B kyoku row count mismatch")
    for r in stage2_kyoku:
        ky = int(r["kyoku_id"])
        if r["match"] not in ("1", "True", "true") or r["error"]:
            raise ValueError(f"approved Stage 2B kyoku comparison is not clean: {ky}")
        replayed = {int(k): int(v) for k, v in json.loads(r["replayed_end_scores"]).items()}
        recorded = {int(k): int(v) for k, v in json.loads(r["recorded_end_scores"]).items()}
        if replayed != recorded:
            raise ValueError(f"Stage 2B end score identity mismatch: {ky}")
        rr = average_ranks(recorded)
        stored = {int(k): float(v) for k, v in json.loads(r["recorded_score_average_ranks"]).items()}
        if rr != stored:
            raise ValueError(f"Stage 2B average rank mismatch: {ky}")
        kyoku_end[ky] = (recorded, rr)
    db_kyoku = {r[0] for r in db.execute("SELECT id FROM kyoku")}
    if set(kyoku_end) != db_kyoku:
        raise ValueError("Stage 2B kyoku coverage differs from DB")

    # The draw-level denominator includes every player's draw, including draws
    # with no don-tsuka. One basic don-tsuka is one unique draw event.
    names = {int(r[0]): r[1] for r in db.execute("SELECT id,name FROM player")}
    draw_ids_by_scope = defaultdict(set)
    dimensions = {}
    for r in db.execute("""SELECT d.event_id,d.actor_player_id,ls.start_year,ss.stage,g.date,k.id,g.id
      FROM draw_event d JOIN event e ON e.id=d.event_id JOIN kyoku k ON k.id=e.kyoku_id
      JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
      JOIN league_season ls ON ls.id=ss.league_season_id"""):
        eid, player, season, stage, date, ky, game = int(r[0]), int(r[1]), int(r[2]), r[3], r[4], int(r[5]), int(r[6])
        dimensions[eid] = dict(player_id=player, season_start_year=season, stage=stage,
                               game_date=date, kyoku_id=ky, game_id=game, player_name=names[player])
        for key in dimension_keys(dimensions[eid]):
            draw_ids_by_scope[(player, *key)].add(eid)
    if len(dimensions) != EXPECTED["all_draws"]:
        raise ValueError("fixed DB draw dimension coverage mismatch")

    # First aggregate only the approved per-opponent hypothetical outcomes.
    source = read_csv_zip(z3a, "opponent_hypothetical_all.csv")
    if len(source) != EXPECTED["opponent_rows"]:
        raise ValueError("Stage 3A opponent row count mismatch")
    by_draw = defaultdict(list)
    by_kyoku_player = defaultdict(list)
    opponent_seen = set()
    for r in source:
        eid, ky, drawer, target = (int(r["draw_event_id"]), int(r["kyoku_id"]),
                                    int(r["drawer"]), int(r["target"]))
        key = (eid, target)
        if key in opponent_seen:
            raise ValueError("duplicate per-opponent classification")
        opponent_seen.add(key)
        if r["status"] != "evaluated":
            raise ValueError("approved Stage 3A contains failed evaluations")
        drop = float(r["rank_drop"])
        if drop < 0 or round(drop * 2) != drop * 2:
            raise ValueError("rank drop not a nonnegative 0.5 step")
        snap = draw_meta[eid]
        rank_before = float(r["drawer_rank_before"])
        score_map = {int(snap[f"player_id_{i}"]): int(snap[f"score_{i}"]) for i in range(1, 5)}
        if drawer not in score_map or average_ranks(score_map)[drawer] != rank_before:
            raise ValueError(f"Stage 3A rank does not match Stage 2B snapshot: {eid}")
        if int(snap["kyoku_id"]) != ky or int(snap["draw_actor_player_id"]) != drawer:
            raise ValueError(f"Stage 3A draw identity mismatch: {eid}")
        by_draw[eid].append(r)
        by_kyoku_player[(ky, drawer)].append(r)
    if len(opponent_seen) != EXPECTED["opponent_rows"] or len(by_draw) != EXPECTED["draws"]:
        raise ValueError("Stage 3A identity totals mismatch")
    if dict(Counter(len(v) for v in by_draw.values())) != {1:27101, 2:472, 3:5}:
        raise ValueError("single/double/triple draw partition mismatch")

    down_rows = [r for r in source if float(r["rank_drop"]) > 0]
    same_rows = [r for r in source if float(r["rank_drop"]) == 0]
    if (len(down_rows), len(same_rows)) != (13170, 14890):
        raise ValueError("per-opponent adopted 3A counts mismatch")
    head_rows = read_csv_zip(z3a, "head_bump_all.csv")
    head_down = sum(float(r["rank_drop"]) > 0 for r in head_rows)
    if len(head_rows) != 27578 or head_down != 12931:
        raise ValueError("head-bump unit mismatch")
    head_by_draw = {int(r["draw_event_id"]): r for r in head_rows}

    # Distinct basic-draw unit, kept separate from per-opponent and head-bump units.
    draw_class = {}
    for eid, rows in by_draw.items():
        drop = [r for r in rows if float(r["rank_drop"]) > 0]
        same = [r for r in rows if float(r["rank_drop"]) == 0]
        draw_class[eid] = {"drawer": int(rows[0]["drawer"]), "down": bool(drop),
                           "same": bool(same), "target_count": len(rows),
                           "drop_widths": Counter(float(r["rank_drop"]) for r in drop)}

    # Deduplicate to one qualifying kyoku per drawer. Baseline is the rank at the
    # earliest rank-drop draw; later drops never replace it.
    ron_events = {(int(r[0]), int(r[1])) for r in db.execute("""SELECT e.kyoku_id,a.target_player_id
      FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type='ron' AND a.target_player_id IS NOT NULL""")}
    kyoku_details = []
    for (ky, drawer), rows in sorted(by_kyoku_player.items()):
        first_row = first_rank_drop_event(rows)
        if first_row is None:
            continue
        eid = int(first_row["draw_event_id"])
        first_order = int(first_row["event_order"])
        meta = dimensions[eid]
        end_scores, end_ranks = kyoku_end[ky]
        if drawer not in end_ranks:
            raise ValueError("drawer missing from kyoku end scores")
        actual_ron = (ky, drawer) in ron_events
        start_rank = float(first_row["drawer_rank_before"])
        end_rank = float(end_ranks[drawer])
        outcome = kyoku_outcome(start_rank, end_rank, actual_ron)
        kyoku_details.append(dict(game_id=meta["game_id"], kyoku_id=ky,
            game_date=meta["game_date"], season_start_year=meta["season_start_year"], stage=meta["stage"],
            player_id=drawer, player_name=names[drawer], first_drop_event_id=eid,
            first_drop_event_order=first_order, first_drop_tile=first_row["tile"],
            first_drop_rank_before=f"{start_rank:.1f}", end_rank=f"{end_rank:.1f}",
            **outcome, actual_end_score=end_scores[drawer],
            first_event_opponent_count=len(by_draw[eid])))

    detail_keys = {(r["kyoku_id"], r["player_id"]) for r in kyoku_details}
    # Verify the local result for every eligible kyoku directly against actual DB results.
    for r in kyoku_details:
        if ((r["kyoku_id"], r["player_id"]) in ron_events) != (not bool(r["ron_avoided"])):
            raise ValueError("actual ron identity mismatch")

    # Complete all scopes, including zero denominator rows. Every metric below
    # carries its numerator and denominator explicitly.
    player_scope_rows = []
    scopes = defaultdict(list)
    for player, name in names.items():
        # A player's existing match participation is the basis for its season/stage rows.
        player_dims = {(int(r[0]), r[1]) for r in db.execute("""SELECT DISTINCT ls.start_year,ss.stage
          FROM game_player_result gr JOIN game g ON g.id=gr.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
          JOIN league_season ls ON ls.id=ss.league_season_id WHERE gr.player_id=?""", (player,))}
        keys = {("all_period", "", "")}
        for season, stage in player_dims:
            keys.update({("season", str(season), ""), ("stage", "", stage),
                         ("season_stage", str(season), stage)})
        for key in sorted(keys):
            scopes[(player, *key)].append(name)
    for key in scopes:
        player = key[0]
        kind, season, stage = key[1:]
        def in_scope(row):
            return ((kind == "all_period") or
                    (kind == "season" and str(row["season_start_year"]) == season) or
                    (kind == "stage" and row["stage"] == stage) or
                    (kind == "season_stage" and str(row["season_start_year"]) == season and row["stage"] == stage))
        draw_set = draw_ids_by_scope.get(key, set())
        own_don = [eid for eid in draw_set if eid in draw_class]
        own_drop_draws = [eid for eid in own_don if draw_class[eid]["down"]]
        own_opp_rows = [r for eid in draw_set for r in by_draw.get(eid, ())]
        opp_drop = sum(float(r["rank_drop"]) > 0 for r in own_opp_rows)
        opp_same = sum(float(r["rank_drop"]) == 0 for r in own_opp_rows)
        scope_details = [r for r in kyoku_details if r["player_id"] == player and in_scope(r)]
        den = len(scope_details)
        maintenance = sum(int(r["rank_maintained_or_improved"]) for r in scope_details)
        avoided = sum(int(r["ron_avoided"]) for r in scope_details)
        actual_ron_count = sum(int(r["actual_ron"]) for r in scope_details)
        scope_head_draws = [head_by_draw[eid] for eid in draw_set if eid in head_by_draw]
        scope_head_drop = sum(float(r["rank_drop"]) > 0 for r in scope_head_draws)
        widths = Counter(float(r["rank_drop"]) for r in own_opp_rows if float(r["rank_drop"]) > 0)
        per_opponent = len(own_opp_rows)
        row = dict(scope=kind, season_start_year=season, stage=stage, player_id=player,
            player_name=names[player], all_draw_count=len(draw_set), basic_dontsuka_draw_count=len(own_don),
            per_opponent_dontsuka_count=per_opponent, opponent_rank_drop_count=opp_drop,
            opponent_rank_maintain_count=opp_same,
            draw_level_any_opponent_drop_count=len(own_drop_draws),
            head_bump_draw_count=len(scope_head_draws), head_bump_rank_drop_count=scope_head_drop,
            rate_drop_per_all_draws=rates(len(own_drop_draws), len(draw_set)),
            rate_draws_with_drop_per_basic_dontsuka=rates(len(own_drop_draws), len(own_don)),
            share_opponent_drop=rates(opp_drop, per_opponent),
            share_opponent_maintain=rates(opp_same, per_opponent),
            rank_maintenance_numerator=maintenance, rank_maintenance_denominator=den,
            rank_maintenance_rate=rates(maintenance, den),
            ron_avoidance_numerator=avoided, ron_avoidance_denominator=den,
            ron_avoidance_rate=rates(avoided, den),
            actual_ron_numerator=actual_ron_count, actual_ron_denominator=den,
            actual_ron_rate=rates(actual_ron_count, den),
            top_fall_risk_count="", last_fall_risk_count="",
            top_last_risk_definition_status="not uniquely specified in origin")
        player_scope_rows.append(row)
        for width in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            row[f"rank_drop_{width:.1f}_count"] = widths[width]

    # Build combined rows from numerators and denominators; never average rates.
    all_scope_rows = []
    group_keys = sorted({(r["scope"], r["season_start_year"], r["stage"]) for r in player_scope_rows})
    for kind, season, stage in group_keys:
        members = [r for r in player_scope_rows if (r["scope"], r["season_start_year"], r["stage"]) == (kind, season, stage)]
        sum_fields = ["all_draw_count", "basic_dontsuka_draw_count", "per_opponent_dontsuka_count",
                      "opponent_rank_drop_count", "opponent_rank_maintain_count",
                      "draw_level_any_opponent_drop_count", "head_bump_draw_count", "head_bump_rank_drop_count",
                      "rank_maintenance_numerator", "rank_maintenance_denominator", "ron_avoidance_numerator",
                      "ron_avoidance_denominator", "actual_ron_numerator", "actual_ron_denominator"]
        row = {"scope":kind,"season_start_year":season,"stage":stage,"player_id":"","player_name":"全選手合算"}
        row.update({k:sum(int(x[k]) for x in members) for k in sum_fields})
        row["rate_drop_per_all_draws"] = rates(row["draw_level_any_opponent_drop_count"], row["all_draw_count"])
        row["rate_draws_with_drop_per_basic_dontsuka"] = rates(row["draw_level_any_opponent_drop_count"],row["basic_dontsuka_draw_count"])
        row["share_opponent_drop"] = rates(row["opponent_rank_drop_count"],row["per_opponent_dontsuka_count"])
        row["share_opponent_maintain"] = rates(row["opponent_rank_maintain_count"],row["per_opponent_dontsuka_count"])
        row["rank_maintenance_rate"] = rates(row["rank_maintenance_numerator"],row["rank_maintenance_denominator"])
        row["ron_avoidance_rate"] = rates(row["ron_avoidance_numerator"],row["ron_avoidance_denominator"])
        row["actual_ron_rate"] = rates(row["actual_ron_numerator"],row["actual_ron_denominator"])
        row["top_fall_risk_count"] = row["last_fall_risk_count"] = ""
        row["top_last_risk_definition_status"] = "not uniquely specified in origin"
        for width in [0.5,1.0,1.5,2.0,2.5,3.0]:
            field=f"rank_drop_{width:.1f}_count";row[field]=sum(int(x.get(field,0)) for x in members)
        all_scope_rows.append(row)

    # Reconstruct the separate event-unit tables directly from their defining rows.
    draw_rows=[]
    for eid,d in sorted(draw_class.items()):
        draw_rows.append(dict(draw_event_id=eid, drawer_player_id=d["drawer"],
            game_id=dimensions[eid]["game_id"], kyoku_id=dimensions[eid]["kyoku_id"],
            opponent_count=d["target_count"], any_opponent_rank_drop=int(d["down"]),
            any_opponent_rank_maintain=int(d["same"]),
            head_bump_rank_drop=int(any(int(r["draw_event_id"])==eid and float(r["rank_drop"])>0 for r in head_rows))))

    # Deterministic real examples spanning important branches.
    examples=[]
    selector=["first_drop_event_id","player_id","kyoku_id"]
    for kind, pred in [("rank_maintained",lambda r:r["rank_maintained_or_improved"]==1 and r["actual_ron"]==0),
                       ("ron_but_rank_maintained",lambda r:r["rank_maintained_or_improved"]==1 and r["actual_ron"]==1),
                       ("no_ron_but_rank_dropped",lambda r:r["rank_maintained_or_improved"]==0 and r["actual_ron"]==0),
                       ("actual_ron_and_rank_dropped",lambda r:r["rank_maintained_or_improved"]==0 and r["actual_ron"]==1)]:
        matches=[r for r in kyoku_details if pred(r)]
        if matches:
            examples.append(dict(category=kind,**matches[0]))
    for eid,d in sorted(draw_class.items()):
        if d["target_count"] > 1 and d["down"] and d["same"]:
            examples.append(dict(category="same_draw_both_drop_and_maintain",draw_event_id=eid,
                player_id=d["drawer"],opponent_count=d["target_count"],
                opponent_drop_rows=sum(float(r["rank_drop"])>0 for r in by_draw[eid]),
                opponent_maintain_rows=sum(float(r["rank_drop"])==0 for r in by_draw[eid])))
            break
    if len(examples)<4:
        raise ValueError("insufficient real-play examples for independent result branches")

    # Cross-check aggregate conservation and decomposition.
    if sum(r["opponent_rank_drop_count"] for r in player_scope_rows if r["scope"]=="all_period") != 13170:
        raise ValueError("player aggregation of per-opponent rank drops is not conserved")
    if sum(r["opponent_rank_maintain_count"] for r in player_scope_rows if r["scope"]=="all_period") != 14890:
        raise ValueError("player aggregation of per-opponent rank maintenance is not conserved")
    if sum(r["draw_level_any_opponent_drop_count"] for r in player_scope_rows if r["scope"]=="all_period") != sum(d["down"] for d in draw_class.values()):
        raise ValueError("draw-unit rank-drop aggregation is not conserved")
    if sum(r["rank_maintenance_denominator"] for r in player_scope_rows if r["scope"]=="all_period") != len(kyoku_details):
        raise ValueError("player kyoku deduplication is not conserved")
    if sum(r["ron_avoidance_numerator"]+r["actual_ron_numerator"] for r in player_scope_rows if r["scope"]=="all_period") != len(kyoku_details):
        raise ValueError("actual ron and avoidance do not partition qualifying kyoku")

    fields=list(player_scope_rows[0])
    write_csv(args.out/"rank_drop_derived_by_player.csv", player_scope_rows, fields)
    write_csv(args.out/"rank_drop_derived_all_scopes.csv", all_scope_rows, list(all_scope_rows[0]))
    write_csv(args.out/"rank_drop_draw_unit.csv", draw_rows, list(draw_rows[0]))
    write_csv(args.out/"rank_drop_kyoku_details.csv", kyoku_details, list(kyoku_details[0]))
    rank_rows=[{k:r[k] for k in ["scope","season_start_year","stage","player_id","player_name",
        "rank_maintenance_numerator","rank_maintenance_denominator","rank_maintenance_rate"]} for r in player_scope_rows]
    avoid_rows=[{k:r[k] for k in ["scope","season_start_year","stage","player_id","player_name",
        "ron_avoidance_numerator","ron_avoidance_denominator","ron_avoidance_rate",
        "actual_ron_numerator","actual_ron_denominator","actual_ron_rate"]} for r in player_scope_rows]
    write_csv(args.out/"rank_maintenance_by_player.csv",rank_rows,list(rank_rows[0]))
    write_csv(args.out/"ron_avoidance_by_player.csv",avoid_rows,list(avoid_rows[0]))
    example_fields=list(dict.fromkeys(k for r in examples for k in r))
    write_csv(args.out/"real_play_examples.csv",examples,example_fields)
    write_csv(args.out/"discrepancies.csv",[],["check","expected","actual","status","detail"])

    # The origin lists top/last transition counts but does not define the tie cases
    # or transition threshold. Retain these as explicitly unmeasured, not guessed.
    counts=dict(opponent_rows=len(source),opponent_rank_drop=len(down_rows),
        opponent_rank_maintain=len(same_rows),draws_with_any_opponent_rank_drop=sum(d["down"] for d in draw_class.values()),
        head_bump_draws=len(head_rows),head_bump_rank_drop=head_down,
        rank_drop_kyoku=len(kyoku_details),rank_maintenance=sum(r["rank_maintained_or_improved"] for r in kyoku_details),
        rank_maintenance_rate=rates(sum(r["rank_maintained_or_improved"] for r in kyoku_details),len(kyoku_details)),
        actual_ron_kyoku=sum(r["actual_ron"] for r in kyoku_details),ron_avoided_kyoku=sum(r["ron_avoided"] for r in kyoku_details),
        ron_avoidance_rate=rates(sum(r["ron_avoided"] for r in kyoku_details),len(kyoku_details)),
        all_draws=len(draw_meta),top_fall_risk_count=None,last_fall_risk_count=None,
        top_last_risk_definition_status="not uniquely specified in origin")
    manifest=dict(scope="Stage 3B only",status="complete_with_origin_definition_gap",
        database=db_manifest,database_sha256=db_sha,stage3a_zip_sha256=STAGE3A_SHA,stage2b_zip_sha256=STAGE2B_SHA,
        stage3a_manifest_sha256=hashlib.sha256(z3a.read("manifest.json")).hexdigest(),
        stage2b_manifest_sha256=hashlib.sha256(z2b.read("manifest.json")).hexdigest(),
        fixed_reference_counts=EXPECTED,counts_3b=counts,scope_rows_player=len(player_scope_rows),
        scope_rows_all_players=len(all_scope_rows),release_id=RELEASE,commit=os.getenv("GITHUB_SHA"),
        run_id=os.getenv("GITHUB_RUN_ID"),checks={"stage2b_draw_event_coverage":True,
        "stage2b_kyoku_end_score_and_average_rank":True,"stage3a_opponent_rows":True,
        "single_double_triple_partition":True,"head_bump_separate":True,
        "first_rank_drop_baseline":True,"one_player_kyoku_dedup":True,
        "actual_ron_including_chankan_query":"event.type=ron, agari_event.target_player_id; causal tile attribution not implemented",
        "rank_and_ron_independent":True,"grouped_sums_reconcile":True,
        "top_last_risk_count":"unresolved; not calculated"})
    manifest["outputs"]={p.name:hashlib.file_digest(p.open("rb"),"sha256").hexdigest()
                          for p in sorted(args.out.iterdir()) if p.is_file() and p.name!="manifest.json"}
    (args.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(jdump(manifest),flush=True)


if __name__ == "__main__":
    main()
