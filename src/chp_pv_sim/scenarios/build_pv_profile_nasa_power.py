from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

from chp_pv_sim.paths import ROOT, ensure_dirs


@dataclass
class PVMeta:
    scenario: str
    lat: float
    lon: float
    utc_offset_hours: float
    tilt_deg: float
    azimuth_deg: float
    albedo: float
    pv_dc_mw: float
    pv_ac_mw: float
    gamma_pdc_per_c: float
    inv_eff: float
    nasa_params: list[str]
    nasa_time_standard: str
    nasa_url: str


NASA_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def _dt_index_from_scenario_heat(scenario: str) -> pd.DatetimeIndex:
    scen_dir = ROOT / "data" / "scenarios" / scenario
    heat_path = scen_dir / "heat.parquet"
    if not heat_path.exists():
        raise FileNotFoundError(f"Missing scenario heat file: {heat_path}")

    df = pd.read_parquet(heat_path)
    df["datetime_local"] = pd.to_datetime(df["datetime_local"], errors="raise")
    idx = pd.DatetimeIndex(df["datetime_local"]).sort_values()

    # sanity: hourly
    if len(idx) < 2:
        raise ValueError("Scenario has too few hours.")
    step = (idx[1] - idx[0])
    if step != pd.Timedelta(hours=1):
        raise ValueError(f"Scenario index step is not hourly: step={step}")

    return idx


def _parse_hourly_param_series(d: Dict[str, Any], param: str) -> pd.Series:
    """
    NASA POWER hourly JSON typically: properties.parameter.PARAM is a dict:
      {"YYYYMMDDHH": value, ...}
    """
    if not isinstance(d, dict):
        raise TypeError("Expected dict for parameter mapping.")

    items = {}
    for k, v in d.items():
        if isinstance(k, str) and len(k) == 10 and k.isdigit():
            items[k] = v

    if not items:
        raise ValueError(f"No hourly keys parsed for param={param}. Got keys example: {list(d.keys())[:5]}")

    s = pd.Series(items, name=param, dtype="float64")
    s.index = pd.to_datetime(s.index, format="%Y%m%d%H", errors="raise")
    s = s.sort_index()

    # NASA POWER missing value convention is often -999
    s = s.replace([-999, -999.0], np.nan)
    return s


def _download_nasa_power_hourly(
    lat: float,
    lon: float,
    start_utc_date: str,
    end_utc_date: str,
    params: list[str],
    time_standard: str = "UTC",
    fmt: str = "JSON",
) -> tuple[dict[str, Any], str]:
    """
    Returns (json_payload, url_used).
    """
    import requests

    param_str = ",".join(params)

    # Build URL with explicit time-standard to avoid default LST ambiguity
    url = (
        f"{NASA_BASE}"
        f"?parameters={param_str}"
        f"&community=SB"
        f"&longitude={lon}"
        f"&latitude={lat}"
        f"&start={start_utc_date}"
        f"&end={end_utc_date}"
        f"&format={fmt}"
        f"&time-standard={time_standard}"
    )

    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"NASA POWER request failed: HTTP {r.status_code}\nURL: {url}\nBody(head): {r.text[:300]}")

    payload = r.json()
    return payload, url


def _safe_import_pvlib():
    try:
        import pvlib  # type: ignore
        return pvlib
    except Exception as e:
        raise RuntimeError(
            "pvlib import failed. You reported pvlib=0.5.2 installed; "
            "please confirm in this env: python -c \"import pvlib; print(pvlib.__version__)\""
        ) from e


