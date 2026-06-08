"""
@file update_profile_readme
@project holic512 GitHub profile
@module Profile README / 自动同步
@description 根据 GitHub 公开数据更新 assets/profile-readme.svg 中的统计数字与贡献曲线。
@logic 1. 使用 GITHUB_TOKEN 查询 GitHub GraphQL；2. 读取 Profile views 徽章；3. 以正则替换 SVG 中的受控统计字段。
@dependencies Env: GITHUB_TOKEN, File: assets/profile-readme.svg, API: GitHub GraphQL
@index_tags GitHub Actions, README 自同步, SVG 生成, GitHub 统计
@author holic512
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "assets" / "profile-readme.svg"
USERNAME = os.environ.get("PROFILE_USERNAME", "holic512")
PROFILE_VIEWS_URL = os.environ.get(
    "PROFILE_VIEWS_URL",
    f"https://komarev.com/ghpvc/?username={USERNAME}&abbreviated=true&color=000000&style=flat-square",
)
FALLBACK_LANGUAGES = ["Vue", "TypeScript", "Java", "JavaScript", "Python"]
LANGUAGE_COLORS = ["#111111", "#333333", "#777777", "#aaaaaa", "#d0d0d0"]


def read_svg() -> str:
    return SVG_PATH.read_text(encoding="utf-8")


def write_svg(svg: str) -> None:
    SVG_PATH.write_text(svg, encoding="utf-8")


def replace_once(svg: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, svg, count=1, flags=re.DOTALL)
    if count == 0:
        raise RuntimeError(f"SVG replacement pattern not found: {pattern}")
    return updated


def replace_text(svg: str, prefix_pattern: str, value: str) -> str:
    return replace_once(svg, f"({prefix_pattern})[^<]*(</text>)", rf"\g<1>{value}\2")


def github_graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "holic512-profile-readme-updater",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"], ensure_ascii=False))
    return result["data"]


def fetch_profile_views() -> str | None:
    try:
        request = urllib.request.Request(
            PROFILE_VIEWS_URL,
            headers={"User-Agent": "holic512-profile-readme-updater"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            badge = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError):
        return None

    labels = re.findall(r">([^<>]+)</text>", badge)
    candidates = [label.strip() for label in labels if label.strip() and "Profile" not in label]
    return candidates[-1] if candidates else None


def fetch_github_stats() -> dict[str, Any] | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None

    today = dt.datetime.now(dt.timezone.utc).date()
    year = today.year
    year_from = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).isoformat()
    year_to = dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc).isoformat()
    recent_from = dt.datetime.combine(today - dt.timedelta(days=365), dt.time.min, tzinfo=dt.timezone.utc).isoformat()
    recent_to = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc).isoformat()

    query = """
    query ProfileReadmeStats($login: String!, $yearFrom: DateTime!, $yearTo: DateTime!, $recentFrom: DateTime!, $recentTo: DateTime!) {
      user(login: $login) {
        login
        name
        createdAt
        yearContrib: contributionsCollection(from: $yearFrom, to: $yearTo) {
          contributionCalendar {
            totalContributions
          }
        }
        recentContrib: contributionsCollection(from: $recentFrom, to: $recentTo) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
          totalCount
          nodes {
            stargazerCount
            primaryLanguage {
              name
            }
            defaultBranchRef {
              target {
                ... on Commit {
                  history(since: $yearFrom, until: $yearTo) {
                    totalCount
                  }
                }
              }
            }
          }
        }
        pullRequests {
          totalCount
        }
        issues {
          totalCount
        }
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) {
          totalCount
        }
      }
    }
    """
    data = github_graphql(
        token,
        query,
        {
            "login": USERNAME,
            "yearFrom": year_from,
            "yearTo": year_to,
            "recentFrom": recent_from,
            "recentTo": recent_to,
        },
    )
    user = data["user"]
    repos = user["repositories"]["nodes"]
    created_at = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00")).date()
    joined_years = max(0, today.year - created_at.year - ((today.month, today.day) < (created_at.month, created_at.day)))
    repo_languages: Counter[str] = Counter()
    commit_languages: Counter[str] = Counter()

    for repo in repos:
        language = ((repo.get("primaryLanguage") or {}).get("name") or "").strip()
        if not language:
            continue
        commits = (((repo.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get("totalCount") or 0
        repo_languages[language] += 1
        commit_languages[language] += commits

    return {
        "year": year,
        "contributions": user["yearContrib"]["contributionCalendar"]["totalContributions"],
        "calendar_days": [
            day
            for week in user["recentContrib"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
        ],
        "public_repos": user["repositories"]["totalCount"],
        "stars": sum(repo.get("stargazerCount") or 0 for repo in repos),
        "year_commits": sum(
            (((repo.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get("totalCount") or 0
            for repo in repos
        ),
        "pull_requests": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributed_to": user["repositoriesContributedTo"]["totalCount"],
        "joined_years": joined_years,
        "repo_languages": top_languages(repo_languages),
        "commit_languages": top_languages(commit_languages if sum(commit_languages.values()) else repo_languages),
    }


def top_languages(counter: Counter[str]) -> list[tuple[str, int]]:
    languages = counter.most_common(5)
    existing = {name for name, _ in languages}
    for name in FALLBACK_LANGUAGES:
        if len(languages) >= 5:
            break
        if name not in existing:
            languages.append((name, 0))
    return languages[:5]


def chart_paths(days: list[dict[str, Any]]) -> tuple[str, str, int, list[str]]:
    if not days:
        raise ValueError("No contribution calendar days found.")

    days = sorted(days, key=lambda item: item["date"])[-366:]
    counts = [int(day["contributionCount"]) for day in days]
    max_count = max(counts) if counts else 0
    max_tick = max(10, int(math.ceil(max_count / 10.0) * 10))

    x0, x1 = 408.0, 1010.0
    y0, y_top = 1006.0, 884.0
    span = max(1, len(days) - 1)

    points: list[tuple[float, float]] = []
    for index, count in enumerate(counts):
        x = x0 + (x1 - x0) * index / span
        y = y0 - (y0 - y_top) * count / max_tick
        points.append((x, y))

    point_path = " ".join(f"L{x:.1f} {y:.1f}" for x, y in points)
    area = f"M{x0:.1f} {y0:.1f} L{points[0][0]:.1f} {points[0][1]:.1f} {point_path} L{x1:.1f} {y0:.1f} Z"
    line = f"M{points[0][0]:.1f} {points[0][1]:.1f} " + point_path

    tick_indexes = [round((len(days) - 1) * ratio / 5) for ratio in range(6)]
    tick_labels = [
        dt.date.fromisoformat(days[index]["date"]).strftime("%y/%m")
        for index in tick_indexes
    ]
    return area, line, max_tick, tick_labels


def update_axis_labels(svg: str, max_tick: int, tick_labels: list[str]) -> str:
    y_positions = [888, 905, 923, 941, 959, 977, 1007]
    values = [
        max_tick,
        round(max_tick * 10 / 11),
        round(max_tick * 8 / 11),
        round(max_tick * 6 / 11),
        round(max_tick * 4 / 11),
        round(max_tick * 2 / 11),
        0,
    ]
    for y, value in zip(y_positions, values):
        svg = re.sub(
            rf'(<text x="1017" y="{y}" class="tiny">)[^<]*(</text>)',
            rf"\g<1>{value}\2",
            svg,
            count=1,
        )

    x_positions = [398, 510, 618, 728, 836, 947]
    for x, label in zip(x_positions, tick_labels):
        svg = re.sub(
            rf'(<text x="{x}" y="1023" class="tiny">)[^<]*(</text>)',
            rf"\g<1>{label}\2",
            svg,
            count=1,
        )
    return svg


def language_legend(x: int, y: int, languages: list[tuple[str, int]]) -> str:
    lines = [f'<g transform="translate({x} {y})">']
    for index, (name, _) in enumerate(languages[:5]):
        y_offset = index * 24
        color = LANGUAGE_COLORS[index]
        escaped = html.escape(name)
        lines.append(f'      <rect x="0" y="{y_offset}" width="12" height="12" fill="{color}"/><text x="20" y="{y_offset + 10}" class="small">{escaped}</text>')
    lines.append("    </g>")
    return "\n".join(lines)


def language_donut(x: int, y: int, languages: list[tuple[str, int]]) -> str:
    total = sum(max(value, 0) for _, value in languages)
    if total <= 0:
        total = len(languages)
        values = [1 for _ in languages]
    else:
        values = [max(value, 0) for _, value in languages]

    circumference = 320.0
    offset = 0.0
    lines = [f'<g transform="translate({x} {y})">']
    for index, value in enumerate(values[:5]):
        segment = circumference * value / total
        color = LANGUAGE_COLORS[index]
        lines.append(
            f'      <circle r="51" fill="none" stroke="{color}" stroke-width="26" '
            f'stroke-dasharray="{segment:.1f} {circumference - segment:.1f}" stroke-dashoffset="{-offset:.1f}"/>'
        )
        offset += segment
    lines.append('      <circle r="27" fill="#ffffff"/>')
    lines.append("    </g>")
    return "\n".join(lines)


def update_language_blocks(svg: str, repo_languages: list[tuple[str, int]], commit_languages: list[tuple[str, int]]) -> str:
    replacements = [
        (r'<g transform="translate\(452 1113\)">.*?</g>', language_legend(452, 1113, repo_languages)),
        (r'<g transform="translate\(616 1147\)">.*?</g>', language_donut(616, 1147, repo_languages)),
        (r'<g transform="translate\(764 1113\)">.*?</g>', language_legend(764, 1113, commit_languages)),
        (r'<g transform="translate\(930 1147\)">.*?</g>', language_donut(930, 1147, commit_languages)),
    ]
    for pattern, replacement in replacements:
        svg = replace_once(svg, pattern, replacement)
    return svg


def update_svg(svg: str, stats: dict[str, Any] | None, profile_views: str | None) -> str:
    if profile_views:
        svg = replace_text(svg, r'<text x="696" y="20" class="badgeText">', profile_views)

    if not stats:
        return svg

    year = stats["year"]
    joined_label = "1 year ago" if stats["joined_years"] == 1 else f"{stats['joined_years']} years ago"

    svg = replace_text(svg, r'<text x="24" y="5" class="body">', f"{stats['contributions']} Contributions in {year}")
    svg = replace_text(svg, r'<text x="24" y="45" class="body">', f"{stats['public_repos']} Public Repos")
    svg = replace_text(svg, r'<text x="24" y="82" class="body">', f"Joined GitHub {joined_label}")
    svg = replace_text(svg, r'<text x="135" y="0" class="body">', str(stats["stars"]))
    svg = replace_text(svg, r'<text x="135" y="27" class="body">', str(stats["year_commits"]))
    svg = replace_text(svg, r'<text x="135" y="54" class="body">', str(stats["pull_requests"]))
    svg = replace_text(svg, r'<text x="135" y="81" class="body">', str(stats["issues"]))
    svg = replace_text(svg, r'<text x="135" y="108" class="body">', str(stats["contributed_to"]))

    area, line, max_tick, tick_labels = chart_paths(stats["calendar_days"])
    svg = re.sub(
        r'<path(?: id="contribution-area")? d="[^"]+" fill="#111111" opacity="0\.96"/>',
        f'<path id="contribution-area" d="{area}" fill="#111111" opacity="0.96"/>',
        svg,
        count=1,
    )
    svg = re.sub(
        r'<path(?: id="contribution-line")? d="[^"]+" fill="none" stroke="#000000" stroke-width="2"/>',
        f'<path id="contribution-line" d="{line}" fill="none" stroke="#000000" stroke-width="2"/>',
        svg,
        count=1,
    )
    svg = update_axis_labels(svg, max_tick, tick_labels)
    return update_language_blocks(svg, stats["repo_languages"], stats["commit_languages"])


def main() -> int:
    svg = read_svg()
    try:
        stats = fetch_github_stats()
    except Exception as exc:  # noqa: BLE001 - workflow should keep existing SVG if GitHub API is temporarily unavailable.
        print(f"warning: failed to fetch GitHub stats: {exc}", file=sys.stderr)
        stats = None

    profile_views = fetch_profile_views()
    updated = update_svg(svg, stats, profile_views)
    write_svg(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
