#!/usr/bin/env python3
"""scan.py 金标测试：召回、商业门控、行业门控、白名单降噪、辟谣、my-rules 容错。

运行：python3 evals/test_scan.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scan  # noqa: E402


def run_scan(text: str, commercial: bool = False, industries: set[str] | None = None):
    return scan.scan(text, commercial, industries or set(), 20)


def rules_hit(result) -> set[str]:
    return {c["rule"] for c in result["candidates"]}


class ScanGolden(unittest.TestCase):
    def test_income_guarantee_recall(self):
        result = run_scan("学完保证你三十天回本，月入过万", commercial=True)
        self.assertIn("commercial-expression.R03", rules_hit(result))

    def test_diversion_recall(self):
        result = run_scan("加我微信进群，评论区扣1领资料", commercial=True)
        self.assertIn("commercial-expression.R05", rules_hit(result))

    def test_commercial_gate_blocks_noncommercial(self):
        result = run_scan("这家店全网第一好吃", commercial=False)
        self.assertNotIn("commercial-expression.R01", rules_hit(result))

    def test_commercial_gate_opens(self):
        result = run_scan("我们的产品全网第一", commercial=True)
        self.assertIn("commercial-expression.R01", rules_hit(result))

    def test_industry_gate(self):
        text = "这个疗法可以根治糖尿病"
        plain = run_scan(text)
        medical = run_scan(text, industries={"medical"})
        self.assertFalse({r for r in rules_hit(plain) if r.startswith("medical-health")})
        self.assertTrue({r for r in rules_hit(medical) if r.startswith("medical-health")})

    def test_myth_advisory_not_candidate(self):
        result = run_scan("这个方法帮我赚米不少")
        self.assertEqual(len(result["myth_advisories"]), 1)
        self.assertIn("赚米", result["myth_advisories"][0]["match"])

    def test_clean_text(self):
        result = run_scan("今天分享一个收纳小技巧，希望对你有帮助。")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["myth_advisories"], [])

    def test_my_rules_black_white_and_bad_regex(self):
        fake = (
            "## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 |\n|---|---|---|---|\n"
            "| 对赌承诺 | 同行被举报 | 全部 | 高 |\n| ((坏正则 | x | 全部 | 高 |\n\n"
            "## 白名单\n\n| 词 | 情境说明 |\n|---|---|\n| 唯一 | 我说的是'唯一的爱好' |\n"
        )
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(fake)
            tmp_path = Path(fh.name)
        try:
            with mock.patch.object(scan, "MY_RULES_PATH", tmp_path):
                result = run_scan("我签了对赌承诺，这是我唯一的爱好", commercial=True)
        finally:
            tmp_path.unlink()
        self.assertEqual(len(result["personal_hits"]), 1)
        self.assertEqual(result["personal_hits"][0]["match"], "对赌承诺")
        self.assertTrue(any("坏正则" in w for w in result["warnings"]))
        muted = [c for c in result["candidates"] if c["match"] == "唯一"]
        self.assertTrue(muted and muted[0]["muted_by_whitelist"])


    def test_trap_patterns_recall(self):
        # 伪合规陷阱词面：观众"自主"完成的站外动作同样构成引导
        result = run_scan(
            "喜欢的家人加我微信聊，或者应用商店搜一下就有，现在注册就送七天会员",
            commercial=True,
        )
        hits = {c["match"] for c in result["candidates"]}
        self.assertTrue({"加我微信", "应用商店搜", "注册就送"} <= hits, hits)

    def test_share_style_zero_candidates(self):
        # 只陈述使用经历、不给观众布置站外动作的种草式表达，不应产生词面候选
        result = run_scan(
            "这期字幕动画是我拿剪映调的，关键帧用顺手之后效率高了不少，纯经验分享。",
            commercial=True,
        )
        self.assertEqual(result["candidates"], [], result["candidates"])

    def test_blacklist_mode_column(self):
        import tempfile

        fake = (
            "## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n|---|---|---|---|---|\n"
            "| 保过 | 法务红线 | 全部 | 高 | 见词即报 |\n"
            "| 对赌承诺 | 同行被举报 | 全部 | 高 | 语境判 |\n"
            "| 老规则词 | 四列旧格式兼容 | 全部 | 中 |\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(fake)
            tmp_path = Path(fh.name)
        try:
            with mock.patch.object(scan, "MY_RULES_PATH", tmp_path):
                result = run_scan("这个班保过，还带对赌承诺，用了老规则词")
        finally:
            tmp_path.unlink()
        modes = {p["match"]: p["mode"] for p in result["personal_hits"]}
        self.assertEqual(modes["保过"], "direct")
        self.assertEqual(modes["对赌承诺"], "semantic")
        self.assertEqual(modes["老规则词"], "semantic")

    def test_blacklist_escaped_pipe_regex(self):
        import tempfile

        fake = (
            "## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n|---|---|---|---|---|\n"
            "| 七天见效\\|7天见效 | 零容忍 | 全部 | 高 | 见词即报 |\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(fake)
            tmp_path = Path(fh.name)
        try:
            with mock.patch.object(scan, "MY_RULES_PATH", tmp_path):
                result = run_scan("这个方法7天见效，那个七天见效")
        finally:
            tmp_path.unlink()
        matches = {p["match"] for p in result["personal_hits"]}
        self.assertEqual(matches, {"7天见效", "七天见效"})

    def test_wordlist_files(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "行业词.md").write_text(
                "# 我的行业词库\n对赌协议|法务提醒过\n虚拟盘\n", encoding="utf-8"
            )
            (Path(tmp) / "旧格式.txt").write_text("老词条\n", encoding="utf-8")
            # README 是说明文件，内容不得被当成词条
            (Path(tmp) / "README.md").write_text("这里放词库文件\n", encoding="utf-8")
            with mock.patch.object(scan, "WORDLISTS_DIR", Path(tmp)):
                result = run_scan("他们做的是虚拟盘，带对赌协议，还有老词条。这里放词库文件")
        matches = {p["match"] for p in result["personal_hits"]}
        self.assertEqual(matches, {"对赌协议", "虚拟盘", "老词条"})
        reasons = {p["reason"] for p in result["personal_hits"]}
        self.assertIn("法务提醒过", reasons)

    def test_shipped_example_wordlist_is_inert(self):
        # 随包发布状态下 data/wordlists 只有 README，不得产生任何词条
        self.assertEqual([e for e in scan.load_wordlists()], [])

    def test_user_data_never_tracked_by_git(self):
        # 数据安全铁律：data/ 下只允许 README 被 Git 跟踪。
        # 违反此测试 = 未来 git pull 可能覆盖用户沉淀，禁止发布。
        import subprocess

        root = Path(__file__).resolve().parents[1]
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=root
        )
        if top.returncode != 0 or Path(top.stdout.strip()) != root:
            self.skipTest("非独立发布仓库（开发副本嵌在外层仓库），跳过")
        proc = subprocess.run(
            ["git", "ls-files", "data"], capture_output=True, text=True, cwd=root
        )
        tracked = [l for l in proc.stdout.splitlines() if l.strip()]
        offenders = [t for t in tracked if not t.lower().endswith("readme.md")]
        self.assertEqual(offenders, [], f"data/ 下有非 README 文件被跟踪: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
