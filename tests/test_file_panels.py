import pathlib

from eval_dashboard.main import file_panel_dirs


def test_same_path_mounts_eval_only(tmp_path):
    dirs = file_panel_dirs(str(tmp_path), str(tmp_path))
    assert dirs["controlled"] == str(tmp_path.resolve())
    assert dirs["controlled_kind"] == "eval"
    assert dirs["operational"] is None


def test_only_records_dir_is_saved_file_comparison(tmp_path):
    dirs = file_panel_dirs(str(tmp_path), str(tmp_path / "missing-eval"))
    assert dirs["controlled"] == str(tmp_path.resolve())
    assert dirs["controlled_kind"] == "saved-files"
    assert dirs["operational"] is None


def test_distinct_dirs_split_panels(tmp_path):
    rec = tmp_path / "records"
    ev = tmp_path / "eval"
    rec.mkdir()
    ev.mkdir()
    dirs = file_panel_dirs(str(rec), str(ev))
    assert dirs["controlled"] == str(ev.resolve())
    assert dirs["controlled_kind"] == "eval"
    assert dirs["operational"] == str(rec.resolve())


def test_only_eval_dir_has_no_operational(tmp_path):
    ev = tmp_path / "eval"
    ev.mkdir()
    dirs = file_panel_dirs(str(tmp_path / "missing-records"), str(ev))
    assert dirs["controlled"] == str(ev.resolve())
    assert dirs["controlled_kind"] == "eval"
    assert dirs["operational"] is None


def test_neither_dir_is_empty():
    dirs = file_panel_dirs("/no/such/records", "/no/such/eval")
    assert dirs == {"controlled": None, "operational": None, "controlled_kind": None}


def test_symlink_same_tree_is_not_duplicated(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    dirs = file_panel_dirs(str(real), str(link))
    assert dirs["operational"] is None
    assert pathlib.Path(dirs["controlled"]).resolve() == real.resolve()
    assert dirs["controlled_kind"] == "eval"
