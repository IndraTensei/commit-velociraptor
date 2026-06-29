#!/usr/bin/env python3
"""
commit-velociraptor — Speed through your Git history.

Analyzes commit velocity, streaks, patterns per day-of-week & hour-of-day,
and renders a beautiful terminal heatmap. Think "GitHub contribution graph"
but for ANY local repo, right in your terminal, no browser needed.
"""

import subprocess
import sys
import os
import argparse
import re
import json
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

__version__ = "1.3.0"

# ── ANSI helpers ──────────────────────────────────────────────────────────

class Color:
    """ANSI escape shortcuts."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    PURPLE = "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    BG_CYAN   = "\033[46m\033[30m"
    BG_YELLOW = "\033[43m\033[30m"
    BG_GREEN  = "\033[42m\033[30m"

LEVEL_COLORS = [
    "\033[48;2;14;16;23m",   # 0  — empty
    "\033[48;2;16;32;56m",   # 1  — low
    "\033[48;2;21;55;90m",   # 2
    "\033[48;2;28;73;135m",   # 3
    "\033[48;2;40;99;170m",   # 4
    "\033[48;2;59;140;218m",   # 5  — high
    "\033[48;2;94;186;255m",   # 6  — very high
]
LEVEL_FG_RESET = "\033[49m\033[39m"


# ── git data extraction ───────────────────────────────────────────────────

def run_git(repo_path: str, *args) -> str:
    """Run a git command and return stdout as string."""
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"{Color.RED}Error: {result.stderr.strip()}{Color.RESET}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def get_commits(repo_path: str, days: Optional[int] = None,
                author: Optional[str] = None,
                since: Optional[str] = None,
                until: Optional[str] = None) -> list[dict]:
    """
    Fetch commit log as a list of dicts with keys:
      hash, author, email, date (datetime), subject
    """
    sep = "<|COMMIT_SEP|>"
    fmt_string = f"%H{sep}%an{sep}%ae{sep}%aI{sep}%s"
    cmd = ["log", f"--pretty=format:{fmt_string}", "--date=iso", "-n", "10000"]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    if days and not since:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        cmd += ["--since", cutoff]
    if author:
        cmd += ["--author", author]

    raw = run_git(repo_path, *cmd).strip()
    if not raw:
        return []

    commits = []
    for entry in raw.split("\n"):
        parts = entry.split(sep, 4)
        if len(parts) < 5:
            continue
        hash_, author_name, email, date_str, subject = parts
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            continue
        commits.append({
            "hash": hash_[:8],
            "author": author_name,
            "email": email,
            "date": dt,
            "subject": subject,
        })
    return commits


def get_file_stats(repo_path: str, days: Optional[int] = None,
                   author: Optional[str] = None,
                   since: Optional[str] = None,
                   until: Optional[str] = None) -> Counter:
    """
    Count how many commits touched each file.
    Uses git log --numstat to find files changed per commit.
    """
    cmd = ["log", "--pretty=format:COMMIT:%H", "--numstat", "-n", "5000"]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    if days and not since:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        cmd += ["--since", cutoff]
    if author:
        cmd += ["--author", author]

    try:
        raw = run_git(repo_path, *cmd)
    except SystemExit:
        return Counter()

    file_counts: Counter = Counter()
    for line in raw.splitlines():
        if line.startswith("COMMIT:") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            filepath = parts[2]
            # Skip binary files and rename targets
            if filepath.startswith("-") or "=>" in filepath:
                continue
            # For renames, take the new path
            file_counts[filepath] += 1

    return file_counts


def get_branch_info(repo_path: str) -> list[dict]:
    """
    Get information about local branches:
    name, last commit date, is current, commit count ahead of main/master.
    """
    try:
        # Get current branch
        current = run_git(repo_path, "branch", "--show-current").strip()

        # Get all local branches with last commit date
        sep = "<|BRANCH_SEP|>"
        raw = run_git(
            repo_path, "for-each-ref",
            f"--format=%(refname:short){sep}%(authordate:iso){sep}%(subject)",
            "refs/heads/"
        ).strip()

        if not raw:
            return []

        # Get the default branch (main or master)
        default_branch = None
        for candidate in ["main", "master"]:
            try:
                run_git(repo_path, "rev-parse", "--verify", candidate)
                default_branch = candidate
                break
            except SystemExit:
                continue

        branches = []
        for line in raw.splitlines():
            parts = line.split(sep, 2)
            if len(parts) < 3:
                continue
            name, date_str, subject = parts
            try:
                dt = datetime.fromisoformat(date_str)
                # Normalize to offset-naive for comparison with now()
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
            except ValueError:
                continue

            ahead = 0
            if default_branch and name != default_branch:
                try:
                    count_raw = run_git(
                        repo_path, "rev-list", "--count",
                        f"{default_branch}..{name}"
                    ).strip()
                    ahead = int(count_raw)
                except (SystemExit, ValueError):
                    ahead = -1  # diverged or error

            branches.append({
                "name": name,
                "date": dt,
                "subject": subject[:50],
                "is_current": name == current,
                "ahead": ahead,
            })

        # Sort by most recent first
        branches.sort(key=lambda b: b["date"], reverse=True)
        return branches[:15]  # Top 15 branches

    except SystemExit:
        return []


# ── analysis ──────────────────────────────────────────────────────────────

def compute_heatmap_data(commits: list[dict]) -> dict:
    """Build a {date_str: count} dict keyed by YYYY-MM-DD."""
    counter: Counter = Counter()
    for c in commits:
        key = c["date"].strftime("%Y-%m-%d")
        counter[key] += 1
    return counter


def compute_streaks(day_counts: dict) -> tuple[int, int, int, str, str]:
    """
    Returns (current_streak, longest_streak, total_active_days, longest_start, longest_end).
    Streak = consecutive days with >= 1 commit.
    """
    if not day_counts:
        return 0, 0, 0, "", ""

    dates = sorted(day_counts.keys())
    longest = curr = 1
    longest_start = curr_start = dates[0]
    longest_end = dates[0]

    for i in range(1, len(dates)):
        prev = datetime.strptime(dates[i - 1], "%Y-%m-%d")
        this = datetime.strptime(dates[i], "%Y-%m-%d")
        if (this - prev).days == 1:
            curr += 1
            if curr > longest:
                longest = curr
                longest_end = dates[i]
                longest_start = curr_start
        else:
            curr = 1
            curr_start = dates[i]

    # Current streak (from today backwards)
    today = datetime.now().date()
    current_streak = 0
    check = today
    while check.strftime("%Y-%m-%d") in day_counts:
        current_streak += 1
        check -= timedelta(days=1)

    return current_streak, longest, len(day_counts), longest_start, longest_end


def compute_time_stats(commits: list[dict], use_local: bool = False) -> dict:
    """Stats broken down by day-of-week, hour-of-day."""
    dow_counts = Counter()
    hour_counts = Counter()
    for c in commits:
        dt = c["date"]
        if use_local and dt.tzinfo is not None:
            dt = dt.astimezone()
        dow_counts[dt.strftime("%A")] += 1
        hour_counts[dt.hour] += 1
    return {"dow": dict(dow_counts), "hour": dict(hour_counts)}


def compute_author_stats(commits: list[dict]) -> dict:
    """Commits per author."""
    counts = Counter()
    for c in commits:
        counts[c["author"]] += 1
    return dict(counts.most_common(10))


def compute_commit_verbs(commits: list[dict]) -> list[tuple[str, int]]:
    """
    Extract the most common 'verbs' (first word) from commit subjects.
    Conventional commit prefixes like 'feat:', 'fix:' are extracted.
    """
    verb_counts: Counter = Counter()

    # Common conventional commit prefixes to recognize
    cc_prefixes = re.compile(
        r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)'
        r'(?:\([^)]+\))?:',
        re.IGNORECASE
    )

    for c in commits:
        subject = c["subject"].strip()
        # Check for conventional commit prefix first
        cc_match = cc_prefixes.match(subject)
        if cc_match:
            verb = cc_match.group(1).lower()
            verb_counts[verb] += 1
            continue

        # Otherwise, take the first word
        words = subject.split()
        if words:
            verb = words[0].lower().rstrip(":!.,")
            # Normalize common variants
            verb = verb.rstrip("ed").rstrip("s") if len(verb) > 4 else verb
            verb_counts[verb] += 1

    return verb_counts.most_common(12)


def compute_quality_score(commits: list[dict]) -> dict:
    """
    Analyze commit message quality and return a score breakdown.

    Scoring criteria:
    - Conventional commit prefix: +30 points (% of commits using conventional format)
    - Descriptive length (10-72 chars): +25 points
    - No generic messages (e.g. "update", "fix"): +20 points
    - Imperative mood detection: +15 points
    - Contains issue/ticket reference: +10 points
    """
    if not commits:
        return {"overall": 0, "details": {}}

    total = len(commits)

    # Conventional commit adherence
    cc_pattern = re.compile(
        r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)'
        r'(?:\([^)]+\))?:',
        re.IGNORECASE
    )
    cc_count = sum(1 for c in commits if cc_pattern.match(c["subject"].strip()))
    cc_pct = cc_count / total
    cc_score = round(cc_pct * 30, 1)

    # Descriptive length (10-72 chars is the sweet spot)
    good_length_count = sum(
        1 for c in commits
        if 10 <= len(c["subject"]) <= 72
    )
    length_pct = good_length_count / total
    length_score = round(length_pct * 25, 1)

    # No generic/vague messages
    generic_patterns = re.compile(
        r'^(update|fix|changed|changes|wip|temp|test|stuff|misc|'
        r'asdf|foo|bar|lol|oops|oopsie|tmp|draft|save|checkpoint)$',
        re.IGNORECASE
    )
    non_generic = sum(
        1 for c in commits
        if not generic_patterns.match(c["subject"].strip())
    )
    non_generic_pct = non_generic / total
    non_generic_score = round(non_generic_pct * 20, 1)

    # Imperative mood (starts with a verb-like word, not past tense)
    imperative_starters = re.compile(
        r'^(add|remove|create|delete|implement|refactor|fix|update|'
        r'improve|optimize|rename|move|merge|bump|release|document|'
        r'simplify|extract|replace|enable|disable|support|allow|prevent|'
        r'feat|chore|style|test|build|ci|perf|revert|docs)',
        re.IGNORECASE
    )
    imperative_count = sum(
        1 for c in commits
        if imperative_starters.match(c["subject"].strip())
    )
    imperative_pct = imperative_count / total
    imperative_score = round(imperative_pct * 15, 1)

    # Issue/ticket reference
    issue_pattern = re.compile(r'#(\d+)|([A-Z][A-Z]+-\d+)')
    issue_count = sum(
        1 for c in commits
        if issue_pattern.search(c["subject"])
    )
    issue_pct = issue_count / total
    issue_score = round(issue_pct * 10, 1)

    overall = round(cc_score + length_score + non_generic_score + imperative_score + issue_score, 1)

    return {
        "overall": overall,
        "grade": _score_to_grade(overall),
        "details": {
            "conventional_commits": {
                "score": cc_score,
                "max": 30,
                "pct": round(cc_pct * 100, 1),
                "count": cc_count,
            },
            "message_length": {
                "score": length_score,
                "max": 25,
                "pct": round(length_pct * 100, 1),
                "count": good_length_count,
            },
            "no_generic_messages": {
                "score": non_generic_score,
                "max": 20,
                "pct": round(non_generic_pct * 100, 1),
                "count": non_generic,
            },
            "imperative_mood": {
                "score": imperative_score,
                "max": 15,
                "pct": round(imperative_pct * 100, 1),
                "count": imperative_count,
            },
            "issue_references": {
                "score": issue_score,
                "max": 10,
                "pct": round(issue_pct * 100, 1),
                "count": issue_count,
            },
        },
    }


def _score_to_grade(score: float) -> str:
    """Convert a 0-100 score to a letter grade."""
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 50:
        return "D"
    else:
        return "F"


def compute_velocity_trend(commits: list[dict]) -> dict:
    """
    Compare the first half vs second half of the commit period
    to determine if velocity is trending up or down.
    """
    if not commits or len(commits) < 4:
        return {"trend": "insufficient_data", "change_pct": 0, "direction": "→"}

    # Sort commits by date
    sorted_commits = sorted(commits, key=lambda c: c["date"])
    mid = len(sorted_commits) // 2

    first_half = sorted_commits[:mid]
    second_half = sorted_commits[mid:]

    # Calculate the date span of each half
    def date_range_days(clist):
        if len(clist) < 2:
            return 1
        delta = clist[-1]["date"] - clist[0]["date"]
        return max(delta.days, 1)

    first_days = date_range_days(first_half)
    second_days = date_range_days(second_half)

    first_rate = len(first_half) / first_days
    second_rate = len(second_half) / second_days

    if first_rate == 0:
        change_pct = 100.0 if second_rate > 0 else 0.0
    else:
        change_pct = round((second_rate - first_rate) / first_rate * 100, 1)

    if change_pct > 10:
        trend = "accelerating"
        direction = "↑"
    elif change_pct < -10:
        trend = "decelerating"
        direction = "↓"
    else:
        trend = "stable"
        direction = "→"

    return {
        "trend": trend,
        "change_pct": change_pct,
        "direction": direction,
        "first_half_rate": round(first_rate, 2),
        "second_half_rate": round(second_rate, 2),
    }


# ── export ─────────────────────────────────────────────────────────────────

def export_json(repo_path: str, days: Optional[int],
                author: Optional[str], all_time: bool,
                since: Optional[str], until: Optional[str],
                show_files: bool = True) -> str:
    """Export all stats as a JSON string."""
    effective_days = None if all_time else (days or 90)
    commits = get_commits(repo_path, days=effective_days, author=author,
                          since=since, until=until)
    if not commits:
        return json.dumps({"error": "No commits found for the given filters."})

    day_counts = compute_heatmap_data(commits)
    cur_streak, long_streak, active_days, ls_start, ls_end = compute_streaks(day_counts)
    time_stats = compute_time_stats(commits)
    author_stats = compute_author_stats(commits)
    verbs = compute_commit_verbs(commits)
    quality = compute_quality_score(commits)
    trend = compute_velocity_trend(commits)

    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_data = {d: time_stats["dow"].get(d, 0) for d in dow_order}
    hour_data = {f"{h:02d}:00": time_stats["hour"].get(h, 0) for h in range(24)}

    weekly_data: Counter = Counter()
    for c in commits:
        dt = c["date"]
        week_num = dt.isocalendar()[1]
        year = dt.isocalendar()[0]
        wk_key = f"{year}-W{week_num:02d}"
        weekly_data[wk_key] += 1
    recent_weeks = sorted(weekly_data.keys())[-12:]

    data = {
        "meta": {
            "tool": "commit-velociraptor",
            "version": __version__,
            "repo": os.path.abspath(repo_path),
            "generated_at": datetime.now().isoformat(),
        },
        "summary": {
            "total_commits": len(commits),
            "date_range": {
                "start": commits[-1]["date"].strftime("%Y-%m-%d"),
                "end": commits[0]["date"].strftime("%Y-%m-%d"),
            },
            "active_days": active_days,
            "current_streak": cur_streak,
            "longest_streak": long_streak,
            "longest_streak_range": {"start": ls_start, "end": ls_end},
            "avg_commits_per_active_day": round(len(commits) / max(active_days, 1), 1),
        },
        "by_day_of_week": dow_data,
        "by_hour": hour_data,
        "top_authors": author_stats,
        "commit_verbs": {verb: count for verb, count in verbs},
        "weekly_velocity": {wk: weekly_data[wk] for wk in recent_weeks},
        "quality_score": quality,
        "velocity_trend": trend,
    }

    if show_files:
        file_stats = get_file_stats(repo_path, days=effective_days, author=author,
                                    since=since, until=until)
        data["most_changed_files"] = [
            {"file": f, "commits": c} for f, c in file_stats.most_common(10)
        ]

    return json.dumps(data, indent=2)


def export_csv(repo_path: str, days: Optional[int],
               author: Optional[str], all_time: bool,
               since: Optional[str], until: Optional[str]) -> str:
    """Export per-commit data as CSV."""
    effective_days = None if all_time else (days or 90)
    commits = get_commits(repo_path, days=effective_days, author=author,
                          since=since, until=until)
    if not commits:
        return "hash,author,email,date,subject\n"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["hash", "author", "email", "date", "subject"])
    for c in commits:
        writer.writerow([
            c["hash"],
            c["author"],
            c["email"],
            c["date"].isoformat(),
            c["subject"],
        ])
    return buf.getvalue()


# ── compare ─────────────────────────────────────────────────────────────────

def print_compare(repo_path: str, author1: str, author2: str,
                  days: Optional[int], all_time: bool,
                  since: Optional[str], until: Optional[str]):
    """Compare two authors side-by-side."""
    effective_days = None if all_time else (days or 90)
    commits_a1 = get_commits(repo_path, days=effective_days, author=author1,
                             since=since, until=until)
    commits_a2 = get_commits(repo_path, days=effective_days, author=author2,
                             since=since, until=until)

    boundary = f"{Color.CYAN}{'─' * 60}{Color.RESET}"
    print(f"\n{Color.BOLD}{Color.PURPLE}  commit-velociraptor — Author Comparison{Color.RESET}")
    print(f"  {Color.DIM}{repo_path}{Color.RESET}")
    print(boundary)

    names = [author1, author2]
    commit_lists = [commits_a1, commits_a2]

    # Summary comparison
    print(f"\n  {Color.BOLD}Summary Comparison{Color.RESET}")
    print(f"  {'Metric':<28} {Color.BOLD}{names[0]:<16}{Color.RESET} {Color.BOLD}{names[1]:<16}{Color.RESET}")
    print(f"  {'─' * 56}")

    def get_stats(commits):
        if not commits:
            return (0, 0, 0, 0, 0.0)
        day_counts = compute_heatmap_data(commits)
        cur, longest, active, _, _ = compute_streaks(day_counts)
        avg = len(commits) / max(active, 1)
        return (len(commits), active, cur, longest, round(avg, 1))

    stats = [get_stats(cl) for cl in commit_lists]
    labels = ["Commits", "Active days", "Current streak", "Longest streak", "Avg/day"]
    for i, label in enumerate(labels):
        v1 = stats[0][i] if len(stats) > 0 else 0
        v2 = stats[1][i] if len(stats) > 1 else 0
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            if v1 > v2:
                c1, c2 = Color.GREEN, Color.DIM
            elif v2 > v1:
                c1, c2 = Color.DIM, Color.GREEN
            else:
                c1, c2 = Color.CYAN, Color.CYAN
        else:
            c1, c2 = "", ""
        print(f"  {label:<28} {c1}{v1:<16}{Color.RESET} {c2}{v2:<16}{Color.RESET}")

    # Day of week comparison
    print(f"\n  {Color.BOLD}Day of Week Comparison{Color.RESET}")
    dow_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    full_dow = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    print(f"  {'Day':<6} {Color.BOLD}{names[0]:<16}{Color.RESET} {Color.BOLD}{names[1]:<16}{Color.RESET}")
    print(f"  {'─' * 38}")
    for short, full in zip(dow_order, full_dow):
        t1 = compute_time_stats(commits_a1)["dow"].get(full, 0) if commits_a1 else 0
        t2 = compute_time_stats(commits_a2)["dow"].get(full, 0) if commits_a2 else 0
        mx = max(t1, t2, 1)
        w1 = int(t1 / mx * 12)
        w2 = int(t2 / mx * 12)
        bar1 = Color.GREEN + BAR * w1 + Color.RESET + EMPTY * (12 - w1)
        bar2 = Color.BLUE + BAR * w2 + Color.RESET + EMPTY * (12 - w2)
        print(f"  {short:<6} {bar1} {t1:<4} {bar2} {t2}")

    # Commit verbs comparison
    print(f"\n  {Color.BOLD}Commit Verbs Comparison{Color.RESET}")
    verbs1 = dict(compute_commit_verbs(commits_a1)) if commits_a1 else {}
    verbs2 = dict(compute_commit_verbs(commits_a2)) if commits_a2 else {}
    all_verbs = sorted(set(list(verbs1.keys()) + list(verbs2.keys())))[:8]
    verb_emoji = {
        "feat": "feat", "fix": "fix", "docs": "docs", "style": "style",
        "refactor": "re", "perf": "perf", "test": "test", "build": "build",
        "ci": "ci", "chore": "chore", "revert": "rev",
    }
    for verb in all_verbs:
        v1 = verbs1.get(verb, 0)
        v2 = verbs2.get(verb, 0)
        mx = max(v1, v2, 1)
        w1 = int(v1 / mx * 12)
        w2 = int(v2 / mx * 12)
        bar1 = Color.GREEN + BAR * w1 + Color.RESET + EMPTY * (12 - w1)
        bar2 = Color.BLUE + BAR * w2 + Color.RESET + EMPTY * (12 - w2)
        print(f"  {verb:<10} {bar1} {v1:<4} {bar2} {v2}")

    print(f"\n{boundary}")
    print(f"  {Color.DIM}Generated by commit-velociraptor v{__version__}{Color.RESET}\n")


# ── rendering ─────────────────────────────────────────────────────────────

BAR = "█"
HALF_BAR = "▌"
EMPTY = "░"

def sparkline(values: list[int]) -> str:
    """Unicode sparkline from a list of ints."""
    blocks = " ▁▂▃▄▅▆▇█"
    if not values:
        return ""
    mx = max(values)
    if mx == 0:
        return blocks[0] * len(values)
    parts = []
    for v in values:
        idx = int(v / mx * (len(blocks) - 1))
        parts.append(blocks[idx])
    return "".join(parts)

def heatmap_grid(day_counts: dict, weeks: int = 20) -> str:
    """
    Render a GitHub-style calendar heatmap in the terminal.
    Each column is a week (Sun→Sat top-to-bottom), newest on far right.
    """
    today = datetime.now().date()
    # Go back far enough to fill the grid
    total_days = weeks * 7
    start = today - timedelta(days=total_days - 1)
    # Align start to a Sunday
    start = start - timedelta(days=start.weekday() + 1)
    if start.weekday() != 6:
        start = start - timedelta(days=(start.weekday() + 1) % 7)

    max_count = max(day_counts.values()) if day_counts else 1
    if max_count == 0:
        max_count = 1

    def count_to_level(n):
        if n == 0:
            return 0
        return max(1, round(n / max_count * (len(LEVEL_COLORS) - 1)))

    # Build grid: 7 rows × (weeks) cols
    label_dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    lines = []
    for row in range(7):
        line = f"{Color.DIM}{label_dow[row]}{Color.RESET} "
        col_dates = []
        for col in range(weeks):
            d = start + timedelta(days=col * 7 + row)
            if d <= today:
                ds = d.strftime("%Y-%m-%d")
                n = day_counts.get(ds, 0)
            else:
                n = -1  # future → blank
            col_dates.append(n)

        for n in col_dates:
            if n == -1:
                line += "  "
            else:
                level = count_to_level(n) if n >= 0 else 0
                line += f"{LEVEL_COLORS[level]} {LEVEL_FG_RESET}"
        lines.append(line)

    # Month labels along the top
    month_line = "     "
    for col in range(weeks):
        d = start + timedelta(days=col * 7)
        if col == 0 or d.month != (start + timedelta(days=(col - 1) * 7)).month:
            month_line += d.strftime("%b")[:1]
        else:
            month_line += " "

    return month_line + "\n" + "\n".join(lines)

def bar_chart(label: str, data: dict, max_width: int = 30) -> str:
    """Simple horizontal bar chart."""
    if not data:
        return ""
    mx = max(data.values())
    lines = []
    for k, v in sorted(data.items()):
        bar_width = int(v / mx * max_width) if mx else 0
        bar_str = Color.GREEN + BAR * bar_width + Color.RESET + EMPTY * (max_width - bar_width)
        lines.append(f"  {Color.BOLD}{k}{Color.RESET}  {bar_str} {Color.CYAN}{v}{Color.RESET}")
    return "\n".join(lines)


# ── main output ───────────────────────────────────────────────────────────

def print_report(repo_path: str, days: Optional[int],
                 author: Optional[str], all_time: bool,
                 show_files: bool = True, show_branches: bool = True,
                 since: Optional[str] = None, until: Optional[str] = None,
                 use_local_time: bool = False):
    effective_days = None if all_time else (days or 90)
    commits = get_commits(repo_path, days=effective_days, author=author,
                          since=since, until=until)
    if not commits:
        print(f"{Color.YELLOW}No commits found for the given filters.{Color.RESET}")
        return

    day_counts = compute_heatmap_data(commits)
    cur_streak, long_streak, active_days, ls_start, ls_end = compute_streaks(day_counts)
    time_stats = compute_time_stats(commits, use_local=use_local_time)
    author_stats = compute_author_stats(commits)

    boundary = f"{Color.CYAN}{'─' * 60}{Color.RESET}"

    # ── Header ──
    print(f"\n{Color.BOLD}{Color.PURPLE}  commit-velociraptor{Color.RESET} {Color.DIM}v{__version__}{Color.RESET}")
    print(f"  {Color.DIM}{repo_path}{Color.RESET}")
    print(boundary)

    # ── Summary ──
    date_range = f"{commits[-1]['date'].strftime('%Y-%m-%d')} -> {commits[0]['date'].strftime('%Y-%m-%d')}"
    print(f"\n  {Color.BOLD}Summary{Color.RESET}")
    print(f"     Total commits:       {Color.CYAN}{len(commits)}{Color.RESET}")
    print(f"     Date range:          {date_range}")
    print(f"     Active days:         {Color.CYAN}{active_days}{Color.RESET}")
    print(f"     Current streak:      {Color.GREEN}{cur_streak} days{Color.RESET}")
    print(f"     Longest streak:      {Color.YELLOW}{long_streak} days{Color.RESET}"
          f"{'  (' + ls_start + ' -> ' + ls_end + ')' if long_streak > 1 else ''}")
    daily = len(commits) / max(active_days, 1)
    print(f"     Avg commits/active:  {Color.CYAN}{daily:.1f}{Color.RESET}")

    # ── Velocity Trend ──
    trend = compute_velocity_trend(commits)
    if trend["trend"] != "insufficient_data":
        trend_color = Color.GREEN if trend["trend"] == "accelerating" else (
            Color.RED if trend["trend"] == "decelerating" else Color.YELLOW
        )
        print(f"\n  {Color.BOLD}Velocity Trend{Color.RESET}")
        print(f"     Direction:     {trend_color}{trend['direction']} {trend['trend']}{Color.RESET}")
        print(f"     Change:        {trend_color}{trend['change_pct']:+.1f}%{Color.RESET}")
        print(f"     First half:    {trend['first_half_rate']} commits/day")
        print(f"     Second half:   {trend['second_half_rate']} commits/day")

    # ── Heatmap ──
    print(f"\n  {Color.BOLD}Commit Calendar{Color.RESET}")
    grid = heatmap_grid(day_counts)
    for line in grid.split("\n"):
        print(f"  {line}")

    # ── Day-of-week ──
    print(f"\n  {Color.BOLD}Activity by Day of Week{Color.RESET}")
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_data = {d: time_stats["dow"].get(d, 0) for d in dow_order}
    print(bar_chart("DoW", dow_data))

    # ── Sparkline ──
    if day_counts:
        sorted_days = sorted(day_counts.keys())
        values = [day_counts[d] for d in sorted_days]
        spark = sparkline(values)
        print(f"\n  {Color.BOLD}Activity Sparkline{Color.RESET}")
        print(f"  {Color.CYAN}{spark}{Color.RESET}")
        print(f"  {Color.DIM}{sorted_days[0]}                        {sorted_days[-1]}{Color.RESET}")

    # ── Hour-of-day ──
    tz_label = "Local" if use_local_time else "UTC"
    print(f"\n  {Color.BOLD}Commits by Hour of Day ({tz_label}){Color.RESET}")
    hour_data = {f"{h:02d}:00": time_stats["hour"].get(h, 0) for h in range(24)}
    hour_items = list(hour_data.items())
    # Show in 4 columns of 6 hours each
    for col_start in range(0, 24, 6):
        chunk = hour_items[col_start:col_start + 6]
        mx = max((v for _, v in chunk), default=1) or 1
        for label, val in chunk:
            w = int(val / mx * 20)
            bar = Color.YELLOW + BAR * w + Color.RESET + EMPTY * (20 - w)
            print(f"  {Color.BOLD}{label}{Color.RESET} {bar} {val}")
        print()

    # ── Commit Verbs / Conventional Commit Breakdown ──
    commit_verbs = compute_commit_verbs(commits)
    if commit_verbs:
        print(f"  {Color.BOLD}Commit Subjects Breakdown{Color.RESET}")
        print(f"  {Color.DIM}Most common verbs/prefixes in commit messages{Color.RESET}")
        mx_verb = commit_verbs[0][1] if commit_verbs else 1
        for verb, count in commit_verbs:
            w = int(count / mx_verb * 25)
            bar = Color.BLUE + BAR * w + Color.RESET + EMPTY * (25 - w)
            print(f"  {Color.BOLD}{verb:<12}{Color.RESET} {bar} {Color.CYAN}{count}{Color.RESET}")
        print()

    # ── Commit Quality Score ──
    quality = compute_quality_score(commits)
    if commits:
        grade_color = Color.GREEN if quality["overall"] >= 70 else (
            Color.YELLOW if quality["overall"] >= 50 else Color.RED
        )
        print(f"  {Color.BOLD}Commit Message Quality{Color.RESET}")
        print(f"  {Color.DIM}Score: 0-100 with breakdown{Color.RESET}")
        print(f"     Overall: {grade_color}{quality['overall']}/100 ({quality['grade']}){Color.RESET}")
        print()
        # Show each sub-score as a mini bar
        for criterion, info in quality["details"].items():
            w = int(info["score"] / info["max"] * 20)
            bar = Color.CYAN + BAR * w + Color.RESET + EMPTY * (20 - w)
            label = criterion.replace("_", " ").title()
            print(f"     {label:<24} {bar} {info['score']}/{info['max']}")
        print()

    # ── Top authors ──
    if len(author_stats) > 1:
        print(f"  {Color.BOLD}Top Contributors{Color.RESET}")
        total = sum(author_stats.values())
        for auth, cnt in author_stats.items():
            pct = cnt / total * 100
            w = int(pct / 100 * 25)
            bar = Color.PURPLE + BAR * w + Color.RESET + EMPTY * (25 - w)
            print(f"  {Color.BOLD}{auth:<22}{Color.RESET} {bar} {cnt} ({pct:.1f}%)")
        print()

    # ── Top Files Changed ──
    if show_files:
        print(f"  {Color.BOLD}Most Changed Files{Color.RESET}")
        print(f"  {Color.DIM}Files with the most commits touching them{Color.RESET}")
        file_stats = get_file_stats(repo_path, days=effective_days, author=author,
                                    since=since, until=until)
        top_files = file_stats.most_common(10)
        if top_files:
            mx_file = top_files[0][1]
            for filepath, count in top_files:
                w = int(count / mx_file * 25)
                bar = Color.RED + BAR * w + Color.RESET + EMPTY * (25 - w)
                # Shorten long paths
                display_path = filepath
                if len(filepath) > 40:
                    parts = filepath.split("/")
                    if len(parts) > 3:
                        display_path = "/".join(parts[:2]) + "/.../" + parts[-1]
                print(f"  {Color.BOLD}{display_path:<42}{Color.RESET} {bar} {Color.CYAN}{count}{Color.RESET}")
        else:
            print(f"  {Color.DIM}(no file data available){Color.RESET}")
        print()

    # ── Branch Overview ──
    if show_branches:
        branch_info = get_branch_info(repo_path)
        if branch_info:
            print(f"  {Color.BOLD}Branch Overview{Color.RESET}")
            print(f"  {Color.DIM}Local branches sorted by recent activity{Color.RESET}")
            now = datetime.now()
            for b in branch_info[:10]:
                age_days = (now - b["date"]).days
                if age_days == 0:
                    age_str = "today"
                elif age_days == 1:
                    age_str = "yesterday"
                elif age_days < 30:
                    age_str = f"{age_days}d ago"
                elif age_days < 365:
                    age_str = f"{age_days // 30}mo ago"
                else:
                    age_str = f"{age_days // 365}y ago"

                current_marker = f"{Color.GREEN}*{Color.RESET}" if b["is_current"] else " "
                ahead_str = ""
                if b["ahead"] > 0:
                    ahead_str = f" {Color.YELLOW}(+{b['ahead']} ahead){Color.RESET}"
                elif b["ahead"] == -1:
                    ahead_str = f" {Color.RED}(diverged){Color.RESET}"

                print(f"  {current_marker} {Color.BOLD}{b['name']:<20}{Color.RESET}"
                      f" {Color.DIM}{age_str:<10}{Color.RESET}"
                      f"{ahead_str}")
            print()

    # ── Velocity (last 12 weeks) ──
    print(f"  {Color.BOLD}Weekly Velocity (recent 12 weeks){Color.RESET}")
    now = datetime.now()
    weekly_data: Counter = Counter()
    for c in commits:
        dt = c["date"]
        # ISO week
        week_num = dt.isocalendar()[1]
        year = dt.isocalendar()[0]
        wk_key = f"{year}-W{week_num:02d}"
        weekly_data[wk_key] += 1

    recent_weeks = sorted(weekly_data.keys())[-12:]
    mx_weekly = max((weekly_data[w] for w in recent_weeks), default=1) or 1
    for wk in recent_weeks:
        v = weekly_data[wk]
        w = int(v / mx_weekly * 25)
        bar = Color.GREEN + BAR * w + Color.RESET + EMPTY * (25 - w)
        print(f"  {Color.BOLD}{wk}{Color.RESET}  {bar} {Color.CYAN}{v}{Color.RESET}")

    print(f"\n{boundary}")
    print(f"  {Color.DIM}Generated by commit-velociraptor v{__version__}{Color.RESET}\n")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="commit-velociraptor — Speed through your Git history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  velociraptor                            # analyze current repo (90 days)\n"
               "  velociraptor --days 30                  # last 30 days\n"
               "  velociraptor --all-time                 # all-time stats\n"
               "  velociraptor --author \"John\"             # filter by author\n"
               "  velociraptor /path/to/repo              # point at another repo\n"
               "  velociraptor --no-files                 # hide file change stats\n"
               "  velociraptor --no-branches              # hide branch overview\n"
               "  velociraptor --since 2025-01-01        # commits after date\n"
               "  velociraptor --until 2025-06-01        # commits before date\n"
               "  velociraptor --export json              # export stats as JSON\n"
               "  velociraptor --export csv               # export commits as CSV\n"
               "  velociraptor --compare \"Alice\" \"Bob\"   # compare two authors\n"
               "  velociraptor --local-time               # use local timezone for hours\n",
    )
    parser.add_argument("repo", nargs="?", default=".",
                        help="Path to git repo (default: current directory)")
    parser.add_argument("--days", type=int, default=90,
                        help="Number of days to look back (default: 90)")
    parser.add_argument("--all-time", action="store_true",
                        help="Show all-time stats, ignoring --days")
    parser.add_argument("--author", type=str, default=None,
                        help="Filter by author name (substring match)")
    parser.add_argument("--since", type=str, default=None,
                        help="Show commits after this date (YYYY-MM-DD or git date format)")
    parser.add_argument("--until", type=str, default=None,
                        help="Show commits before this date (YYYY-MM-DD or git date format)")
    parser.add_argument("--export", type=str, choices=["json", "csv"], default=None,
                        help="Export data as JSON (full stats) or CSV (per-commit)")
    parser.add_argument("--compare", type=str, nargs=2, default=None,
                        metavar=("AUTHOR1", "AUTHOR2"),
                        help="Compare two authors side-by-side")
    parser.add_argument("--no-files", action="store_true",
                        help="Skip the 'most changed files' section")
    parser.add_argument("--no-branches", action="store_true",
                        help="Skip the branch overview section")
    parser.add_argument("--local-time", action="store_true",
                        help="Display hour-of-day stats in local timezone instead of UTC")
    parser.add_argument("--version", action="version",
                        version=f"commit-velociraptor v{__version__}")
    args = parser.parse_args()

    if not os.path.isdir(args.repo):
        print(f"{Color.RED}Error: {args.repo} is not a directory.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    git_dir = os.path.join(args.repo, ".git")
    if not os.path.isdir(git_dir):
        print(f"{Color.RED}Error: {args.repo} does not appear to be a git repository.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    # Handle --export
    if args.export == "json":
        output = export_json(
            args.repo, args.days, args.author, args.all_time,
            since=args.since, until=args.until,
        )
        print(output)
        return

    if args.export == "csv":
        output = export_csv(
            args.repo, args.days, args.author, args.all_time,
            since=args.since, until=args.until,
        )
        print(output)
        return

    # Handle --compare
    if args.compare:
        print_compare(
            args.repo, args.compare[0], args.compare[1],
            args.days, args.all_time,
            since=args.since, until=args.until,
        )
        return

    # Default: print the full report
    print_report(
        args.repo, args.days, args.author, args.all_time,
        show_files=not args.no_files,
        show_branches=not args.no_branches,
        since=args.since, until=args.until,
        use_local_time=args.local_time,
    )


if __name__ == "__main__":
    main()
