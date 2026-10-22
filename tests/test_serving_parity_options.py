"""scripts/serving_parity.py: the default still checks the registered serving model and writes the incumbent's evidence
files; a candidate-scoped check loads an explicit model (checksums verified), needs its own output and can never
overwrite the incumbent's evidence. The full replay needs recorded data and is run as a separate verification step."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("serving_parity", ROOT / "scripts" / "serving_parity.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

SYNTH = "synthetic-demo.lightgbm.dyn-v2.v1"


def test_default_arguments_keep_the_incumbent_outputs():
    a = sp.parse_args([])
    assert not a.candidate and a.output is None
    summary, detail = sp.resolve_outputs(a, "some.model")
    assert summary == ROOT / "reports" / "serving_parity.json"
    assert detail.name == "serving_parity_some.model.json" and detail.parent.name == "verification"


@pytest.mark.parametrize("argv", [["--model-dir", "x"], ["--registry", "r.json"], ["--experiment-dir", "e"],
                                  ["--pipeline", "lightgbm:dyn-v2"], ["--personalization", "none"]])
def test_candidate_options_require_an_explicit_output(argv):
    with pytest.raises(SystemExit):
        sp.parse_args(argv)


def test_model_dir_and_registry_are_alternatives_and_version_needs_a_registry(tmp_path):
    with pytest.raises(SystemExit):
        sp.parse_args(["--model-dir", "x", "--registry", "r.json", "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit):
        sp.parse_args(["--model-version", "v", "--output", str(tmp_path / "o.json")])


@pytest.mark.parametrize("target", ["reports/serving_parity.json", "reports/serving_parity.md"])
def test_candidate_cannot_overwrite_the_incumbent_public_evidence(target):
    a = sp.parse_args(["--model-dir", "x", "--output", str(ROOT / target)])
    with pytest.raises(SystemExit, match="incumbent"):
        sp.resolve_outputs(a, "candidate.model")


def test_candidate_cannot_overwrite_existing_per_participant_evidence(tmp_path):
    vdir = sp.paths().artifacts / "verification"
    existing = sorted(vdir.glob("serving_parity_*.json")) if vdir.is_dir() else []
    if not existing:
        pytest.skip("no saved per-participant parity evidence on this installation")
    a = sp.parse_args(["--model-dir", "x", "--output", str(tmp_path / "o.json"), "--detail-output", str(existing[0])])
    with pytest.raises(SystemExit, match="incumbent"):
        sp.resolve_outputs(a, "candidate.model")


def test_candidate_detail_with_participant_ids_defaults_to_the_git_ignored_artifacts_tree(tmp_path):
    a = sp.parse_args(["--model-dir", "x", "--output", str(tmp_path / "parity_c.json")])
    summary, detail = sp.resolve_outputs(a, "candidate.model")
    assert summary == (tmp_path / "parity_c.json").resolve()
    assert detail == (sp.paths().artifacts / "verification" / "candidate_parity" / "parity_c.per_participant.json").resolve()
    a = sp.parse_args(["--model-dir", "x", "--output", str(tmp_path / "c.json"), "--detail-output", str(tmp_path / "d.json")])
    assert sp.resolve_outputs(a, "candidate.model")[1] == (tmp_path / "d.json").resolve()


def _synthetic_model_copy(tmp_path: Path) -> Path:
    src = sp.paths().artifacts / "models" / SYNTH
    dst = tmp_path / "candidate_model"
    shutil.copytree(src, dst)
    return dst


def test_model_dir_loads_without_the_registry_and_verifies_checksums(synthetic_ready, tmp_path):
    mdir = _synthetic_model_copy(tmp_path)
    a = sp.parse_args(["--model-dir", str(mdir), "--output", str(tmp_path / "o.json")])
    model, source = sp.load_model(a)
    assert model.model_version == SYNTH and model.artifact_dir == mdir.resolve() and source["source"] == "model_dir"
    assert set(model.horizons) == {30, 60}
    # an altered model file must fail clearly, never be checked under the same name
    (mdir / "h30.lgb.txt").write_text((mdir / "h30.lgb.txt").read_text() + "\n")
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        sp.load_model(a)


def test_registry_option_resolves_the_named_version_from_another_registry(synthetic_ready, tmp_path):
    mdir = _synthetic_model_copy(tmp_path)
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"models": [{"model_version": SYNTH, "artifact_dir": str(mdir)}],
                               "serving": {"dataset_replay": SYNTH}}))
    model, source = sp.load_model(sp.parse_args(["--registry", str(reg), "--output", str(tmp_path / "o.json")]))
    assert model.artifact_dir == mdir.resolve() and source["registry_sha256"] == sp.sha256_file(reg)
    with pytest.raises(SystemExit, match="not in"):
        sp.load_model(sp.parse_args(["--registry", str(reg), "--model-version", "other",
                                     "--output", str(tmp_path / "o.json")]))


def test_raw_capture_records_the_unrounded_final_value_and_keeps_the_forecast():
    class Engine:
        def _build_forecast(self, t, fid, row, quality, reasons, latest_idx, support_ids, pop_t, corr, *rest):
            return {"t": t, "rest": rest}

    eng, raw = Engine(), {}
    assert sp.capture_raw(eng, raw)
    out = eng._build_forecast(100.0, "f", None, "ok", [], 0, [], {30: 150.04, 60: None}, {30: 1.25, 60: None}, "x")
    assert out == {"t": 100.0, "rest": ("x",)}
    assert raw == {(100.0, 30): pytest.approx(151.29)}  # 60 has no population value: no forecast, no raw entry
    eng2, raw2 = Engine(), {}
    sp.capture_raw(eng2, raw2)
    eng2._build_forecast(5.0, "f", None, "ok", [], 0, [], {30: 120.0}, {30: None})
    assert raw2 == {(5.0, 30): 120.0}  # a missing correction adds nothing


def test_tree_digest_is_independent_of_location_and_detects_changes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "sub").mkdir(parents=True)
        (d / "m.txt").write_text("model")
        (d / "sub" / "n.json").write_text("{}")
    assert sp.tree_sha256(a) == sp.tree_sha256(b)
    (b / "m.txt").write_text("model ")
    assert sp.tree_sha256(a) != sp.tree_sha256(b)
