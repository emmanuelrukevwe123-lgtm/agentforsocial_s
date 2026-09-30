import json

import pytest

import db
import package


def test_import_skips_near_duplicates(tmp_project):
    _, con = tmp_project
    added, skipped = db.import_ideas(con, [
        {"title": "Supabase RLS in 60 seconds", "pillar": "build"},
        {"title": "Supabase RLS in 60 seconds!", "pillar": "build"},
        {"title": "Why my kind cluster failed kube-bench", "pillar": "k8s", "score": 5},
    ])
    assert len(added) == 2 and len(skipped) == 1
    assert db.backlog(con, 1)[0]["pillar"] == "k8s"  # highest score first


def test_video_lifecycle_and_approval_gate(tmp_project):
    tmp, con = tmp_project
    idea = db.add_idea(con, "Seven projects, 14 days", "build")
    vid = db.new_video(con, idea, date="20261005")
    assert vid == "20261005-seven-projects-14-days"
    script = tmp / "media" / vid / "script.md"
    assert script.exists()
    script.write_text("---\ntitle: T\n---\n## Script\n[1] Hello there.\n[2] Bye.\n", encoding="utf-8")

    db.save_script(con, vid)  # fact check pending
    with pytest.raises(SystemExit, match="Fact check"):
        db.approve_script(con, vid)

    db.save_script(con, vid, fact_check="pass")
    script.write_text(script.read_text() + "[3] Sneaky edit.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="changed"):
        db.approve_script(con, vid)

    db.save_script(con, vid, fact_check="pass")
    assert db.approve_script(con, vid) == 3
    assert db.get_video(con, vid)["status"] == "approved"


def test_status_never_moves_backwards(tmp_project):
    _, con = tmp_project
    vid = db.new_video(con, db.add_idea(con, "x", "linux"), date="20261001")
    db.add_post(con, vid, "youtube", "https://youtu.be/x")
    db.set_video_status(con, vid, "cut")
    assert db.get_video(con, vid)["status"] == "published"


def test_stats_use_latest_snapshot_only(tmp_project):
    _, con = tmp_project
    vid = db.new_video(con, db.add_idea(con, "x", "k8s"), date="20261001")
    db.add_post(con, vid, "tiktok", "https://tiktok.com/x")
    db.add_metrics(con, vid, "tiktok", views=100)
    db.add_metrics(con, vid, "tiktok", views=250, likes=9)
    s = db.stats(con)
    assert s["by_platform"]["tiktok"]["views"] == 250 and s["published_videos"] == 1


def _pkg(**over):
    pkg = {"youtube": {"title": "Supabase RLS", "description": "d", "tags": ["a"]},
           "tiktok": {"caption": "c", "hashtags": []}, "thumbnail_text": "RLS",
           "ai_disclosure": {"label_required": False, "reason": "own voice"}}
    pkg.update(over)
    return pkg


def test_package_validation():
    assert package.validate(_pkg(), "own") == ([], [])
    errors, _ = package.validate(_pkg(thumbnail_text=""), "own")
    assert "missing thumbnail_text" in errors
    errors, _ = package.validate(_pkg(youtube={"title": "x" * 101, "description": "d", "tags": ["a"]}), "own")
    assert any("limit 100" in e for e in errors)
    errors, _ = package.validate(_pkg(tiktok={"caption": "Guaranteed job in 30 days"}), "own")
    assert any("guaranteed" in e for e in errors)
    _, warnings = package.validate(_pkg(), "kokoro")
    assert any("AI label" in w for w in warnings)
    errors, _ = package.validate(_pkg(), "edge-tts-draft")
    assert any("edge-tts" in e for e in errors)
    assert json.dumps(_pkg())  # sanity
