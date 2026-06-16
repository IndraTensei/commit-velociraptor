# 🦖 commit-velociraptor

> **Speed through your Git history.**

A blazing-fast CLI tool that turns your git commit log into beautiful, insightful
terminal dashboards. Think GitHub's contribution graph on steroids — right in
your terminal, for *any* local repo, no browser needed.

![terminal demo](https://img.shields.io/badge/platform-terminal-brightgreen)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![license](https://img.shields.io/badge/license-MIT-yellow)
![version](https://img.shields.io/badge/version-1.2.0-orange)

---

## ✨ Features

- 📅 **Commit Calendar** — GitHub-style heatmap grid rendered with ANSI colors
- 🔥 **Activity Sparkline** — At-a-glance trend line across your history
- 📊 **Day-of-Week Analysis** — Know your most and least productive days
- 🕐 **Hour-of-Day Breakdown** — Find your peak coding hours
- 🏟️ **Streak Tracking** — Current streak vs. longest ever, with dates
- 👥 **Contributor Stats** — Who's pushing the most in this repo?
- 🚀 **Weekly Velocity** — Last 12 weeks of commit volume, bar chart style
- 🏷️ **Author Filtering** — Zoom in on one contributor
- 📝 **Commit Subjects Breakdown** — Most common verbs & conventional commit prefixes (feat, fix, docs…) with emoji indicators
- 🏆 **Most Changed Files** — Find the hotspots — which files get committed most often
- 🔀 **Branch Overview** — See all local branches sorted by recency, with ahead/behind status vs main
- 📏 **Configurable Windows** — 30 days, 90 days, or all-time
- 🏳️ **Version Flag** — `--version` to check which version you're running
- 📤 **Export as JSON/CSV** — Machine-readable output for CI/CD, dashboards, or external analysis (`--export json|csv`)
- 📆 **Flexible Date Filters** — `--since` and `--until` for precise date ranges (accepts `YYYY-MM-DD` or any git date format)
- 🆚 **Author Comparison** — `--compare "Alice" "Bob"` shows side-by-side stats for two contributors

No dependencies, no browser, no API keys. Just Python 3.8+ and `git`.

---

## 🚀 Installation

### Quick run (no install)

```bash
curl -fsSL https://raw.githubusercontent.com/IndraTensei/commit-velociraptor/main/velociraptor.py \
  -o velociraptor && chmod +x velociraptor
```

### From source

```bash
git clone https://github.com/IndraTensei/commit-velociraptor.git
cd commit-velociraptor
chmod +x velociraptor.py
# Optional: symlink into your PATH
ln -s "$(pwd)/velociraptor.py" ~/.local/bin/velociraptor
```

### Requirements

- Python 3.8 or newer
- A git repository (obviously 😄)
- A terminal that supports ANSI color codes (basically any modern terminal)

---

## 📖 Usage

```bash
# Analyze the repo you're currently in (last 90 days)
velociraptor

# Point it at any repo
velociraptor ~/projects/my-awesome-project

# Show last 30 days only
velociraptor --days 30

# All-time history
velociraptor --all-time

# Filter by a specific author
velociraptor --author "Alice"

# Commits after a specific date
velociraptor --since 2025-01-01

# Commits before a specific date
velociraptor --until 2025-06-01

# Date range: combine --since and --until
velociraptor --since 2025-01-01 --until 2025-12-31

# Export full stats as JSON (great for CI/CD or dashboards)
velociraptor --export json

# Export per-commit data as CSV
velociraptor --export csv --all-time

# Compare two authors side-by-side
velociraptor --compare "Alice" "Bob"

# Hide the new file/branch sections
velociraptor --no-files
velociraptor --no-branches

# Check your version
velociraptor --version

# Combine flags
velociraptor ~/code/some-repo --days 365 --author "Bob" --export json
```

---

## 🖼️ Example Output

```
  🦖 commit-velociraptor v1.2.0
  /home/indra/projects/velociraptor
  ────────────────────────────────────────────────────────────

  📊 Summary
     Total commits:       847
     Date range:          2025-03-01 → 2026-05-30
     Active days:         203
     Current streak:      14 days
     Longest streak:      31 days  (2026-01-02 → 2026-02-01)
     Avg commits/active:  4.2

  📅 Commit Calendar
     O M J J A S O N
  Sun
  Mon ░░░░██░░██░░██░░░░██░░██░░██░░░░██░░██░░██░░░░██░░██░░░░
  Tue ░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░░░
  Wed ██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░░██░
  Thu ...
  Fri ...
  Sat ...

  📆 Activity by Day of Week
  Wednesday  ██████████████████████████████ 142
  Tuesday    ████████████████████████████   131
  Monday     █████████████████████████       124
  ...

  🕐 Commits by Hour of Day (UTC)
  01:00  ████████████████████ 42
  10:00  █████████░░░░░░░░░░░ 18
  14:00  ██████████████████████████ 51
  ...

  📝 Commit Subjects Breakdown
  Most common verbs/prefixes in commit messages
  ✨ feat         █████████████████████████ 193
  🐛 fix          ██████████████████░░░░░░░ 121
  ♻️ refactor      █████████████░░░░░░░░░░░░ 84
  📖 docs         █████░░░░░░░░░░░░░░░░░░░░ 31
  ...

  🏆 Most Changed Files
  Files with the most commits touching them
  src/core/engine.py                         █████████████████████████ 67
  src/cli/parser.py                          ████████████████░░░░░░░░░ 42
  tests/test_engine.py                       ██████████░░░░░░░░░░░░░░░ 28
  ...

  🔀 Branch Overview
  Local branches sorted by recent activity
  * main                  today
    feat/auth-middleware  3d ago     (+12 ahead)
    fix/timeout-bug       1w ago     (+2 ahead)
    hotfix/crash          5mo ago    (diverged)

  🚀 Weekly Velocity (recent 12 weeks)
  2026-W18  █████████████████████████ 23
  2026-W19  █████████████████████░░░ 19
  ...

  ────────────────────────────────────────────────────────────
  Generated by commit-velociraptor v1.2.0 🦖
```

---

## 🛠️ Development

```bash
# Clone
git clone https://github.com/IndraTensei/commit-velociraptor.git
cd commit-velociraptor

# Test against its own repo
python velociraptor.py --all-time

# Run on another repo
python velociraptor.py ~/other-project --days 30

# Run on a larger project to see all features shine
python velociraptor.py ~/some-big-project --all-time
```

---

## 🤝 Contributing

1. Fork the project
2. Create your feature branch (`git checkout -b feature/amazing-thing`)
3. Commit your changes (`git commit -m 'Add amazing thing'`)
4. Push to the branch (`git push origin feature/amazing-thing`)
5. Open a Pull Request

Please keep the dependency-free philosophy. No `pip install` should ever be
required to run this tool.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

*Built with coffee, curiosity, and a healthy obsession with git log.*
