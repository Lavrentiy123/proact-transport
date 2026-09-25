"""
Feature Engineering module for Moscow Transport Hackathon 2026.
Extracts physically-grounded spatial, temporal, and telemetric features
strictly respecting the anti-leakage rule (event_time <= T).
"""

import numpy as np
import pandas as pd
import math
import re

def haversine_np(lon1, lat1, lon2, lat2):
    """Calculate the great circle distance between two points in meters."""
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.clip(np.sqrt(a), 0, 1))
    km = 6367 * c
    return km * 1000.0

def parse_point_geom(geom_series):
    """Extracts (lon, lat) from 'POINT (lon lat)' strings."""
    pattern = r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)"
    extracted = geom_series.str.extract(pattern).astype(float)
    return extracted[0], extracted[1]

def build_features(df_points, df_traffic, df_schedule):
    """
    Extracts features for each row in df_points.
    df_points columns: sample_id, tr_id, T, target_stop_id, target_time_begin, cur_dev_s
    """
    points = df_points.copy()
    points['T_dt'] = pd.to_datetime(points['T'])
    points['target_time_dt'] = pd.to_datetime(points['target_time_begin'])
    
    # 1. Basic time & horizon features
    points['horizon_s'] = (points['target_time_dt'] - points['T_dt']).dt.total_seconds()
    points['hour'] = points['T_dt'].dt.hour
    points['minute'] = points['T_dt'].dt.minute
    minutes_in_day = points['hour'] * 60 + points['minute']
    points['time_sin'] = np.sin(2 * np.pi * minutes_in_day / 1440.0)
    points['time_cos'] = np.cos(2 * np.pi * minutes_in_day / 1440.0)
    points['is_rush_morning'] = ((points['hour'] >= 7) & (points['hour'] <= 9)).astype(int)
    points['is_rush_evening'] = ((points['hour'] >= 17) & (points['hour'] <= 20)).astype(int)
    
    # 2. Schedule features & target stop coordinates
    sched = df_schedule.copy()
    sched['time_begin_dt'] = pd.to_datetime(sched['time_begin'])
    stop_lon, stop_lat = parse_point_geom(sched['geom'])
    sched['stop_lon'] = stop_lon
    sched['stop_lat'] = stop_lat
    
    # Lookup stop coordinates for target_stop_id
    stop_lookup = sched.drop_duplicates('tt_action_item_id').set_index('tt_action_item_id')
    
    points['target_lon'] = points['target_stop_id'].map(stop_lookup['stop_lon'])
    points['target_lat'] = points['target_stop_id'].map(stop_lookup['stop_lat'])
    
    # Pre-index traffic by tr_id and event_time
    traffic = df_traffic.copy()
    traffic['event_time_dt'] = pd.to_datetime(traffic['event_time'])
    traffic = traffic.sort_values(['tr_id', 'event_time_dt'])
    
    # Group traffic and schedule by tr_id
    traffic_by_tr = dict(tuple(traffic.groupby('tr_id')))
    sched_by_tr = dict(tuple(sched.groupby('tr_id')))
    
    features_list = []
    
    for idx, row in points.iterrows():
        tr_id = row['tr_id']
        t_moment = row['T_dt']
        target_t = row['target_time_dt']
        target_lon = row['target_lon']
        target_lat = row['target_lat']
        cur_dev = row['cur_dev_s']
        horizon_s = max(row['horizon_s'], 1.0)
        
        # Intermediate stops count between T and target_time
        num_intermediate_stops = 0
        if tr_id in sched_by_tr:
            s_df = sched_by_tr[tr_id]
            stops_between = s_df[(s_df['time_begin_dt'] > t_moment) & (s_df['time_begin_dt'] <= target_t)]
            num_intermediate_stops = len(stops_between)
        
        # Telemetry before T
        f_row = {
            'num_intermediate_stops': num_intermediate_stops,
            'has_telemetry': 0,
            'time_since_last_telemetry_s': 999.0,
            'last_speed': 0.0,
            'last_heading': 0.0,
            'mean_speed_1m': 0.0,
            'mean_speed_3m': 0.0,
            'mean_speed_5m': 0.0,
            'mean_speed_10m': 0.0,
            'max_speed_3m': 0.0,
            'min_speed_3m': 0.0,
            'std_speed_3m': 0.0,
            'stopped_ratio_3m': 1.0,
            'stopped_ratio_5m': 1.0,
            'dist_traveled_3m_m': 0.0,
            'dist_traveled_5m_m': 0.0,
            'dist_to_target_m': 0.0,
            'implied_speed_kmh': 0.0,
            'speed_diff_kmh': 0.0,
            'speed_ratio': 1.0,
        }
        
        if tr_id in traffic_by_tr:
            t_df = traffic_by_tr[tr_id]
            t_past = t_df[t_df['event_time_dt'] <= t_moment]
            
            if len(t_past) > 0:
                f_row['has_telemetry'] = 1
                last_pt = t_past.iloc[-1]
                dt_last = (t_moment - last_pt['event_time_dt']).total_seconds()
                f_row['time_since_last_telemetry_s'] = dt_last
                f_row['last_speed'] = float(last_pt['speed'])
                f_row['last_heading'] = float(last_pt['heading'])
                
                last_lat = float(last_pt['lat'])
                last_lon = float(last_pt['lon'])
                
                # Distance to target stop
                if not np.isnan(target_lat) and not np.isnan(target_lon):
                    d_target = haversine_np(last_lon, last_lat, target_lon, target_lat)
                    f_row['dist_to_target_m'] = d_target
                    implied_spd = (d_target / 1000.0) / (horizon_s / 3600.0)
                    f_row['implied_speed_kmh'] = implied_spd
                
                # Windows: 1m, 3m, 5m, 10m
                t_1m = t_past[t_past['event_time_dt'] >= t_moment - pd.Timedelta(minutes=1)]
                t_3m = t_past[t_past['event_time_dt'] >= t_moment - pd.Timedelta(minutes=3)]
                t_5m = t_past[t_past['event_time_dt'] >= t_moment - pd.Timedelta(minutes=5)]
                t_10m = t_past[t_past['event_time_dt'] >= t_moment - pd.Timedelta(minutes=10)]
                
                if len(t_1m) > 0:
                    f_row['mean_speed_1m'] = float(t_1m['speed'].mean())
                    
                if len(t_3m) > 0:
                    spd_3m = t_3m['speed']
                    f_row['mean_speed_3m'] = float(spd_3m.mean())
                    f_row['max_speed_3m'] = float(spd_3m.max())
                    f_row['min_speed_3m'] = float(spd_3m.min())
                    f_row['std_speed_3m'] = float(spd_3m.std()) if len(spd_3m) > 1 else 0.0
                    f_row['stopped_ratio_3m'] = float((spd_3m < 2.0).mean())
                    
                    # Distance traveled in 3m
                    if len(t_3m) > 1:
                        f_row['dist_traveled_3m_m'] = haversine_np(
                            t_3m['lon'].iloc[0], t_3m['lat'].iloc[0],
                            t_3m['lon'].iloc[-1], t_3m['lat'].iloc[-1]
                        )
                
                if len(t_5m) > 0:
                    spd_5m = t_5m['speed']
                    f_row['mean_speed_5m'] = float(spd_5m.mean())
                    f_row['stopped_ratio_5m'] = float((spd_5m < 2.0).mean())
                    if len(t_5m) > 1:
                        f_row['dist_traveled_5m_m'] = haversine_np(
                            t_5m['lon'].iloc[0], t_5m['lat'].iloc[0],
                            t_5m['lon'].iloc[-1], t_5m['lat'].iloc[-1]
                        )
                
                if len(t_10m) > 0:
                    f_row['mean_speed_10m'] = float(t_10m['speed'].mean())
                
                # Speed discrepancy
                f_row['speed_diff_kmh'] = f_row['implied_speed_kmh'] - f_row['mean_speed_3m']
                f_row['speed_ratio'] = f_row['implied_speed_kmh'] / (f_row['mean_speed_3m'] + 1.0)
                
        features_list.append(f_row)
        
    df_feat = pd.DataFrame(features_list, index=points.index)
    combined = pd.concat([points, df_feat], axis=1)
    return combined
