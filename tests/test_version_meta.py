from eval_dashboard.main import load_version_meta


def test_plain_int_entry_has_no_parent(tmp_path):
    p = tmp_path / "versions.yaml"
    p.write_text("upstream-act-teacher: 0\n")
    meta = load_version_meta(str(p))
    assert meta["upstream-act-teacher"] == {"size": 0, "parent": None}


def test_dict_entry_carries_parent(tmp_path):
    p = tmp_path / "versions.yaml"
    p.write_text(
        "act-v2-ft160:\n"
        "  size: 160\n"
        "  parent: upstream-act-teacher\n"
    )
    meta = load_version_meta(str(p))
    assert meta["act-v2-ft160"] == {"size": 160, "parent": "upstream-act-teacher"}


def test_both_shapes_coexist(tmp_path):
    p = tmp_path / "versions.yaml"
    p.write_text(
        "eval-teacher-v1: 0\n"
        "eval-ft-20ep:\n"
        "  size: 20\n"
        "  parent: eval-teacher-v1\n"
    )
    meta = load_version_meta(str(p))
    assert meta["eval-teacher-v1"]["parent"] is None
    assert meta["eval-ft-20ep"]["parent"] == "eval-teacher-v1"


def test_missing_file_returns_empty():
    assert load_version_meta("/nonexistent/path/versions.yaml") == {}
