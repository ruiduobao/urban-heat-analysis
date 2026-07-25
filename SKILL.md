---
description: 'Calculate Urban Heat Island (UHI) intensity from MODIS LST GeoTIFF data.

  Classify heat island levels, perform temporal analysis, and output UHI maps

  with statistics.

  '
name: urban-heat-analysis
---

# urban-heat-analysis

Calculate Urban Heat Island (UHI) intensity from MODIS Land Surface Temperature (LST) GeoTIFF data. Supports UHI classification, temporal analysis, and map output.

## Features

- **UHI Intensity**: T_urban - T_rural_reference
- **Auto Rural Reference**: Uses coolest N% of pixels when no mask provided
- **Custom Rural Mask**: Accepts user-defined rural reference mask
- **Heat Island Classification**: Strong / Moderate / Weak / None
- **Temporal Analysis**: Seasonal UHI patterns from multiple LST images
- **GeoTIFF Output**: UHI intensity and classification maps
- **Statistics**: Mean, max, min, classification percentages

## Usage

```bash
# Compute UHI from single LST image
python scripts\urban-heat-analysis.py analyze --lst MOD11A1.tif --output uhi.tif

# With rural reference mask
python scripts\urban-heat-analysis.py analyze --lst lst.tif --rural-mask rural.tif --output uhi.tif

# Classify UHI intensity map
python scripts\urban-heat-analysis.py classify --uhi-tif uhi.tif --output classified.tif

# Temporal analysis across multiple images
python scripts\urban-heat-analysis.py temporal --lst-dir ./lst_data/ --output seasonal.json
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--lst` | LST GeoTIFF file path | Required |
| `--rural-mask` | Rural reference mask (1=rural) | None |
| `--rural-fraction` | Fraction of coolest pixels as rural ref | 0.1 |
| `--uhi-tif` | UHI intensity GeoTIFF (classify mode) | Required |
| `--lst-dir` | Directory of LST files (temporal mode) | Required |
| `--output` | Output file path | Auto-generated |

## Installation

```bash
pip install requests>=2.28.0 tqdm numpy scipy rasterio
# Or: pip install -r scripts/requirements.txt
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `rasterio` | GeoTIFF I/O and CRS handling |
| `numpy` | Array computation and statistics |
| `requests` | Data download (if applicable) |
| `tqdm` | Progress bars |

## Data Source

- **MODIS LST** (MOD11A1/MYD11A1) — NASA EOSDIS, Public Domain
- Scale factor: value × 0.02 = Kelvin
- Supports both Terra (MOD) and Aqua (MYD) products

## Data Acquisition

Obtain MODIS LST data from:
- **NASA Earthdata Search** (https://search.earthdata.nasa.gov/) — search for MOD11A1 or MYD11A1
- **NASA LAADS DAAC** (https://ladsweb.modaps.eosdis.nasa.gov/)
- Requires free Earthdata login (https://urs.earthdata.nasa.gov/)

## Nodata Handling

Nodata pixels (QC-flagged or fill values) are automatically excluded from UHI computation. The output GeoTIFF uses `nodata=-9999`. When using auto rural reference, nodata pixels are not considered in the coolest-N% calculation.

## CRS Requirements

All input rasters should be in the **same CRS**. If combining Terra and Aqua images, ensure they share the same projection and spatial extent. Reproject with `gdalwarp` if needed:

```bash
gdalwarp -t_srs EPSG:4326 input.tif reprojected.tif
```

## Cloud Contamination Handling

Use the QC band (`QC_Day` or `QC_Night`) to filter cloud-contaminated pixels. Pixels with QC flags indicating cloud cover should be masked out before UHI analysis:

```bash
python scripts\urban-heat-analysis.py analyze --lst MOD11A1.tif --qc-band qc.tif --output uhi.tif
```

If QC band is not available, consider using only clear-sky quality flags (QC == 0).

## Temporal Analysis Date Logic

For temporal analysis, dates are extracted from filenames using the MODIS naming convention (e.g., `MOD11A1.A2023001.h27v05.061.2023002010234.hdf`). Alternatively, use `--date-format` to specify a custom pattern:

```bash
python scripts\urban-heat-analysis.py temporal --lst-dir ./lst_data/ --date-format "%Y%m%d" --output seasonal.json
```

## Output GeoTIFF Structure

| Property | Value |
|----------|-------|
| Data type | `float32` |
| Bands | 1 (UHI intensity in °C) |
| NoData | -9999 |
| CRS | Same as input |

## Custom UHI Thresholds

Default classification uses fixed thresholds. To customize:

```bash
python scripts\urban-heat-analysis.py classify --uhi-tif uhi.tif --thresholds "1.0,2.5,4.0" --output classified.tif
```

The 3 values define boundaries between: none / weak / moderate / strong UHI.

## CSV Export for Statistics

Export classification statistics to CSV:

```bash
python scripts\urban-heat-analysis.py analyze --lst lst.tif --output uhi.tif --csv-stats stats.csv
```

CSV columns: `class, pixel_count, percentage, mean_intensity`.

## Multi-Sensor Combination

Combine Terra (MOD) and Aqua (MYD) for same-day average:

```bash
python scripts\urban-heat-analysis.py combine --terra MOD11A1.tif --aqua MYD11A1.tif --output lst_avg.tif
```

Then run UHI analysis on the averaged LST.

## Validation / Quality Assessment

- Compare UHI results with ground-based air temperature stations
- Check for anomalous values (|UHI| > 10°C may indicate cloud residual or data error)
- Report rural reference temperature sanity (should be within regional climate norms)

## Citation

```bibtex
@article{imhoff2010remote,
  title={Remote sensing of the urban heat island effect across biomes in the continental USA},
  author={Imhoff, Marc L and Zhang, Ping and Wolfe, Robert E and Bounoua, Lahouari},
  journal={Remote Sensing of Environment},
  volume={114},
  number={3},
  pages={504--513},
  year={2010},
  doi={10.1016/j.rse.2009.10.008}
}
```

## Visualization Guidance

```python
import rasterio
import matplotlib.pyplot as plt
import numpy as np

