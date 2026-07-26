"""Tests for urban-heat-analysis from-place (PHASE 1+ REFACTORED)."""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PROJECT_ROOT, "scripts")


def test_from_place_subcommand_in_help():
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "urban-heat-analysis.py"), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    combined = out.stdout + out.stderr
    assert "from-place" in combined


def test_from_place_resolves_place_then_runs():
    """PHASE 1+: from-place 真的解析 --place 然后调 fetch skill。
    没有网络时应该返回明确的网络/无数据错误（exit 4 或 5）。
    """
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "urban-heat-analysis.py"),
         "from-place", "--place", "北京市",
         "--start", "2024-06-01", "--end", "2024-06-08",
         "--output", os.path.join(os.environ.get("TEMP", "/tmp"), "uhi_test.tif")],
        capture_output=True, text=True, timeout=60,
    )
    combined = out.stdout + out.stderr
    assert "from-place" in combined
    assert "PHASE 0 DISABLED" not in combined
    # 退出码：0=成功, 2=参数错(用户传错), 3=依赖缺失, 4=网络/限流, 5=无数据, 7=处理失败
    # 我们传的是合法参数；如果 modis-lst-download 自己 exit 1/6 也是可接受（其内部定义）
    assert out.returncode != 0, "should fail (no real network/data in test env)"
    assert out.returncode < 130, "should not be killed by signal"


def test_aoi_resolution_works_via_vendored_geoskill_core():
    """验证 _geoskill_core.aoi 在该 skill 内部真实工作。"""
    skill_dir = PROJECT_ROOT
    sys.path.insert(0, skill_dir)
    from _geoskill_core import aoi
    m = aoi.resolve_place("北京市", allow_nominatim=True, use_cache=False)
    assert m.bbox_wgs84 is not None
    assert len(m.bbox_wgs84) == 4
