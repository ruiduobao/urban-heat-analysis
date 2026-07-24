# urban-heat-analysis

**Urban Heat Island (UHI) Intensity Calculator** — Analyze heat islands from MODIS LST data.

## Install

### ClawHub
```bash
clawhub install urban-heat-analysis
```

### Manual
```bash
git clone https://github.com/ruiduobao/urban-heat-analysis.git
cd urban-heat-analysis
pip install -r requirements.txt  # rasterio, numpy
```

### Claude Code / skills.sh
```bash
/clawhub install urban-heat-analysis
```

## Quick Start
```bash
python scripts/urban-heat-analysis.py analyze --lst MOD11A1.tif --output uhi.tif
python scripts/urban-heat-analysis.py classify --uhi-tif uhi.tif --output classified.tif
```

## Data Source
- MODIS LST (MOD11A1/MYD11A1) — NASA EOSDIS, Public Domain

## License
MIT-0

---

# 城市热岛分析工具

**城市热岛（UHI）强度计算器** — 基于 MODIS 地表温度数据的热岛分析。

## 安装

### 手动安装
```bash
git clone https://github.com/ruiduobao/urban-heat-analysis.git
cd urban-heat-analysis
pip install rasterio numpy
```

## 快速开始
```bash
python scripts/urban-heat-analysis.py analyze --lst MOD11A1.tif --output uhi.tif
python scripts/urban-heat-analysis.py classify --uhi-tif uhi.tif --output classified.tif
```

## 数据来源
- MODIS LST (MOD11A1/MYD11A1) — NASA EOSDIS，公共领域

## 许可证
MIT-0