with rasterio.open("uhi.tif") as src:
    uhi = src.read(1)
    nodata = src.nodata

uhi_plot = np.where(uhi == nodata, np.nan, uhi)

fig, ax = plt.subplots(figsize=(10, 8))
im = ax.imshow(uhi_plot, cmap="RdYlBu_r", vmin=-2, vmax=6)
cbar = plt.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label("UHI Intensity (°C)")
ax.set_title("Urban Heat Island Intensity")
ax.axis("off")
plt.tight_layout()
plt.savefig("uhi_map.png", dpi=200)
```

## UHI Classification

| UHI Intensity (°C) | Classification |
|---------------------|----------------|
| > 4.0 | Strong UHI |
| 2.0 to 4.0 | Moderate UHI |
| 0.0 to 2.0 | Weak UHI |
| < 0.0 | None/Cool |

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `ConnectionError` | Network issue | Check internet, retry |
| `HTTP 429` | Rate limit | Wait 60s, retry |
| `ValueError` | Invalid input | Check parameter format |
| Empty output | No data | Try different parameters |
| `ModuleNotFoundError` | Missing dep | Run pip install |

---

## Advanced Usage

### Batch Multi-Date Analysis
```bash
for lst_file in data/MOD11A1*.tif; do
  python scripts\urban-heat-analysis.py analyze     --input "$lst_file" --rural-fraction 0.1     --output "uhi_$(basename $lst_file)"
done
```

### CI/CD Integration (GitHub Actions)
```yaml
# .github/workflows/uhi-monitor.yml
name: UHI Monthly Analysis
on:
  schedule:
    - cron: '0 0 5 * *'  # Monthly
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install numpy rasterio
      - run: |
          python scripts\urban-heat-analysis.py analyze \
            --input data/latest_lst.tif \
            --rural-fraction 0.1 \
            --output data/uhi_latest.tif
