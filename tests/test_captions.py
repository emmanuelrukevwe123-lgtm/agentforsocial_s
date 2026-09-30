import captions


def heard(*items):
    return [{"text": t, "start": s, "end": e} for t, s, e in items]


def test_align_uses_script_spelling_with_recorded_timing():
    script = {1: "Supabase RLS is on.", 2: "Done."}
    rec = heard(("super", 0.0, 0.3), ("base", 0.3, 0.6), ("RLS", 0.7, 1.0), ("is", 1.0, 1.1),
                ("on.", 1.1, 1.4), ("Done.", 2.0, 2.4))
    words, ratio = captions.align(script, rec)
    assert [w["text"] for w in words] == ["Supabase", "RLS", "is", "on.", "Done."]
    assert words[0]["start"] == 0.0 and words[0]["end"] == 0.6  # "super base" collapsed onto one word
    assert words[1]["start"] == 0.7
    assert words[4]["line"] == 2
    assert 0.7 < ratio <= 1.0


def test_align_interpolates_unheard_words():
    script = {1: "one two three four"}
    rec = heard(("one", 0.0, 0.5), ("four", 2.0, 2.5))
    words, _ = captions.align(script, rec)
    assert words[1]["start"] == 0.5 and words[2]["end"] == 2.0
    assert all(w["end"] >= w["start"] for w in words)


def test_line_times_tile_the_audio():
    words = [{"text": "a", "start": 0.4, "end": 0.6, "line": 1},
             {"text": "b", "start": 1.5, "end": 1.9, "line": 2}]
    lines = captions.line_times(words, 3.0)
    assert lines[0]["start"] == 0.0 and lines[0]["end"] == 1.5
    assert lines[1]["start"] == 1.5 and lines[1]["end"] == 3.0


def test_chunk_breaks_on_punctuation_line_and_size():
    words = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25, "line": 1 if i < 5 else 2}
             for i, t in enumerate(["a", "b,", "c", "d", "e", "f"])]
    assert [[w["text"] for w in c] for c in captions.chunk(words, 3)] == [["a", "b,"], ["c", "d", "e"], ["f"]]


def test_time_formats():
    assert captions.srt_time(3723.456) == "01:02:03,456"
    assert captions.ass_time(3723.456) == "1:02:03.46"


def test_ass_highlights_one_word_per_event_and_escapes():
    words = [{"text": "{x}", "start": 0.0, "end": 0.4, "line": 1},
             {"text": "y", "start": 0.5, "end": 0.9, "line": 1}]
    ass = captions.to_ass(captions.chunk(words, 3), "9x16")
    events = [ln for ln in ass.splitlines() if ln.startswith("Dialogue")]
    assert len(events) == 2
    assert "PlayResY: 1920" in ass
    assert "{x}" not in ass and "(x)" in ass
    assert events[0].count("\\c&H") == 1 and events[1].endswith("y{\\r}")


def test_srt_has_no_overlaps():
    words = [{"text": str(i), "start": i * 0.5, "end": i * 0.5 + 0.45, "line": 1} for i in range(20)]
    srt = captions.to_srt(captions.chunk(words, 8))
    times = [ln for ln in srt.splitlines() if "-->" in ln]
    ends = [t.split(" --> ")[1] for t in times]
    starts = [t.split(" --> ")[0] for t in times]
    assert all(e <= s for e, s in zip(ends, starts[1:]))
