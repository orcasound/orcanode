#!/usr/bin/env python3
"""Offline unit tests for archive_feed pure logic (no files/network/ffmpeg).

Run:  python3 test_archive.py
"""

import calendar
import sys

import archive_feed as af

# One explicit strptime pattern for the whole filename (selects + parses time).
PAT = "sensorA_%Y%m%d_%H%M%S.wav"


def check(name, cond):
    print(("PASS" if cond else "FAIL") + ": " + name)
    if not cond:
        raise AssertionError(name)


def main():
    # 1. timestamp parsing -> UTC epoch
    ts = af.parse_timestamp("sensorA_20200102_030000.wav", PAT)
    check("parse timestamp UTC epoch",
          ts == calendar.timegm((2020, 1, 2, 3, 0, 0, 0, 0, 0)))
    check("parse timestamp no-match -> None",
          af.parse_timestamp("readme.txt", PAT) is None)

    # 2. index build: pattern selects matching names only, sorted ascending
    names = [
        "sensorA_20200102_030500.wav",
        "sensorA_20200102_030000.wav",
        "sensorB_20200102_030000.wav",   # different source -> excluded by pattern
        "sensorA_20200102_030000.txt",   # different extension -> excluded
        "notes.md",                      # no timestamp
    ]
    idx = af.build_index(names, PAT)
    check("index count (pattern filter)", len(idx) == 2)
    check("index sorted ascending", idx[0][1].endswith("030000.wav"))

    # Build a clean two-slot index at T, T+300
    T = calendar.timegm((2020, 1, 2, 3, 0, 0, 0, 0, 0))
    two = [(T, "a.wav"), (T + 300, "b.wav")]

    # 3. mid-file -> offset into current file
    name, off, dur = af.find_slot(two, T + 100, 300)
    check("mid-file name", name == "a.wav")
    check("mid-file offset", off == 100)
    check("mid-file remaining dur", dur == 200)

    # 4. exact boundary -> next file at offset 0
    name, off, dur = af.find_slot(two, T + 300, 300)
    check("boundary name", name == "b.wav" and off == 0 and dur == 300)

    # 5. before first file -> silence until it
    name, off, dur = af.find_slot(two, T - 50, 300)
    check("pre-start silence", name is None and dur == 50)

    # 6. after last file -> bounded silence slot
    name, off, dur = af.find_slot(two, T + 700, 300)
    check("post-end bounded silence", name is None and dur == 300)

    # 7. gap between files -> silence until next known file
    gap = [(T, "a.wav"), (T + 600, "c.wav")]  # T+300 missing
    name, off, dur = af.find_slot(gap, T + 350, 300)
    check("gap silence until next", name is None and dur == 250)

    # 8. empty index -> bounded silence
    name, off, dur = af.find_slot([], T, 300)
    check("empty index silence", name is None and dur == 300)

    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
