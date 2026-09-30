from pathlib import Path

import pytest

import cut

LINES = [{"n": 1, "start": 0.0, "end": 2.0}, {"n": 2, "start": 2.0, "end": 3.5}, {"n": 3, "start": 3.5, "end": 6.0}]


def test_segment_times_tile_the_voice_track():
    segs = [{"lines": [1, 2]}, {"line": 3}]
    assert cut.segment_times(segs, LINES, 6.0) == [(0.0, 3.5), (3.5, 2.5)]


def test_segment_times_rejects_out_of_order():
    with pytest.raises(SystemExit):
        cut.segment_times([{"line": 3}, {"line": 1}], LINES, 6.0)


def test_segment_times_rejects_unknown_line():
    with pytest.raises(SystemExit):
        cut.segment_times([{"line": 9}], LINES, 6.0)


@pytest.mark.parametrize("layout", ["blur", "fit", "fill"])
def test_layout_filters_end_in_label(layout):
    f = cut.layout_filter({"layout": layout}, 1080, 1920, "0x000000", 4)
    assert f.startswith("[src4]") and f.endswith("[lay4]")


def test_crop_layout():
    f = cut.layout_filter({"layout": "crop", "crop": [420, 0, 1080, 1080]}, 1080, 1920, "0x000000", 0)
    assert "crop=1080:1080:420:0" in f


def test_build_command_uses_placeholder_and_relative_captions(tmp_path: Path):
    (tmp_path / "captions_9x16.ass").write_text("x")
    timeline = {"fps": 30, "segments": [{"line": 1, "clip": None}, {"line": 2, "clip": None}]}
    args = cut.build_command(tmp_path, timeline, [(0.0, 2.0), (2.0, 1.0)], "9x16", voice=Path("voice.wav"),
                             total=3.0, draft=False, captions=True, loudnorm=True, out=Path("out/x.mp4"))
    graph = args[args.index("-filter_complex") + 1]
    assert args.count("lavfi") == 2
    assert "concat=n=2:v=1:a=0[vc];[vc]ass=captions_9x16.ass[vout]" in graph
    assert "[2:a]loudnorm" in graph
    assert args[-1] == str(Path("out/x.mp4"))


def test_music_loops_with_crossfade_and_ducks_under_voice():
    music = {"path": Path("Music/song.wav"), "duration": 41.8, "level": -30.0, "start": 0.0}
    graph = ";".join(cut.music_chains(3, 4, music, 50.0, True))
    assert "asplit=2[m0][m1]" in graph and "acrossfade=d=2.0" in graph
    assert "sidechaincompress" in graph and "afade=t=out:st=47.500" in graph
    assert graph.endswith("[aout]")
    short = ";".join(cut.music_chains(3, 4, {**music, "duration": 120.0}, 50.0, True))
    assert "acrossfade" not in short