def _compute_pv_ac_mw(
    times_local_tz: pd.DatetimeIndex,
    lat: float,
    lon: float,
    ghi: pd.Series,
    dni: pd.Series,
    dhi: pd.Series,
    temp_air: pd.Series,
    wind: pd.Series,
    tilt: float,
    azimuth: float,
    albedo: float,
    pv_dc_mw: float,
    pv_ac_mw: float,
    gamma_pdc: float,
    inv_eff: float,
) -> pd.DataFrame:
    pvlib = _safe_import_pvlib()

    # solar position
    solpos = pvlib.solarposition.get_solarposition(times_local_tz, lat, lon)

    # handle column names across pvlib versions
    if "apparent_zenith" in solpos.columns:
        zenith = solpos["apparent_zenith"]
    elif "zenith" in solpos.columns:
        zenith = solpos["zenith"]
    else:
        raise KeyError(f"Unexpected solpos columns: {list(solpos.columns)}")

    if "azimuth" not in solpos.columns:
        raise KeyError(f"Unexpected solpos columns: {list(solpos.columns)}")
    sol_az = solpos["azimuth"]

    # plane-of-array irradiance
        # plane-of-array irradiance (pvlib API compat: old versions use total_irrad)
    irr = pvlib.irradiance
    if hasattr(irr, "get_total_irradiance"):
        # pvlib >= ~0.6
        poa = irr.get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=zenith,
            solar_azimuth=sol_az,
            dni=dni,
            ghi=ghi,
            dhi=dhi,
            albedo=albedo,
        )
    elif hasattr(irr, "total_irrad"):
        # pvlib <= ~0.5 (your case: 0.5.2)
        # signature is positional: (surface_tilt, surface_azimuth, apparent_zenith, azimuth, dni, ghi, dhi, ...)
        poa = irr.total_irrad(
            tilt,
            azimuth,
            zenith,
            sol_az,
            dni,
            ghi,
            dhi,
            albedo=albedo,
        )
    else:
        raise AttributeError(
            "pvlib.irradiance has neither get_total_irradiance nor total_irrad. "
            "Please upgrade pvlib."
        )

    # normalize return type (older pvlib may return OrderedDict)
    if not isinstance(poa, pd.DataFrame):
        poa = pd.DataFrame(poa, index=times_local_tz)

    if "poa_global" not in poa.columns:
        raise KeyError(f"Unexpected POA columns: {list(poa.columns)}")
    poa_global = poa["poa_global"].clip(lower=0.0)

    # cell temperature (try sapm_cell; fallback to simple NOCT model)
    try:
        t_cell = pvlib.temperature.sapm_cell(poa_global, temp_air, wind)
    except Exception:
        # Fallback: Tcell = Ta + (POA/800)*(NOCT-20)
        NOCT = 45.0
        t_cell = temp_air + (poa_global / 800.0) * (NOCT - 20.0)

    # PVWatts-like DC (W)
    pdc0_w = pv_dc_mw * 1e6
    pdc_w = (poa_global / 1000.0) * pdc0_w * (1.0 + gamma_pdc * (t_cell - 25.0))
    pdc_w = np.maximum(pdc_w, 0.0)

    # Simple inverter model (W): cap at pac0 and apply efficiency
    pac0_w = pv_ac_mw * 1e6
    pac_w = np.minimum(pdc_w * inv_eff, pac0_w)
    pac_w = np.maximum(pac_w, 0.0)

    out = pd.DataFrame(
        {
            "ghi_wm2": ghi.astype(float),
            "dni_wm2": dni.astype(float),
            "dhi_wm2": dhi.astype(float),
            "temp_air_c": temp_air.astype(float),
            "wind_mps": wind.astype(float),
            "poa_global_wm2": poa_global.astype(float),
            "t_cell_c": pd.Series(t_cell, index=times_local_tz).astype(float),
            "pv_dc_mw": (pdc_w / 1e6).astype(float),
            "pv_ac_mw": (pac_w / 1e6).astype(float),
        },
        index=times_local_tz,
    )

    return out


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--lat", type=float, default=55.6761, help="latitude (default: Copenhagen)")
    ap.add_argument("--lon", type=float, default=12.5683, help="longitude (default: Copenhagen)")
    ap.add_argument("--utc_offset_hours", type=float, default=1.0, help="treat scenario datetime_local as this fixed UTC offset (Dec in DK is +1)")
    ap.add_argument("--tilt", type=float, default=35.0)
    ap.add_argument("--azimuth", type=float, default=180.0, help="180=south-facing in Northern Hemisphere")
    ap.add_argument("--albedo", type=float, default=0.2)
    ap.add_argument("--pv_dc_mw", type=float, default=120.0, help="PV DC nameplate (MW)")
    ap.add_argument("--pv_ac_mw", type=float, default=100.0, help="PV AC inverter limit (MW)")
    ap.add_argument("--gamma_pdc", type=float, default=-0.003, help="PVWatts temperature coeff (per degC)")
    ap.add_argument("--inv_eff", type=float, default=0.96, help="constant inverter efficiency")
    ap.add_argument("--save_raw_json", action="store_true", help="also save raw NASA JSON for audit")
    args = ap.parse_args()

    scenario = args.scenario
    lat = float(args.lat)
    lon = float(args.lon)
    utc_offset_hours = float(args.utc_offset_hours)

    dt_local_naive = _dt_index_from_scenario_heat(scenario)

    # Create timezone-aware local index using fixed offset (avoids tzdata issues on Windows)
    tz_local = timezone(timedelta(hours=utc_offset_hours))
    dt_local = dt_local_naive.tz_localize(tz_local)
    dt_utc = dt_local.tz_convert(timezone.utc)

    # NASA POWER request is date-based; request a superset and then reindex precisely
    start_utc_date = dt_utc.min().strftime("%Y%m%d")
    end_utc_date = dt_utc.max().strftime("%Y%m%d")

    nasa_params = ["ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_SW_DNI", "ALLSKY_SFC_SW_DIFF", "T2M", "WS10M"]

    print("Downloading NASA POWER hourly data ...", flush=True)
    payload, url = _download_nasa_power_hourly(
        lat=lat,
        lon=lon,
        start_utc_date=start_utc_date,
        end_utc_date=end_utc_date,
        params=nasa_params,
        time_standard="UTC",
        fmt="JSON",
    )
    print("NASA URL:", url, flush=True)

    # Parse
    try:
        param_block = payload["properties"]["parameter"]
    except Exception as e:
        raise RuntimeError(f"Unexpected NASA POWER JSON structure. Keys: {list(payload.keys())[:10]}") from e

    s_ghi = _parse_hourly_param_series(param_block["ALLSKY_SFC_SW_DWN"], "ALLSKY_SFC_SW_DWN")
    s_dni = _parse_hourly_param_series(param_block["ALLSKY_SFC_SW_DNI"], "ALLSKY_SFC_SW_DNI")
    s_dhi = _parse_hourly_param_series(param_block["ALLSKY_SFC_SW_DIFF"], "ALLSKY_SFC_SW_DIFF")
    s_t2m = _parse_hourly_param_series(param_block["T2M"], "T2M")
    s_ws10 = _parse_hourly_param_series(param_block["WS10M"], "WS10M")

    met = pd.concat([s_ghi, s_dni, s_dhi, s_t2m, s_ws10], axis=1)

    # met index is UTC naive; localize to UTC then convert to local tz
    met.index = met.index.tz_localize(timezone.utc).tz_convert(tz_local)

    # filter to exact scenario hours and reindex
    met = met.reindex(dt_local)

    if met.isna().any().any():
        na = met.isna().sum().to_dict()
        raise ValueError(f"NASA meteo has missing values after reindex to scenario hours: {na}")

    # rename to physics-friendly names (units are W/m^2, degC, m/s)
    ghi = met["ALLSKY_SFC_SW_DWN"].astype(float).clip(lower=0.0)
    dni = met["ALLSKY_SFC_SW_DNI"].astype(float).clip(lower=0.0)
    dhi = met["ALLSKY_SFC_SW_DIFF"].astype(float).clip(lower=0.0)
    temp_air = met["T2M"].astype(float)
    wind = met["WS10M"].astype(float).clip(lower=0.0)

    print("Computing PV output with pvlib ...", flush=True)
    pv = _compute_pv_ac_mw(
        times_local_tz=dt_local,
        lat=lat,
        lon=lon,
        ghi=ghi,
        dni=dni,
        dhi=dhi,
        temp_air=temp_air,
        wind=wind,
        tilt=float(args.tilt),
        azimuth=float(args.azimuth),
        albedo=float(args.albedo),
        pv_dc_mw=float(args.pv_dc_mw),
        pv_ac_mw=float(args.pv_ac_mw),
        gamma_pdc=float(args.gamma_pdc),
        inv_eff=float(args.inv_eff),
    )

    # Write scenario outputs (use naive datetime_local to match other scenario files)
    scen_dir = ROOT / "data" / "scenarios" / scenario
    out_pv = scen_dir / "pv.parquet"
    out_manifest = scen_dir / "pv_manifest.json"

    pv_out = pv.copy()
    pv_out = pv_out.reset_index().rename(columns={"index": "datetime_local"})
    pv_out["datetime_local"] = pv_out["datetime_local"].dt.tz_localize(None)

    pv_out.to_parquet(out_pv, index=False, engine="pyarrow", compression="zstd")

    meta = PVMeta(
        scenario=scenario,
        lat=lat,
        lon=lon,
        utc_offset_hours=utc_offset_hours,
        tilt_deg=float(args.tilt),
        azimuth_deg=float(args.azimuth),
        albedo=float(args.albedo),
        pv_dc_mw=float(args.pv_dc_mw),
        pv_ac_mw=float(args.pv_ac_mw),
        gamma_pdc_per_c=float(args.gamma_pdc),
        inv_eff=float(args.inv_eff),
        nasa_params=nasa_params,
        nasa_time_standard="UTC",
        nasa_url=url,
    )

    manifest: dict[str, Any] = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "pv_profile": asdict(meta),
        "outputs": {"pv_parquet": str(out_pv).replace("\\", "/")},
        "stats": {
            "pv_ac_mw": {
                "min": float(pv["pv_ac_mw"].min()),
                "p50": float(pv["pv_ac_mw"].median()),
                "p99": float(pv["pv_ac_mw"].quantile(0.99)),
                "max": float(pv["pv_ac_mw"].max()),
                "energy_mwh": float(pv["pv_ac_mw"].sum()),  # dt=1h
            }
        },
    }
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.save_raw_json:
        raw_path = scen_dir / "nasa_power_raw.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print("Wrote raw NASA JSON:", raw_path)

    print("Wrote PV profile  :", out_pv)
    print("Wrote PV manifest :", out_manifest)
    print("\nPV AC stats (MW):")
    print(pv["pv_ac_mw"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]).to_string())


if __name__ == "__main__":
    main()