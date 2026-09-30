import animate
import papercut as pc


def test_at_word_lands_just_before_the_spoken_word():
    words = [{"text": "Kubernetes", "line": 7, "start": 30.0}, {"text": "SSH", "line": 7, "start": 31.5}]
    assert animate.element_start({"at_word": "ssh"}, (7, 7), words, 28.0) == 31.5 - 28.0 - 0.08
    assert animate.element_start({"at_word": "missing", "at": 1.0}, (7, 7), words, 28.0) == 1.0


def test_estimated_timing_without_voice(tmp_path):
    (tmp_path / "script.md").write_text("## Script\n[1] one two three four five\n[2] six\n", encoding="utf-8")
    lines, words, total, real = animate.load_timing(tmp_path)
    assert not real and [ln["n"] for ln in lines] == [1, 2]
    assert lines[1]["start"] == lines[0]["end"] and total == lines[1]["end"]
    assert words[5]["line"] == 2


def test_element_hidden_before_start_and_settles_on_target():
    el = {"x": 0.5, "y": 0.5, "enter": "drop", "_start": 1.0}
    stage = (0, 0, 1000)
    assert animate.transform(el, 0.5, 6, 0, 7, stage, (100, 100)) is None
    x, y, sx, sy, rot = animate.transform(el, 3.0, 36, 0, 7, stage, (100, 100))
    assert abs(x - 500) < 4 and abs(y - 500) < 4 and sx == sy == 1.0 and abs(rot) < 1


def test_counter_counts_up():
    el = {"count": [0, 14], "suffix": " DAYS", "count_dur": 1.0}
    assert animate.counter_value(el, 0) == "0 DAYS"
    assert animate.counter_value(el, 5) == "14 DAYS"


def test_every_icon_draws():
    for name in pc.ICONS:
        sprite = pc.icon_sprite(name, 60)
        assert sprite.mode == "RGBA" and sprite.getbbox(), name


def test_naira_falls_back_to_a_font_that_has_it():
    f = pc.font_for("stencil", 60, "₦")
    assert pc._covers(f, "₦")


def test_moves_reach_their_target_and_exit_hides():
    el = {"x": 0.2, "y": 0.5, "enter": "none", "_start": 0.0,
          "moves": [{"_start": 1.0, "x": 0.8, "y": 0.5, "dur": 0.5}],
          "exit": {"_start": 3.0, "type": "fly-left", "dur": 0.4}}
    stage = (0, 0, 1000)
    x, *_ = animate.transform(el, 0.5, 6, 0, 7, stage, (100, 100))
    assert abs(x - 200) < 4
    x, *_ = animate.transform(el, 2.0, 24, 0, 7, stage, (100, 100))
    assert abs(x - 800) < 4
    assert animate.transform(el, 3.5, 42, 0, 7, stage, (100, 100)) is None


def test_slam_knocks_its_neighbour():
    scene = {"elements": [{"x": 0.5, "y": 0.5, "enter": "slam", "dur": 0.3, "_start": 1.0},
                          {"x": 0.55, "y": 0.5, "enter": "none", "_start": 0.0}]}
    impacts = animate.impacts_for(scene)
    assert impacts and impacts[0]["t"] == 1.3
    still = animate.transform(scene["elements"][1], 1.0, 12, 1, 7, (0, 0, 1000), (100, 100), impacts)
    hit = animate.transform(scene["elements"][1], 1.35, 16, 1, 7, (0, 0, 1000), (100, 100), impacts)
    assert abs(hit[1] - 500) > abs(still[1] - 500)  # hops on impact
    assert animate.camera_shake(impacts, 1.35, 16, 1000, 7) != (0.0, 0.0)


def test_every_transition_blends_two_frames():
    from PIL import Image
    a, b = Image.new("RGB", (120, 200), (255, 0, 0)), Image.new("RGB", (120, 200), (0, 0, 255))
    for kind in animate.TRANSITIONS:
        mid = animate.apply_transition(kind, a, b, 0.5, 3)
        assert mid.size == (120, 200), kind
        assert animate.apply_transition(kind, a, b, 1.0, 3) is b
    assert animate.apply_transition("slide-left", None, b, 0.3, 3) is b


def test_moving_background_changes_on_twos():
    bg = animate.MovingBackground((108, 192), {"bg": "sky", "pattern": "dots", "floaters": 5}, 1)
    f0, f1, f4 = bg.frame(0), bg.frame(1), bg.frame(4)
    assert f0.tobytes() == f1.tobytes() and f0.tobytes() != f4.tobytes()
