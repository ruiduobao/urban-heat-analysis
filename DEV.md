# urban-heat-analysis - Development Doc

## Purpose
Calculate Urban Heat Island (UHI) intensity from MODIS LST GeoTIFF data.

## Data Source
- MODIS LST (MOD11A1/MYD11A1) GeoTIFF files (local processing)
- Optional: NASA POWER air temperature for validation

## UHI Calculation
- UHI_intensity = T_urban - T_rural_reference
- Rural reference: buffer zone around urban area, or user-provided mask

## Heat Island Classification
| UHI Intensity (°C) | Classification |
|---------------------|----------------|
| > 4.0 | Strong UHI |
| 2.0 to 4.0 | Moderate UHI |
| 0.0 to 2.0 | Weak UHI |
| < 0.0 | None/Cool |

## CLI Design
```
urban-heat-analysis analyze --lst --rural-mask --output
urban-heat-analysis classify --uhi-tif --output
urban-heat-analysis temporal --lst-dir --rural-mask --output
```

## Dependencies
- rasterio>=1.3.0
- numpy>=1.21.0

## Implementation Notes
- Read LST GeoTIFF via rasterio
- Support Kelvin-to-Celsius conversion (MODIS LST is in Kelvin * 0.02)
- Rural reference: if no mask provided, use lowest 10% of pixels as rural
- Temporal analysis: group by season/month, compute mean UHI per period
- Output: UHI intensity GeoTIFF + classification map + statistics JSON
