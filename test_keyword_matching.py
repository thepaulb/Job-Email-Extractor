#!/usr/bin/env python3
"""
Tests for the matches_keywords function in job_link_extractor.py
Verifies word-boundary matching to prevent substring false positives.
"""

from job_link_extractor import matches_keywords

# Each test: (url, link_text, keywords, expected_result, description)
TESTS = [
    # --- FALSE POSITIVES (should NOT match) ---
    (
        "https://example.com/jobs/director-of-marketing",
        "Director of Marketing",
        ["CTO"],
        False,
        "CTO should not match inside 'Director'",
    ),
    (
        "https://example.com/ncDSaWqweCTO/job/123",
        "Software Engineer",
        ["CTO"],
        False,
        "CTO should not match random uppercase substring in URL",
    ),
    (
        "https://example.com/ncdsawqwecto/job/123",
        "Software Engineer",
        ["CTO"],
        False,
        "CTO should not match random lowercase substring in URL",
    ),
    (
        "https://example.com/jobs/technical-director",
        "Technical Director",
        ["CTO"],
        False,
        "CTO should not match 'Technical Director' (contains 'cto' in director)",
    ),

    # --- TRUE POSITIVES (should match) ---
    (
        "https://example.com/jobs/cto-role",
        "CTO at Startup",
        ["CTO"],
        True,
        "CTO in link text as standalone word",
    ),
    (
        "https://example.com/jobs/view/123",
        "CTO",
        ["CTO"],
        True,
        "CTO as entire link text",
    ),
    (
        "https://example.com/jobs/chief-cto-search",
        "",
        ["CTO"],
        True,
        "CTO as a word segment in URL path (hyphen-separated)",
    ),
    (
        "https://example.com/jobs/view/123",
        "Chief Technology Officer",
        ["chief technology officer"],
        True,
        "Multi-word keyword match in link text",
    ),
    (
        "https://example.com/jobs/123",
        "Digital Marketing Manager",
        ["digital"],
        True,
        "'digital' should still match as a standalone word in text",
    ),
    (
        "https://example.com/jobs/digital-transformation-lead",
        "",
        ["digital"],
        True,
        "'digital' should match in hyphen-separated URL path",
    ),
]


def run_tests():
    passed = 0
    failed = 0

    for url, text, kws, expected, desc in TESTS:
        result = matches_keywords(url, text, kws)
        status = "PASS" if result == expected else "FAIL"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"  {status}: {desc}")
        if result != expected:
            print(f"         Got {result}, expected {expected}")
            print(f"         url={url}, text=\"{text}\", keywords={kws}")

    print(f"\n{passed}/{passed + failed} tests passed")
    if failed:
        print(f"{failed} test(s) FAILED")
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
