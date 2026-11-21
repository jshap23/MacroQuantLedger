"""Standalone validation for My Views levels, freshness, streak, bests, deck links, and cleanup.

Run with: python validate_view_levels.py

Pure in-memory checks: no network, no files, and the live data/ directory is
never touched.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from models.interview import InterviewAnswer, InterviewQuestion, InterviewSession
from models.schema import AppState, TopicView, ViewFact, ViewPoint
from services.topic_views import RECALL_RATINGS, split_point
from services.session_cleanup import stale_active_sessions
from services.view_progress import (
    ACTIVITY_CAP, activity_dates, band_index, deck_for_link, is_personal_best, note_activity,
    weekly_streak,
)
from services.view_levels import (
    confirmed_at,
    days_since_confirmed,
    freshness_ratio,
    view_level,
)

NOW = datetime.now(timezone.utc)
_failures: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        _failures.append(name)


def make_view(
    *,
    facts: int = 0,
    counter: str = "",
    bottom: str = "A view.",
    titled: int = 3,
    priority: str = "Normal",
) -> TopicView:
    points = [ViewPoint(title=f"Point {i}") for i in range(titled)]
    for i in range(facts):
        points[i % max(1, len(points))].facts.append(ViewFact(text=f"fact {i}"))
    return TopicView(
        name="V",
        bottom_line=bottom,
        points=points,
        counterargument=counter,
        priority=priority,
    )


def make_session(
    view: TopicView,
    score: int,
    *,
    style: str = "Deliver",
    model: str = "g1",
    rubric: str = "argument-v3",
    days_ago: int = 1,
    status: str = "completed",
    retry: bool = False,
) -> InterviewSession:
    answer = InterviewAnswer(
        text="a", score=score, is_retry=retry, evaluation_status="ok"
    )
    return InterviewSession(
        mode="Discussion",
        topic="V",
        rubric_id=rubric,
        model=model,
        view_ids=[view.id],
        practice_style=style,
        status=status,
        completed_at=NOW - timedelta(days=days_ago) if status == "completed" else None,
        questions=[InterviewQuestion(text="q", answers=[answer])],
    )


def main() -> int:
    blank = make_view(bottom="")
    check("no bottom line is Blank", view_level(blank, []).level == 0)
    check(
        "one titled point is still Blank",
        view_level(make_view(titled=1), []).level == 0,
    )
    check(
        "bottom line and two points is Sketch",
        view_level(make_view(titled=2), []).level == 1,
    )
    check(
        "counterargument plus two facts is Supported",
        view_level(make_view(facts=2, counter="c"), []).level == 2,
    )
    check(
        "facts without a counterargument stay Sketch",
        view_level(make_view(facts=3), []).level == 1,
    )

    v = make_view()
    check(
        "one scored rep is not Rehearsed",
        view_level(v, [make_session(v, 7)]).level == 1,
    )
    check(
        "two reps, latest 5, is Rehearsed",
        view_level(
            v, [make_session(v, 3, days_ago=3), make_session(v, 5, days_ago=1)]
        ).level
        == 3,
    )
    check(
        "two reps, latest below 5, is not Rehearsed",
        view_level(
            v, [make_session(v, 8, days_ago=3), make_session(v, 4, days_ago=1)]
        ).level
        == 1,
    )
    check(
        "Rehearsed does not need optional facts",
        view_level(
            v, [make_session(v, 5, days_ago=2), make_session(v, 6, days_ago=1)]
        ).level
        == 3,
    )

    check(
        "Defend at 7 on top of Rehearsed is Battle-tested",
        view_level(
            v,
            [
                make_session(v, 5, days_ago=3),
                make_session(v, 7, style="Defend", days_ago=1),
            ],
        ).level
        == 4,
    )
    check(
        "Defend at 6 is only Rehearsed",
        view_level(
            v,
            [
                make_session(v, 5, days_ago=3),
                make_session(v, 6, style="Defend", days_ago=1),
            ],
        ).level
        == 3,
    )
    check(
        "a lone Defend 8 is not Battle-tested without two reps",
        view_level(v, [make_session(v, 8, style="Defend")]).level == 1,
    )
    check(
        "Deliver 8 twice is Rehearsed, not Battle-tested",
        view_level(
            v, [make_session(v, 8, days_ago=2), make_session(v, 8, days_ago=1)]
        ).level
        == 3,
    )

    # Grader isolation: reps by different graders never combine, and a new
    # grader never removes a level already earned under another.
    check(
        "reps from two graders do not combine",
        view_level(
            v,
            [
                make_session(v, 6, model="g1", days_ago=2),
                make_session(v, 6, model="g2", days_ago=1),
            ],
        ).level
        == 1,
    )
    earned = [
        make_session(v, 5, model="g1", days_ago=5),
        make_session(v, 6, model="g1", days_ago=4),
    ]
    check(
        "a low rep under another grader does not remove the level",
        view_level(v, earned + [make_session(v, 2, model="g2", days_ago=1)]).level == 3,
    )
    check(
        "rubrics are kept apart",
        view_level(
            v,
            [
                make_session(v, 6, rubric="shared-v2", days_ago=2),
                make_session(v, 6, days_ago=1),
            ],
        ).level
        == 1,
    )

    check(
        "retries do not count",
        view_level(
            v,
            [
                make_session(v, 6, days_ago=2),
                make_session(v, 6, retry=True, days_ago=1),
            ],
        ).level
        == 1,
    )
    check(
        "abandoned sessions do not count",
        view_level(
            v, [make_session(v, 6, days_ago=2), make_session(v, 6, status="abandoned")]
        ).level
        == 1,
    )
    check(
        "unanchored and custom rubrics do not count",
        view_level(
            v,
            [
                make_session(v, 6, rubric="unanchored", days_ago=2),
                make_session(v, 6, rubric="custom", days_ago=1),
            ],
        ).level
        == 1,
    )
    other = make_view()
    check(
        "another View's reps are ignored",
        view_level(
            v, [make_session(other, 6, days_ago=2), make_session(other, 6, days_ago=1)]
        ).level
        == 1,
    )
    check(
        "practice cannot lift a Blank View",
        view_level(
            blank,
            [make_session(blank, 6, days_ago=2), make_session(blank, 6, days_ago=1)],
        ).level
        == 0,
    )

    # Freshness and Still holds.
    old = make_view(priority="Normal")
    old.updated_at = NOW - timedelta(days=42)
    check("age is measured from updated_at", days_since_confirmed(old, NOW) == 42)
    check("Normal cadence is 21 days", abs(freshness_ratio(old, NOW) - 2.0) < 0.05)
    old.reviewed_at = NOW - timedelta(days=2)
    check(
        "Still holds resets age without touching updated_at",
        days_since_confirmed(old, NOW) == 2 and (NOW - old.updated_at).days == 42,
    )
    core = make_view(priority="Core")
    core.updated_at = NOW - timedelta(days=14)
    check("Core cadence is 7 days", abs(freshness_ratio(core, NOW) - 2.0) < 0.05)
    naive = make_view()
    naive.updated_at = datetime.now() - timedelta(days=3)
    check("naive timestamps are handled", confirmed_at(naive).tzinfo is not None)

    # Deck point splitting: claim first, detail folded away.
    lead, rest = split_point(
        "**Labor demand is weak.** JOLTS hiring is 3.4% and quits are 2.0%."
    )
    check(
        "bold lead is the claim, remainder is the detail",
        lead == "Labor demand is weak." and rest.startswith("JOLTS hiring"),
    )
    check(
        "short plain point has no detail",
        split_point("Short point.") == ("Short point.", ""),
    )
    long_point = (
        "US exceptionalism continues to support the dollar cyclically. "
        + "US growth has held up better than most. " * 5
    )
    lead, rest = split_point(long_point)
    check(
        "long plain point leads with its first sentence",
        lead == "US exceptionalism continues to support the dollar cyclically."
        and rest.startswith("US growth"),
    )
    check(
        "nothing is lost by splitting",
        (lead + " " + rest).strip() == long_point.strip(),
    )
    check(
        "a tiny first sentence is not split off",
        split_point("Yes. " + "Because the mechanism is long. " * 8)[1] == "",
    )
    check("empty point is safe", split_point("   ") == ("", ""))
    check(
        "recall ratings are the three expected values",
        RECALL_RATINGS == ("Nailed", "Shaky", "Blanked"),
    )
    check(
        "old state without recall fields loads with defaults",
        make_view().practice.recall_last == ""
        and make_view().practice.recall_at is None,
    )

    # Weekly streak: forgiving of an empty current week, ended by a missed full week.
    wed = date(2026, 11, 18)  # a Wednesday
    week = lambda n: wed - timedelta(days=7 * n)  # noqa: E731
    check("no activity is a zero streak", weekly_streak([], wed) == 0)
    check("activity only this week is a streak of one", weekly_streak([wed], wed) == 1)
    check("three consecutive weeks counts three",
          weekly_streak([week(0), week(1), week(2)], wed) == 3)
    check("an empty current week does not break the streak",
          weekly_streak([week(1), week(2)], wed) == 2)
    check("a missed full week ends the streak",
          weekly_streak([week(0), week(2), week(3)], wed) == 1)
    check("two missed weeks leave nothing", weekly_streak([week(3), week(4)], wed) == 0)
    check("several days in one week count once",
          weekly_streak([wed, wed - timedelta(days=1), wed - timedelta(days=2)], wed) == 1)
    check("weeks start on Monday",
          weekly_streak([date(2026, 11, 15), date(2026, 11, 16)], date(2026, 11, 16)) == 2)

    state = AppState()
    note_activity(state, wed)
    note_activity(state, wed)
    check("noting activity twice on a day records one entry", state.activity_days == ["2026-11-18"])
    for offset in range(ACTIVITY_CAP + 20):
        note_activity(state, date(2025, 1, 1) + timedelta(days=offset))
    check("the activity list is capped", len(state.activity_days) == ACTIVITY_CAP)
    messy = AppState(activity_days=["2026-11-18", "not-a-date"])
    rep_view = make_view()
    rep = make_session(rep_view, 5, days_ago=3)
    dates = activity_dates(messy, [rep, make_session(rep_view, 5, status="abandoned")])
    check("activity merges app days and completed reps, ignoring junk and abandoned",
          dates == {date(2026, 11, 18), (NOW - timedelta(days=3)).astimezone().date()})

    # Personal best: a higher rubric band than any earlier like-for-like rep.
    check("band index follows the rubric bands",
          [band_index(s) for s in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)] == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
    pv = make_view()
    old = make_session(pv, 5, days_ago=5)
    check("a higher band than before is a best",
          is_personal_best(make_session(pv, 7, days_ago=1), [old]))
    check("the same band is not a best",
          not is_personal_best(make_session(pv, 6, days_ago=1), [old]))
    check("a first rep is not a best", not is_personal_best(make_session(pv, 9, days_ago=1), []))
    check("a lower band is not a best",
          not is_personal_best(make_session(pv, 3, days_ago=1), [old]))
    check("a different grader's earlier rep is ignored", is_personal_best(
        make_session(pv, 7, days_ago=1), [make_session(pv, 9, model="g2", days_ago=5)]) is False)
    check("a different practice style is ignored", is_personal_best(
        make_session(pv, 7, days_ago=1), [make_session(pv, 9, style="Defend", days_ago=5)]) is False)
    check("a best needs a lower or equal earlier rep under the same grader", is_personal_best(
        make_session(pv, 7, days_ago=1),
        [make_session(pv, 9, model="g2", days_ago=6), make_session(pv, 4, days_ago=5)]))
    check("later reps do not count as earlier ones", not is_personal_best(
        make_session(pv, 7, days_ago=3), [make_session(pv, 3, days_ago=1)]))
    other_view = make_view()
    check("another View's reps are ignored", not is_personal_best(
        make_session(pv, 7, days_ago=1), [make_session(other_view, 3, days_ago=5)]))
    check("a retry-only session is never a best", not is_personal_best(
        make_session(pv, 9, retry=True, days_ago=1), [old]))

    # Deep links: ?deck=<key> picks Views and an order; anything unknown selects nothing.
    core_view, shaky_view, blank_view, plain_view = make_view(priority="Core"), make_view(), make_view(), make_view()
    shaky_view.practice.recall_last = "Shaky"
    blank_view.practice.recall_last = "Blanked"
    nailed_view = make_view()
    nailed_view.practice.recall_last = "Nailed"
    pool = [core_view, shaky_view, blank_view, plain_view, nailed_view]
    check("all keeps every View in the listed order", deck_for_link(pool, "all") == (pool, "listed"))
    check("stale keeps every View but asks for the stalest-first order",
          deck_for_link(pool, "stale") == (pool, "stale"))
    check("shaky selects Shaky and Blanked only",
          deck_for_link(pool, "shaky")[0] == [shaky_view, blank_view])
    check("core selects Core priority only", deck_for_link(pool, "core")[0] == [core_view])
    check("keys are trimmed and case-insensitive", deck_for_link(pool, " SHAKY ")[0] == [shaky_view, blank_view])
    check("an unknown or empty key selects nothing",
          deck_for_link(pool, "nonsense")[0] == [] and deck_for_link(pool, "")[0] == [])
    check("a filter with no matches is empty", deck_for_link([plain_view], "shaky")[0] == [])
    check("the returned list is a copy", deck_for_link(pool, "all")[0] is not pool)

    # Stale unfinished sessions: only active sessions older than the cutoff.
    def raw_session(status: str, days_old: int) -> InterviewSession:
        return InterviewSession(mode="Discussion", topic="V", status=status,
                                started_at=NOW - timedelta(days=days_old))

    old_active, new_active = raw_session("active", 8), raw_session("active", 2)
    old_done, old_abandoned = raw_session("completed", 30), raw_session("abandoned", 30)
    picked = stale_active_sessions([old_active, new_active, old_done, old_abandoned], 7, NOW)
    check("only an old active session is stale", picked == [old_active])
    check("a recent active session is left alone", new_active not in picked)
    naive = InterviewSession(mode="Discussion", topic="V", status="active",
                             started_at=(NOW - timedelta(days=20)).replace(tzinfo=None))
    check("naive start times are handled", stale_active_sessions([naive], 7, NOW) == [naive])
    check("nothing stale gives an empty list", stale_active_sessions([], 7, NOW) == [])

    # Launcher flag and URL.
    import launch
    check("no flag opens the plain app", launch.parse_args([]).deck is None
          and launch.build_url(None) == launch.URL)
    check("a bare --deck means all", launch.parse_args(["--deck"]).deck == "all")
    check("--deck shaky is passed through", launch.parse_args(["--deck", "shaky"]).deck == "shaky")
    check("the deck URL carries the query", launch.build_url("shaky") == launch.URL + "/?deck=shaky")
    try:
        launch.parse_args(["--deck", "bogus"])
        rejected = False
    except SystemExit:
        rejected = True
    check("an unknown deck choice is rejected", rejected)

    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed.")
        return 1
    print("All view-level checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
