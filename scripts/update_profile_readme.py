"""
@file update_profile_readme
@project holic512 GitHub profile
@module Profile README / 数据同步
@description 根据 GitHub 公开数据更新 data/profile-readme.json 中的动态统计字段。
@logic 1. 使用 GITHUB_TOKEN 查询 GitHub GraphQL；2. 读取 Profile views 徽章；3. 合并动态数据到 README 图片数据源。
@dependencies Env: GITHUB_TOKEN, File: data/profile-readme.json, API: GitHub GraphQL
@index_tags GitHub Actions, README 自同步, JSON 数据源, GitHub 统计
@author holic512
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "profile-readme.json"
USERNAME = os.environ.get("PROFILE_USERNAME", "holic512")
PROFILE_VIEWS_URL = os.environ.get(
    "PROFILE_VIEWS_URL",
    f"https://komarev.com/ghpvc/?username={USERNAME}&abbreviated=true&color=000000&style=flat-square",
)
FALLBACK_LANGUAGES = ["Vue", "TypeScript", "Java", "JavaScript", "Python"]


def read_data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def write_data(data: dict[str, Any]) -> None:
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def top_languages(counter: Counter[str]) -> list[dict[str, int | str]]:
    languages = counter.most_common(5)
    existing = {name for name, _ in languages}
    for name in FALLBACK_LANGUAGES:
        if len(languages) >= 5:
            break
        if name not in existing:
            languages.append((name, 0))
    return [{"name": name, "value": value} for name, value in languages[:5]]


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
        "calendarDays": [
            {
                "date": day["date"],
                "count": int(day["contributionCount"]),
            }
            for week in user["recentContrib"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
        ][-366:],
        "publicRepos": user["repositories"]["totalCount"],
        "stars": sum(repo.get("stargazerCount") or 0 for repo in repos),
        "yearCommits": sum(
            (((repo.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get("totalCount") or 0
            for repo in repos
        ),
        "pullRequests": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributedTo": user["repositoriesContributedTo"]["totalCount"],
        "joinedYears": joined_years,
        "repoLanguages": top_languages(repo_languages),
        "commitLanguages": top_languages(commit_languages if sum(commit_languages.values()) else repo_languages),
    }


def merge_dynamic_data(data: dict[str, Any], stats: dict[str, Any] | None, profile_views: str | None) -> dict[str, Any]:
    dynamic = data.setdefault("dynamic", {})
    if stats:
        dynamic["github"] = stats
        dynamic["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if profile_views:
        dynamic["profileViews"] = profile_views
    return data


def main() -> int:
    data = read_data()
    try:
        stats = fetch_github_stats()
    except Exception as exc:  # noqa: BLE001 - workflow should still render from the last good JSON snapshot.
        print(f"warning: failed to fetch GitHub stats: {exc}", file=sys.stderr)
        stats = None

    profile_views = fetch_profile_views()
    write_data(merge_dynamic_data(data, stats, profile_views))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