```

### PostGIS Raster Import
```bash
raster2pgsql -s 4326 -I -C uhi_latest.tif public.uhi_intensity | psql -d gis_db
```

### Performance Tips
- `--rural-fraction 0.1` uses coolest 10% as rural reference; adjust for your region
- Use `--thresholds 1.5 3.0` for arid regions (default 2.0/4.0 is for temperate)
- Combine Terra + Aqua: run analysis separately, then average results

---

## 中文说明

基于 MODIS 地表温度（LST）GeoTIFF 数据计算城市热岛（UHI）强度，支持热岛分级、时序分析和专题图输出。

## 安装

```bash
pip install requests>=2.28.0 tqdm numpy scipy rasterio
# 或: pip install -r scripts/requirements.txt
```

## 依赖

| 包 | 用途 |
|-----|------|
| `rasterio` | GeoTIFF 读写和 CRS 处理 |
| `numpy` | 数组计算和统计 |
| `requests` | 数据下载（如适用） |
| `tqdm` | 进度条 |

## 数据获取

从以下渠道获取 MODIS LST 数据：
- **NASA Earthdata Search** (https://search.earthdata.nasa.gov/) — 搜索 MOD11A1 或 MYD11A1
- **NASA LAADS DAAC** (https://ladsweb.modaps.eosdis.nasa.gov/)
- 需要免费 Earthdata 账号 (https://urs.earthdata.nasa.gov/)

## NoData 处理

NoData 像元（QC 标记或填充值）自动从 UHI 计算中排除。输出 GeoTIFF 使用 `nodata=-9999`。使用自动乡村参考时，NoData 像元不参与最冷 N% 计算。

## CRS 要求

所有输入栅格应使用**相同 CRS**。如合并 Terra 和 Aqua 影像，确保它们共享相同的投影和空间范围。如需重投影：

```bash
gdalwarp -t_srs EPSG:4326 input.tif reprojected.tif
```

## 云污染处理

使用 QC 波段（`QC_Day` 或 `QC_Night`）过滤云污染像元。QC 标记为云覆盖的像元应在 UHI 分析前掩膜掉：

```bash
python scripts\urban-heat-analysis.py analyze --lst MOD11A1.tif --qc-band qc.tif --output uhi.tif
```

## 时序分析日期逻辑

时序分析中，日期从文件名按 MODIS 命名约定提取。也可使用 `--date-format` 指定自定义格式：

```bash
python scripts\urban-heat-analysis.py temporal --lst-dir ./lst_data/ --date-format "%Y%m%d" --output seasonal.json
```

## 输出 GeoTIFF 结构

| 属性 | 值 |
|------|-----|
| 数据类型 | `float32` |
| 波段数 | 1（UHI 强度，°C） |
| NoData | -9999 |
| CRS | 与输入相同 |

## 自定义 UHI 阈值

```bash
python scripts\urban-heat-analysis.py classify --uhi-tif uhi.tif --thresholds "1.0,2.5,4.0" --output classified.tif
```

3 个值定义无/弱/中/强热岛的分界。

## CSV 统计导出

```bash
python scripts\urban-heat-analysis.py analyze --lst lst.tif --output uhi.tif --csv-stats stats.csv
```

CSV 列：`class, pixel_count, percentage, mean_intensity`。

## 多传感器组合

组合 Terra (MOD) 和 Aqua (MYD) 计算同日平均：

```bash
python scripts\urban-heat-analysis.py combine --terra MOD11A1.tif --aqua MYD11A1.tif --output lst_avg.tif
```

## 验证/质量评估

- 将 UHI 结果与地面气温站对比
- 检查异常值（|UHI| > 10°C 可能为云残留或数据错误）
- 报告乡村参考温度合理性（应在区域气候正常范围内）

## 引用格式

```bibtex
@article{imhoff2010remote,
  title={Remote sensing of the urban heat island effect across biomes in the continental USA},
  author={Imhoff, Marc L and Zhang, Ping and Wolfe, Robert E and Bounoua, Lahouari},
  journal={Remote Sensing of Environment},
  volume={114},
  number={3},
  pages={504--513},
  year={2010},
  doi={10.1016/j.rse.2009.10.008}
}
```

## 可视化指南

```python
import rasterio
import matplotlib.pyplot as plt
import numpy as np

with rasterio.open("uhi.tif") as src:
    uhi = src.read(1)
    nodata = src.nodata

uhi_plot = np.where(uhi == nodata, np.nan, uhi)

fig, ax = plt.subplots(figsize=(10, 8))
im = ax.imshow(uhi_plot, cmap="RdYlBu_r", vmin=-2, vmax=6)
cbar = plt.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label("UHI 强度 (°C)")
ax.set_title("城市热岛强度")
ax.axis("off")
plt.tight_layout()
plt.savefig("uhi_map.png", dpi=200)
```

## 故障排除

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ConnectionError` | 网络问题 | 检查网络，重试 |
| `HTTP 429` | 速率限制 | 等待 60 秒后重试 |
| `ValueError` | 无效输入 | 检查参数格式 |
| 空输出 | 无数据 | 尝试不同参数 |
| `ModuleNotFoundError` | 缺少依赖 | 运行 pip install |

基于 MODIS 地表温度（LST）GeoTIFF 数据计算城市热岛（UHI）强度，支持热岛分级、时序分析和专题图输出。

## 功能特性

- **UHI 强度计算**：T_城市 - T_乡村参考
- **自动乡村参考**：无掩膜时使用最冷 N% 像元
- **自定义乡村掩膜**：支持用户定义乡村参考区
- **热岛分级**：强/中/弱/无 四级分类
- **时序分析**：多期 LST 影像的季节性热岛变化
- **GeoTIFF 输出**：热岛强度和分级专题图
- **统计信息**：均值、最大最小值、分级占比

## 使用方法

```bash
# 单期 LST 计算 UHI
python scripts\urban-heat-analysis.py analyze --lst MOD11A1.tif --output uhi.tif

# 使用乡村参考掩膜
python scripts\urban-heat-analysis.py analyze --lst lst.tif --rural-mask rural.tif --output uhi.tif

# 热岛分级
python scripts\urban-heat-analysis.py classify --uhi-tif uhi.tif --output classified.tif

# 时序分析
python scripts\urban-heat-analysis.py temporal --lst-dir ./lst_data/ --output seasonal.json
```

## 数据来源

- **MODIS LST** (MOD11A1/MYD11A1) — NASA EOSDIS，公共领域
- 缩放系数：值 × 0.02 = 开尔文
- 支持 Terra (MOD) 和 Aqua (MYD) 产品

## 热岛分级标准

| UHI 强度 (°C) | 等级 |
|---------------|------|
| > 4.0 | 强热岛 |
| 2.0 至 4.0 | 中等热岛 |
| 0.0 至 2.0 | 弱热岛 |
| < 0.0 | 无热岛/冷岛 |
