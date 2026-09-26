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
    check("index scales start to frames",
          af.build_index(["sensorA_20200102_030000.wav"], PAT, 48000)[0][0]
          == calendar.timegm((2020, 1, 2, 3, 0, 0, 0, 0, 0)) * 48000)

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

    # 9. split_per_channel: one value fans out, N values pass through
    check("split one value fans out",
          af.split_per_channel("/mnt/a", 3, "X") == ["/mnt/a"] * 3)
    check("split N values pass through",
          af.split_per_channel("a, b, c", 3, "X") == ["a", "b", "c"])
    try:
        af.split_per_channel("a,b", 3, "ARCHIVE_GAINS")
        check("split wrong count raises", False)
    except ValueError:
        check("split wrong count raises", True)

    # 10. find_slots: all channels advance on the earliest boundary
    ch_a = [(T, "a0.wav"), (T + 300, "a1.wav")]
    ch_b = [(T + 120, "b0.wav")]              # starts mid-way through a0
    slots, dur = af.find_slots([ch_a, ch_b], T, 300)
    check("slots one per channel", len(slots) == 2)
    check("slot 0 plays its file", slots[0][0] == "a0.wav")
    check("slot 1 is silent until its file", slots[1][0] is None)
    check("dur clipped to earliest boundary", dur == 120)

    # at T+120 both have audio, and the shared dur runs to a0's end
    slots, dur = af.find_slots([ch_a, ch_b], T + 120, 300)
    check("both channels playing", slots[0][0] == "a0.wav" and slots[1][0] == "b0.wav")
    check("dur to earliest end", dur == 180)

    # a channel with nothing at all stays silent without stalling the others
    slots, dur = af.find_slots([ch_a, []], T, 300)
    check("empty channel silent", slots[1][0] is None)
    check("empty channel does not shorten slot", dur == 300)

    # 10b. whole-frame arithmetic must never yield a zero-length slot, or the feed
    # spins forever making no progress
    for pos in range(T - 2, T + 902):
        _, dur = af.find_slots([ch_a, ch_b], pos, 300)
        if dur <= 0:
            check("slot never zero-length (pos=%d)" % pos, False)
    check("slot never zero-length across boundaries", True)

    # walking the timeline by whole slots lands exactly on each boundary
    pos, seen = T, []
    for _ in range(4):
        slots, dur = af.find_slots([ch_a], pos, 300)
        seen.append((pos - T, slots[0][0], dur))
        pos += dur
    check("slots tile the timeline exactly",
          seen == [(0, "a0.wav", 300), (300, "a1.wav", 300),
                   (600, None, 300), (900, None, 300)])

    # 11. interleave: frame-interleaved output, channel order preserved
    import array
    mono = lambda vals: array.array("h", vals).tobytes()
    out = af.interleave([mono([1, 2, 3]), mono([-1, -2, -3])], 3)
    check("interleave byte length", len(out) == 3 * 2 * af.SAMPLE_BYTES)
    got = array.array("h"); got.frombytes(out)
    check("interleave order", list(got) == [1, -1, 2, -2, 3, -3])
    check("interleave single channel passthrough",
          af.interleave([mono([7, 8])], 2) == mono([7, 8]))

    # 12. read_padded: a missing source becomes silence of the exact size
    check("read_padded fills absent source", af.read_padded(None, 8) == bytes(8))

    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
