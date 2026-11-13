"""样本血缘模块测试。

覆盖需求里的每个硬约束：
1. 去重合并保留全部来源；
2. 校验隔离样本仍有完整轨迹；
3. 跨批次续做幂等，不重复追加、不丢断点前证据；
4. 缺失来源的旧样例显式标注证据缺口；
5. 重演只生成实验轨迹，正式交付证据不可变；
6. 候选规则会产生可定位的逐字段差异。
"""
from __future__ import annotations

import copy
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services.lineage import LineageService


class LineageApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例拿到全新的内存仓库，避免续做/重演结果互相污染。
        # 必须深拷贝：处理段、来源都是嵌套结构，浅拷贝会让上一个用例的写入
        # 反向污染全局种子，导致后续用例拿到被改过的样本。
        self.client = TestClient(app)
        from app.store import store
        from app.seed import SEED_ROWS
        store._tables = copy.deepcopy(SEED_ROWS)
        self.service = LineageService()

    def test_merged_sample_keeps_every_source(self) -> None:
        """SMPL-0001 被去重合并，但两个来源与两段采集证据都必须保留。"""
        detail = self.client.get("/api/lineage/1").json()
        self.assertEqual(detail["sample_code"], "SMPL-0001")
        self.assertTrue(detail["merged"])
        self.assertEqual(detail["source_count"], 2)
        self.assertEqual(len(detail["sources"]), 2)
        collect_segments = [seg for seg in detail["segments"] if seg["stage"] == "collect"]
        self.assertEqual(len(collect_segments), 2)
        refs = {source["source_ref"] for source in detail["sources"]}
        self.assertEqual(len(refs), 2)
        # 每段采集证据都有独立指纹，不允许被最后一次来源覆盖。
        fingerprints = {seg["fingerprint"] for seg in collect_segments}
        self.assertEqual(len(fingerprints), 2)

    def test_quarantined_sample_has_full_trace(self) -> None:
        """SMPL-0002 被隔离后，五个阶段的处理段与隔离落点仍然完整。"""
        detail = self.client.get("/api/lineage/2").json()
        self.assertTrue(detail["quarantined"])
        self.assertEqual(detail["status"], "已隔离")
        stages = [seg["stage"] for seg in detail["segments"]]
        self.assertEqual(stages, ["collect", "extract", "cleanse", "validate", "storage"])
        validate_seg = next(seg for seg in detail["segments"] if seg["stage"] == "validate")
        self.assertEqual(validate_seg["status"], "quarantined")
        self.assertTrue(validate_seg["reasons"])
        self.assertEqual(detail["final_value"]["storage_zone"], "quarantine")

    def test_resume_is_idempotent_and_preserves_prior_evidence(self) -> None:
        """SMPL-0003 续做补齐三阶段；同批次再触发只跳过、不重复追加。"""
        before = self.client.get("/api/lineage/3").json()
        self.assertEqual(before["resume_stage"], "cleanse")
        prior_fingerprints = [seg["fingerprint"] for seg in before["segments"]]
        prior_inputs = [seg["input_value"] for seg in before["segments"]]

        response = self.client.post(
            "/api/lineage/3/resume", json={"values": {"batch_id": "BATCH-RESUME-TEST"}}
        )
        self.assertTrue(response.json()["ok"], response.text)
        result = response.json()["entry"]
        self.assertEqual(len(result["appended"]), 3)
        self.assertEqual([item["stage"] for item in result["appended"]],
                         ["cleanse", "validate", "storage"])

        after = self.client.get("/api/lineage/3").json()
        self.assertIsNone(after["resume_stage"])
        self.assertEqual(after["status"], "已交付")
        self.assertEqual(len(after["segments"]), 5)
        # 断点前的指纹与输入快照原样保留。
        self.assertEqual([seg["fingerprint"] for seg in after["segments"][:2]], prior_fingerprints)
        self.assertEqual([seg["input_value"] for seg in after["segments"][:2]], prior_inputs)

        # 同批次再续做一次：指纹全部命中，零新增。
        again = self.client.post(
            "/api/lineage/3/resume", json={"values": {"batch_id": "BATCH-RESUME-TEST"}}
        )
        self.assertFalse(again.json()["ok"])
        self.assertIn("没有待续做的断点", again.json()["message"])

        # 换批次重复补齐（模拟重跑）也不能产生重复处理段。
        # 直接调 service 验证指纹去重分支：手工把断点重置后再续做。
        from app.store import store
        sample = store.find("lineage_sample", 3)
        sample["resume_stage"] = "cleanse"
        replayed, message = self.service.resume(3, "BATCH-RESUME-TEST")
        self.assertEqual(len(replayed["appended"]), 0)
        self.assertEqual(len(replayed["skipped"]), 3)
        self.assertEqual(len(store.find("lineage_sample", 3)["segments"]), 5)

    def test_legacy_sample_marks_evidence_gap_explicitly(self) -> None:
        """SMPL-0004 缺采集来源时，列表与详情都要明确显示证据缺口。"""
        listed = self.client.get("/api/lineage?evidence_gap=true").json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["sample_code"], "SMPL-0004")
        self.assertGreaterEqual(listed["items"][0]["gap_segment_count"], 1)

        detail = self.client.get("/api/lineage/4").json()
        self.assertTrue(detail["evidence_gap"])
        self.assertEqual(detail["source_count"], 0)
        gap_segments = [seg for seg in detail["segments"] if seg["evidence_gap"]]
        self.assertEqual(len(gap_segments), 1)
        self.assertEqual(gap_segments[0]["stage"], "collect")
        self.assertEqual(gap_segments[0]["status"], "gap")
        self.assertTrue(gap_segments[0]["reasons"])
        self.assertEqual(gap_segments[0]["fingerprint"], "")

    def test_replay_creates_experiment_without_touching_delivered_evidence(self) -> None:
        """候选规则重演只写实验表，正式样本的处理段、终值与状态完全不变。"""
        before = self.client.get("/api/lineage/1").json()
        response = self.client.post(
            "/api/lineage/1/replay",
            json={"values": {"candidate_rule_id": "STOR-CAND-01", "note": "实验分区演练"}},
        )
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        experiment = payload["entry"]
        self.assertEqual(experiment["branch"], "experiment")
        self.assertTrue(experiment["immutable"])

        after = self.client.get("/api/lineage/1").json()
        self.assertEqual(after["segments"], before["segments"])
        self.assertEqual(after["final_value"], before["final_value"])
        self.assertEqual(after["status"], before["status"])

        # 实验里存储段被候选规则替换，落在实验分区；且与正式输出逐字段可对比。
        storage_seg = next(seg for seg in experiment["segments"] if seg["stage"] == "storage")
        self.assertTrue(storage_seg["is_candidate"])
        self.assertIn("warehouse-experiments", storage_seg["output_value"]["storage_ref"])
        self.assertIn("storage_ref", {diff["field"] for diff in storage_seg["diffs"]})
        self.assertTrue(experiment["summary"]["final_diverged"])
        self.assertTrue(experiment["summary"]["delivered_final_untouched"])

        # 实验可以通过列表与详情接口查到。
        experiments = self.client.get("/api/lineage/experiments?sample_id=1").json()["items"]
        self.assertEqual(len(experiments), 1)
        fetched = self.client.get(f"/api/lineage/experiments/{experiment['id']}").json()
        self.assertEqual(fetched["id"], experiment["id"])
        self.assertEqual(len(fetched["segments"]), 5)

    def test_replay_candidate_validation_can_change_outcome(self) -> None:
        """VALI-CAND-01 允许空价格：SMPL-0002 在实验里从隔离变为人工复核放行。"""
        response = self.client.post(
            "/api/lineage/2/replay", json={"values": {"candidate_rule_id": "VALI-CAND-01"}}
        )
        experiment = response.json()["entry"]
        validate_seg = next(seg for seg in experiment["segments"] if seg["stage"] == "validate")
        self.assertTrue(validate_seg["is_candidate"])
        self.assertNotEqual(validate_seg["status"], "quarantined")
        self.assertTrue(validate_seg["output_value"].get("manual_review"))
        # 首次分叉点正是校验阶段。
        self.assertEqual(experiment["summary"]["first_divergence_stage"], "validate")
        self.assertTrue(experiment["summary"]["delivered_quarantined"])
        self.assertFalse(experiment["summary"]["experiment_quarantined"])
        # 正式样本依旧是隔离状态。
        self.assertTrue(self.client.get("/api/lineage/2").json()["quarantined"])

    def test_replay_strict_rule_quarantines_normal_sample(self) -> None:
        """VALI-CAND-02 收紧区间后，159 元的正常样本在实验里被隔离。"""
        response = self.client.post(
            "/api/lineage/5/replay", json={"values": {"candidate_rule_id": "VALI-CAND-02"}}
        )
        experiment = response.json()["entry"]
        self.assertTrue(experiment["summary"]["experiment_quarantined"])
        validate_seg = next(seg for seg in experiment["segments"] if seg["stage"] == "validate")
        self.assertEqual(validate_seg["status"], "quarantined")
        self.assertFalse(experiment["segments"][-1]["output_value"]["validation_passed"])

    def test_replay_rejects_non_candidate_and_unknown_rule(self) -> None:
        """正式在效规则和不存在的规则都不能作为重演候选。"""
        ok_rule = self.client.post(
            "/api/lineage/1/replay", json={"values": {"candidate_rule_id": "VALI-0001"}}
        )
        self.assertFalse(ok_rule.json()["ok"])
        missing = self.client.post(
            "/api/lineage/1/replay", json={"values": {"candidate_rule_id": "NOPE"}}
        )
        self.assertFalse(missing.json()["ok"])
        empty = self.client.post("/api/lineage/1/replay", json={"values": {}})
        self.assertFalse(empty.json()["ok"])

    def test_replay_carries_evidence_gap_flag(self) -> None:
        """缺口样本重演时必须把证据缺口带入实验，并从清洗阶段起步。"""
        response = self.client.post(
            "/api/lineage/4/replay", json={"values": {"candidate_rule_id": "CLEA-CAND-01"}}
        )
        experiment = response.json()["entry"]
        self.assertTrue(experiment["carried_evidence_gap"])
        self.assertEqual(experiment["segments"][0]["stage"], "cleanse")
        self.assertEqual(len(experiment["segments"]), 3)

    def test_gap_sample_cannot_replay_missing_stage(self) -> None:
        """缺口样本没有采集/映射证据，重演这两个阶段必须被明确拒绝。"""
        response = self.client.post(
            "/api/lineage/4/replay", json={"values": {"candidate_rule_id": "EXTR-CAND-01"}}
        )
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("无法重演", payload["message"])

    def test_resume_appends_continue_to_storage_with_correct_values(self) -> None:
        """续做补齐的值由同一套引擎算出：全角标题被规范化、价格通过校验并落盘。"""
        self.client.post(
            "/api/lineage/3/resume", json={"values": {"batch_id": "BATCH-RESUME-TEST"}}
        )
        detail = self.client.get("/api/lineage/3").json()
        cleanse_output = next(
            seg["output_value"] for seg in detail["segments"] if seg["stage"] == "cleanse"
        )
        self.assertEqual(cleanse_output["title"], "4Ｋ高刷显示器 27寸")
        self.assertEqual(cleanse_output["price"], 1899.0)
        storage_output = detail["segments"][-1]["output_value"]
        self.assertEqual(storage_output["storage_zone"], "published")
        self.assertTrue(storage_output["storage_ref"].endswith("SKU-3105.parquet"))

    def test_stats_and_filters(self) -> None:
        """统计口径与过滤参数能对上种子数据。"""
        stats = self.client.get("/api/lineage/stats").json()
        self.assertEqual(stats["sample_total"], 5)
        self.assertEqual(stats["quarantined"], 1)
        self.assertEqual(stats["resume_pending"], 1)
        self.assertEqual(stats["evidence_gap"], 1)
        self.assertEqual(stats["merged"], 1)

        merged = self.client.get("/api/lineage?merged_only=true").json()
        self.assertEqual(merged["total"], 1)
        by_status = self.client.get("/api/lineage?status=待续做").json()
        self.assertEqual(by_status["items"][0]["sample_code"], "SMPL-0003")
        rules = self.client.get("/api/lineage/candidate-rules").json()["items"]
        self.assertEqual(len(rules), 5)


if __name__ == "__main__":
    unittest.main()
