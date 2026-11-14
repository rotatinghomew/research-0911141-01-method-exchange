from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import unittest

from method_exchange.comparison import compare, normalize_policy
from method_exchange.domain import explore, validate
from method_exchange.service import Workbench
from method_exchange.server import make_server
from method_exchange.storage import fingerprint


ROOT = Path(__file__).resolve().parents[1]


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "fixtures" / "data.json").read_text())
        self.selection = json.loads((ROOT / "product.json").read_text())["selection"]
        self.policy = {"absolute": 2, "relative": 0.04}

    def test_fixture_is_valid_and_serializable(self):
        validate(self.data)
        view = explore(self.data, self.selection)
        self.assertTrue(view["rows"])
        self.assertTrue(view["notes"])
        self.assertIn("comparison", view)
        json.dumps(view, allow_nan=False)

    def test_exploration_does_not_mutate_inputs(self):
        before = deepcopy(self.data)
        explore(self.data, self.selection, self.policy)
        self.assertEqual(before, self.data)

    def test_missing_table_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            validate({})

    def test_same_method_rejected(self):
        with self.assertRaises(ValueError):
            explore(self.data, {"reference": "old", "candidate": "old"})

    def test_replicates_do_not_inflate_sample_count(self):
        view = explore(self.data, self.selection)
        self.assertLess(view["summary"]["可定量样品"], len(self.data["measurements"]))
        self.assertEqual(len({row["sample_id"] for row in view["rows"]}), len(view["rows"]))

    def test_reference_is_not_treated_as_truth(self):
        comp = compare(self.data, self.selection, self.policy)
        # Deming 回归的 lambda 来自两方法各自的复测方差，而不是把参考方法方差当 0
        self.assertIsNotNone(comp["deming"]["slope"])
        self.assertGreater(comp["repeatability"]["reference"]["degrees_of_freedom"], 0)
        self.assertGreater(comp["repeatability"]["candidate"]["degrees_of_freedom"], 0)
        self.assertNotEqual(comp["deming"]["lambda"], 0)

    def test_bias_is_shown_across_the_measuring_range(self):
        comp = compare(self.data, self.selection, self.policy)
        trend = comp["deming"]["bias_trend"]
        self.assertEqual(len(trend), 3)
        self.assertLess(trend[0]["bias"], trend[-1]["bias"])
        # 分箱覆盖观测量程，且不向外推断
        self.assertEqual(len(comp["profile"]["bins"]), 6)
        self.assertIsNotNone(comp["profile"]["evidence_range"])
        self.assertEqual(comp["profile"]["bins"][0]["range_low"],
                         comp["profile"]["evidence_range"]["low"])

    def test_tolerance_changes_change_the_verdict(self):
        strict = compare(self.data, self.selection, {"absolute": 1, "relative": 0.02})
        relaxed = compare(self.data, self.selection, {"absolute": 5, "relative": 0.1})
        strict_pass = sum(1 for bin_entry in strict["profile"]["bins"] if bin_entry["status"] == "合格")
        relaxed_pass = sum(1 for bin_entry in relaxed["profile"]["bins"] if bin_entry["status"] == "合格")
        self.assertGreater(relaxed_pass, strict_pass)

    def test_relative_only_tolerance_grows_with_reading(self):
        comp = compare(self.data, self.selection, {"absolute": 0, "relative": 0.1})
        tolerances = [bin_entry["tolerance_at_center"] for bin_entry in comp["profile"]["bins"]]
        self.assertEqual(tolerances, sorted(tolerances))

    def test_zero_policy_is_descriptive_only(self):
        comp = compare(self.data, self.selection, {"absolute": 0, "relative": 0})
        self.assertFalse(comp["policy"]["verdict_enabled"])
        self.assertTrue(all(not bin_entry["evaluable"] for bin_entry in comp["profile"]["bins"]))
        self.assertTrue(any("不输出合格" in note for note in comp["notes"]))

    def test_invalid_policy_rejected(self):
        with self.assertRaises(ValueError):
            normalize_policy({"absolute": -1, "relative": 0}, self.data)
        with self.assertRaises(ValueError):
            normalize_policy({"absolute": 0, "relative": 1.5}, self.data)
        with self.assertRaises(ValueError):
            normalize_policy({"absolute": "x", "relative": 0}, self.data)

    def test_policy_defaults_to_dataset_limits(self):
        policy = normalize_policy(None, self.data)
        self.assertEqual(policy["absolute"], self.data["limits"]["absolute"])
        self.assertEqual(policy["relative"], self.data["limits"]["relative"])
        self.assertTrue(policy["verdict_enabled"])

    def test_censored_records_are_not_zeroes(self):
        comp = compare(self.data, self.selection, self.policy)
        sample_000 = next(sample for sample in comp["samples"] if sample["sample_id"] == "sample_000")
        self.assertEqual(sample_000["pair_status"], "fully_censored")
        self.assertIsNone(sample_000["difference"])
        self.assertIn(sample_000["sample_id"],
                      [item["sample_id"] for item in comp["fully_censored_samples"]])
        # 检出限样品没有出现在任何定量分箱里
        binned = {identifier for bin_entry in comp["profile"]["bins"]
                  for identifier in bin_entry["sample_ids"]}
        self.assertNotIn("sample_000", binned)
        # sample_001 的 new_a 有一次 below_limit，但仍有可定量复测
        sample_001 = next(sample for sample in comp["samples"] if sample["sample_id"] == "sample_001")
        self.assertEqual(sample_001["pair_status"], "partial_censored")
        self.assertEqual(sample_001["candidate_censored_replicates"], [2])

    def test_single_method_batch_is_flagged_not_paired(self):
        comp = compare(self.data, {"reference": "old", "candidate": "new_b"}, self.policy)
        late = next(group for group in comp["lot_groups"] if group["name"] == "late")
        self.assertTrue(late["only_one_method"])
        self.assertEqual(late["n_pairs"], 0)
        self.assertEqual(late["methods_measured"], ["new_b"])
        self.assertEqual(comp["coverage"]["one_sided_censored_pairs"], 8)

    def test_verdict_is_traceable_to_samples(self):
        comp = compare(self.data, self.selection, self.policy)
        for bin_entry in comp["profile"]["bins"]:
            if bin_entry["status"] == "超限":
                self.assertTrue(bin_entry["exceeding_samples"])
                for sample_id in bin_entry["exceeding_samples"]:
                    sample = next(item for item in comp["samples"] if item["sample_id"] == sample_id)
                    self.assertFalse(sample["within_tolerance"])
        all_binned = {identifier for bin_entry in comp["profile"]["bins"]
                      for identifier in bin_entry["sample_ids"]}
        paired = {sample["sample_id"] for sample in comp["samples"]
                  if sample["pair_status"] in ("quantitative", "partial_censored")}
        self.assertEqual(all_binned, paired)

    def test_insufficient_bins_keep_blank_conclusion(self):
        # 只保留 4 个样品的小数据集，分箱必然证据不足
        small = deepcopy(self.data)
        keep = {"sample_002", "sample_010", "sample_020", "sample_030"}
        small["measurements"] = [row for row in small["measurements"] if row["sample_id"] in keep]
        comp = compare(small, self.selection, self.policy)
        weak = [bin_entry for bin_entry in comp["profile"]["bins"]
                if bin_entry["status"] in ("证据不足", "区间无证据")]
        self.assertTrue(weak)
        self.assertTrue(all(not bin_entry["evaluable"] for bin_entry in weak))
        # 少量点不做 LoA 或回归时显式说明而不是静默给数
        tiny = deepcopy(small)
        tiny["measurements"] = [row for row in small["measurements"] if row["sample_id"] == "sample_010"]
        tiny_comp = compare(tiny, self.selection, self.policy)
        self.assertIsNone(tiny_comp["deming"]["slope"])
        self.assertIsNotNone(tiny_comp["deming"]["note"])
        self.assertIsNone(tiny_comp["bland_altman"]["loa_lower"])

    def test_bad_limits_in_dataset_rejected(self):
        bad = deepcopy(self.data)
        bad["limits"] = {"absolute": -1, "relative": 0}
        with self.assertRaises(ValueError):
            validate(bad)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workbench = Workbench(ROOT, self.temporary.name)
        self.selection = {"reference": "old", "candidate": "new_a"}

    def test_content_addressed_import_is_idempotent(self):
        data = self.workbench.store.dataset(self.workbench.default_revision)
        uploaded = self.workbench.upload({"label": "再次导入", "data": data})
        self.assertEqual(uploaded["revision"], self.workbench.default_revision)
        self.assertEqual(len(self.workbench.store.datasets()), 1)

    def test_browser_numeric_roundtrip_preserves_fingerprint(self):
        self.assertEqual(fingerprint({"values": [1.0, 2, -0.0]}), fingerprint({"values": [1, 2.0, 0]}))

    def test_saved_description_keeps_original_dataset(self):
        saved = self.workbench.save({"title": "会议记录"})
        original = deepcopy(saved)
        data = self.workbench.store.dataset(self.workbench.default_revision)
        data["context_note"] = "新资料"
        newer = self.workbench.upload({"label": "新数据", "data": data})
        self.assertNotEqual(newer["revision"], saved["revision"])
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened, original)
        self.assertEqual(fingerprint(reopened["dataset"]), saved["revision"])

    def test_saved_tolerance_is_frozen_and_recomputed_server_side(self):
        saved = self.workbench.save({"title": "误差约定冻结", "selection": self.selection,
                                     "tolerance": {"absolute": 1, "relative": 0.02}})
        self.assertEqual(saved["selection"]["tolerance"], {"absolute": 1, "relative": 0.02})
        self.assertEqual(saved["result"]["view"]["comparison"]["policy"]["absolute"], 1)
        # 上传新批次后，旧记录仍引用旧版本与旧误差约定
        data = self.workbench.store.dataset(self.workbench.default_revision)
        data["measurements"].append(deepcopy(data["measurements"][-1]))
        data["measurements"][-1]["sample_id"] = "sample_999"
        data["measurements"][-1]["replicate"] = 9
        self.workbench.upload({"label": "追加批次", "data": data})
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened["selection"]["tolerance"], {"absolute": 1, "relative": 0.02})
        self.assertEqual(reopened["revision"], saved["revision"])
        self.assertEqual(deepcopy(reopened["result"]), deepcopy(saved["result"]))

    def test_invalid_upload_leaves_no_dataset(self):
        with self.assertRaises(ValueError):
            self.workbench.upload({"label": "坏数据", "data": {}})
        self.assertEqual(len(self.workbench.store.datasets()), 1)

    def test_unknown_version_cannot_fall_back(self):
        with self.assertRaises(LookupError):
            self.workbench.inspect({"revision": "missing"})

    def test_blank_title_rejected(self):
        with self.assertRaises(ValueError):
            self.workbench.save({"title": " "})

    def test_invalid_tolerance_rejected_at_service(self):
        with self.assertRaises(ValueError):
            self.workbench.inspect({"selection": self.selection,
                                    "tolerance": {"absolute": 0, "relative": -0.1}})

    def test_saved_view_is_reproducible_after_restart(self):
        saved = self.workbench.save({"title": "重启核对"})
        restarted = Workbench(ROOT, self.temporary.name)
        self.assertEqual(saved, restarted.store.notebook(saved["id"]))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.server = make_server(ROOT, self.temporary.name, port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temporary.cleanup()

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        return urlopen(request)

    def test_http_explore_save_and_read(self):
        with urlopen(self.base + "/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")
        with self.post("/api/notebooks", {"title": "页面保存"}) as response:
            saved = json.load(response)
            self.assertEqual(response.status, 201)
        self.assertIn("tolerance", saved["selection"])
        with urlopen(self.base + "/api/notebooks/" + str(saved["id"])) as response:
            self.assertEqual(saved, json.load(response))

    def test_explore_accepts_editable_tolerance(self):
        with self.post("/api/explore", {"tolerance": {"absolute": 3, "relative": 0.05}}) as response:
            result = json.load(response)
        self.assertEqual(result["selection"]["tolerance"], {"absolute": 3, "relative": 0.05})
        self.assertEqual(result["view"]["comparison"]["policy"]["relative"], 0.05)

    def test_bad_tolerance_returns_client_error(self):
        request = Request(self.base + "/api/explore",
                          data=json.dumps({"tolerance": {"absolute": 0, "relative": 5}}).encode(),
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_bad_data_returns_client_error(self):
        request = Request(self.base + "/api/datasets", data=b'{"label":"bad","data":{}}',
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_unknown_route_is_not_static_file_access(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/../product.json")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
