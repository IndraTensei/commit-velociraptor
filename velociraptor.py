#!/usr/bin/env python3
"""
commit-velociraptor 🦖 — Speed through your Git history.

Analyzes commit velocity, streaks, patterns per day-of-week & hour-of-day,
and renders a beautiful terminal heatmap. Think "GitHub contribution graph"
but for ANY local repo, right in your terminal, no browser needed.
"""

import subprocess
import sys
import os
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

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
                author: Optional[str] = None) -> list[dict]:
    """
    Fetch commit log as a list of dicts with keys:
      hash, author, email, date (datetime), subject
    """
    sep = "<|COMMIT_SEP|>"
    fmt_string = f"%H{sep}%an{sep}%ae{sep}%aI{sep}%s"
    cmd = ["log", f"--pretty=format:{fmt_string}", "--date=iso", "-n", "10000"]
    if days:
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


def compute_time_stats(commits: list[dict]) -> dict:
    """Stats broken down by day-of-week, hour-of-week."""
    dow_counts = Counter()
    hour_counts = Counter()
    for c in commits:
        dow_counts[c["date"].strftime("%A")] += 1
        hour_counts[c["date"].hour] += 1
    return {"dow": dict(dow_counts), "hour": dict(hour_counts)}


def compute_author_stats(commits: list[dict]) -> dict:
    """Commits per author."""
    counts = Counter()
    for c in commits:
        counts[c["author"]] += 1
    return dict(counts.most_common(10))


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
                 author: Optional[str], all_time: bool):
    commits = get_commits(
        repo_path,
        days=None if all_time else (days or 90),
        author=author,
    )
    if not commits:
        print(f"{Color.YELLOW}No commits found for the given filters.{Color.RESET}")
        return

    day_counts = compute_heatmap_data(commits)
    cur_streak, long_streak, active_days, ls_start, ls_end = compute_streaks(day_counts)
    time_stats = compute_time_stats(commits)
    author_stats = compute_author_stats(commits)

    boundary = f"{Color.CYAN}{'─' * 60}{Color.RESET}"

    # ── Header ──
    print(f"\n{Color.BOLD}{Color.PURPLE}  🦖 commit-velociraptor{Color.RESET}")
    print(f"  {Color.DIM}{repo_path}{Color.RESET}")
    print(boundary)

    # ── Summary ──
    date_range = f"{commits[-1]['date'].strftime('%Y-%m-%d')} → {commits[0]['date'].strftime('%Y-%m-%d')}"
    print(f"\n  {Color.BOLD}📊 Summary{Color.RESET}")
    print(f"     Total commits:       {Color.CYAN}{len(commits)}{Color.RESET}")
    print(f"     Date range:          {date_range}")
    print(f"     Active days:         {Color.CYAN}{active_days}{Color.RESET}")
    print(f"     Current streak:      {Color.GREEN}{cur_streak} days{Color.RESET}")
    print(f"     Longest streak:      {Color.YELLOW}{long_streak} days{Color.RESET}"
          f"{'  (' + ls_start + ' → ' + ls_end + ')' if long_streak > 1 else ''}")
    daily = len(commits) / max(active_days, 1)
    print(f"     Avg commits/active:  {Color.CYAN}{daily:.1f}{Color.RESET}")

    # ── Heatmap ──
    print(f"\n  {Color.BOLD}📅 Commit Calendar{Color.RESET}")
    grid = heatmap_grid(day_counts)
    for line in grid.split("\n"):
        print(f"  {line}")

    # ── Day-of-week ──
    print(f"\n  {Color.BOLD}📆 Activity by Day of Week{Color.RESET}")
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_data = {d: time_stats["dow"].get(d, 0) for d in dow_order}
    print(bar_chart("DoW", dow_data))

    # ── Sparkline ──
    if day_counts:
        sorted_days = sorted(day_counts.keys())
        values = [day_counts[d] for d in sorted_days]
        spark = sparkline(values)
        print(f"\n  {Color.BOLD}🔥 Activity Sparkline{Color.RESET}")
        print(f"  {Color.CYAN}{spark}{Color.RESET}")
        print(f"  {Color.DIM}{sorted_days[0]}                        {sorted_days[-1]}{Color.RESET}")

    # ── Hour-of-day ──
    print(f"\n  {Color.BOLD}🕐 Commits by Hour of Day (UTC){Color.RESET}")
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

    # ── Top authors ──
    if len(author_stats) > 1:
        print(f"  {Color.BOLD}👥 Top Contributors{Color.RESET}")
        total = sum(author_stats.values())
        for auth, cnt in author_stats.items():
            pct = cnt / total * 100
            w = int(pct / 100 * 25)
            bar = Color.PURPLE + BAR * w + Color.RESET + EMPTY * (25 - w)
            print(f"  {Color.BOLD}{auth:<22}{Color.RESET} {bar} {cnt} ({pct:.1f}%)")
        print()

    # ── Velocity (last 12 weeks) ──
    print(f"  {Color.BOLD}🚀 Weekly Velocity (recent 12 weeks){Color.RESET}")
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
    print(f"  {Color.DIM}Generated by commit-velociraptor 🦖{Color.RESET}\n")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🦖 commit-velociraptor — Speed through your Git history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  velociraptor                     # analyze current repo (90 days)\n"
               "  velociraptor --days 30           # last 30 days\n"
               "  velociraptor --all-time          # all-time stats\n"
               "  velociraptor --author \"John\"      # filter by author\n"
               "  velociraptor /path/to/repo       # point at another repo\n",
    )
    parser.add_argument("repo", nargs="?", default=".",
                        help="Path to git repo (default: current directory)")
    parser.add_argument("--days", type=int, default=90,
                        help="Number of days to look back (default: 90)")
    parser.add_argument("--all-time", action="store_true",
                        help="Show all-time stats, ignoring --days")
    parser.add_argument("--author", type=str, default=None,
                        help="Filter by author name (substring match)")
    args = parser.parse_args()

    if not os.path.isdir(args.repo):
        print(f"{Color.RED}Error: {args.repo} is not a directory.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    git_dir = os.path.join(args.repo, ".git")
    if not os.path.isdir(git_dir):
        print(f"{Color.RED}Error: {args.repo} does not appear to be a git repository.{Color.RESET}", file=sys.stderr)
        sys.exit(1)

    print_report(args.repo, args.days, args.author, args.all_time)


if __name__ == "__main__":
    main()
