#!/usr/bin/env python3
"""LLM 위키 점검 스크립트.

검사 항목:
  - 깨진 [[링크]]
  - 중복 파일명 (링크가 모호해짐)
  - frontmatter 누락 / 필수 키 누락
  - index.md에 없는 페이지
  - 아무도 링크하지 않는 고아 페이지

사용법: python3 wiki/tools/wiki_lint.py
문제가 있으면 종료 코드 1.
"""
import re
import sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
PAGES = WIKI / "pages"
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
REQUIRED = ("title", "type", "sources", "updated")


def frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    keys = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            keys[k.strip()] = v.strip()
    return keys


def main():
    problems = []
    pages = {}
    for p in sorted(PAGES.rglob("*.md")):
        if p.stem in pages:
            problems.append(f"중복 파일명: {p.relative_to(WIKI)} / {pages[p.stem].relative_to(WIKI)}")
        pages[p.stem] = p

    index_text = (WIKI / "index.md").read_text(encoding="utf-8")
    index_links = set(LINK.findall(index_text))
    inbound = {name: 0 for name in pages}

    for name, path in pages.items():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(WIKI)
        fm = frontmatter(text)
        if fm is None:
            problems.append(f"frontmatter 없음: {rel}")
        else:
            missing = [k for k in REQUIRED if k not in fm]
            if missing:
                problems.append(f"frontmatter 키 누락 {missing}: {rel}")
        for target in LINK.findall(text):
            target = target.strip()
            if target not in pages:
                problems.append(f"깨진 링크 [[{target}]]: {rel}")
            elif target != name:
                inbound[target] += 1

    for target in index_links:
        if target not in pages:
            problems.append(f"깨진 링크 [[{target}]]: index.md")
    for name in pages:
        if name not in index_links:
            problems.append(f"index.md에 없음: {name}")
        if inbound[name] == 0:
            problems.append(f"고아 페이지 (다른 페이지에서 링크 없음): {name}")

    print(f"페이지 {len(pages)}개 검사")
    for msg in problems:
        print("  -", msg)
    if problems:
        print(f"문제 {len(problems)}건")
        return 1
    print("문제 없음 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
