"""
Training and evaluation script for Moscow Transport Delay Predictor.
Uses CatBoostRegressor to predict delta = target_delay_s - cur_dev_s.
"""

import os
import sys
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from feature_engineering import build_features

def main():
    print("=== 1. Loading raw data ===")
    train_labels = pd.read_csv("data/labels/labels_train.csv")
    test_labels = pd.read_csv("data/labels/labels_test.csv")
    val_points = pd.read_csv("data/validate/points.csv")
    
    train_traffic = pd.read_csv("data/train/traffic.csv", low_memory=False)
    train_sched = pd.read_csv("data/train/schedule.csv", low_memory=False)
    
    test_traffic = pd.read_csv("data/test/traffic.csv", low_memory=False)
    test_sched = pd.read_csv("data/test/schedule.csv", low_memory=False)
    
    val_traffic = pd.read_csv("data/validate/traffic.csv", low_memory=False)
    val_sched = pd.read_csv("data/validate/schedule_plan.csv", low_memory=False)
    
    print(f"Train samples: {len(train_labels)}, Test samples: {len(test_labels)}, Val samples: {len(val_points)}")
    
    print("=== 2. Feature Extraction ===")
    print("Extracting train features...")
    df_train_feat = build_features(train_labels, train_traffic, train_sched)
    
    print("Extracting test features...")
    df_test_feat = build_features(test_labels, test_traffic, test_sched)
    
    print("Extracting validate features...")
    df_val_feat = build_features(val_points, val_traffic, val_sched)
    
    # Define features
    feature_cols = [
        'cur_dev_s',
        'horizon_s',
        'hour',
        'minute',
        'time_sin',
        'time_cos',
        'is_rush_morning',
        'is_rush_evening',
        'num_intermediate_stops',
        'has_telemetry',
        'time_since_last_telemetry_s',
        'last_speed',
        'last_heading',
        'mean_speed_1m',
        'mean_speed_3m',
        'mean_speed_5m',
        'mean_speed_10m',
        'max_speed_3m',
        'min_speed_3m',
        'std_speed_3m',
        'stopped_ratio_3m',
        'stopped_ratio_5m',
        'dist_traveled_3m_m',
        'dist_traveled_5m_m',
        'dist_to_target_m',
        'implied_speed_kmh',
        'speed_diff_kmh',
        'speed_ratio',
    ]
    
    X_train = df_train_feat[feature_cols].fillna(0)
    y_train = (df_train_feat['target_delay_s'] - df_train_feat['cur_dev_s']).values
    
    X_test = df_test_feat[feature_cols].fillna(0)
    y_test = (df_test_feat['target_delay_s'] - df_test_feat['cur_dev_s']).values
    
    X_val = df_val_feat[feature_cols].fillna(0)
    
    print(f"\nFeature matrix shapes: X_train {X_train.shape}, X_test {X_test.shape}, X_val {X_val.shape}")
    
    print("=== 3. Training CatBoostRegressor ===")
    cb = CatBoostRegressor(
        iterations=700,
        learning_rate=0.03,
        depth=6,
        loss_function='MAE',
        eval_metric='MAE',
        random_seed=42,
        verbose=100
    )
    
    cb.fit(X_train, y_train, eval_set=(X_test, y_test), early_stopping_rounds=50)
    
    # Save model
    os.makedirs("models", exist_ok=True)
    cb.save_model("models/catboost_delta_predictor.cbm")
    print("Model saved to models/catboost_delta_predictor.cbm")
    
    # Feature importances
    fi = pd.Series(cb.get_feature_importance(), index=feature_cols).sort_values(ascending=False)
    print("\nTop 10 Feature Importances:")
    print(fi.head(10))
    
    print("\n=== 4. Evaluation on TEST set ===")
    pred_delta_test = cb.predict(X_test)
    pred_test = df_test_feat['cur_dev_s'].values + pred_delta_test
    actual_test = df_test_feat['target_delay_s'].values
    
    mae_zero_test = np.mean(np.abs(actual_test))
    mae_base_test = np.mean(np.abs(actual_test - df_test_feat['cur_dev_s'].values))
    mae_cb_test = np.mean(np.abs(actual_test - pred_test))
    
    print(f"Test MAE (Zero baseline): {mae_zero_test:.2f} s")
    print(f"Test MAE (cur_dev_s baseline): {mae_base_test:.2f} s")
    print(f"Test MAE (CatBoost model): {mae_cb_test:.2f} s")
    print(f"Improvement over baseline: {mae_base_test - mae_cb_test:.2f} s ({(mae_base_test - mae_cb_test)/mae_base_test:.1%})")
    
    print("\n=== 5. Evaluation & Submission for VALIDATE ===")
    pred_delta_val = cb.predict(X_val)
    pred_val = df_val_feat['cur_dev_s'].values + pred_delta_val
    
    # Local ground truth check for validate
    test_sched['time_begin_dt'] = pd.to_datetime(test_sched['time_begin'])
    test_sched['time_fact_begin_dt'] = pd.to_datetime(test_sched['time_fact_begin'])
    test_sched['exact_delay_s'] = (test_sched['time_fact_begin_dt'] - test_sched['time_begin_dt']).dt.total_seconds()
    
    val_merged = df_val_feat.merge(
        test_sched[['tt_action_item_id', 'exact_delay_s']],
        left_on='target_stop_id',
        right_on='tt_action_item_id',
        how='left'
    )
    
    if val_merged['exact_delay_s'].notnull().all():
        fact_val = val_merged['exact_delay_s'].values
        mae_zero_val = np.mean(np.abs(fact_val))
        mae_base_val = np.mean(np.abs(fact_val - df_val_feat['cur_dev_s'].values))
        mae_cb_val = np.mean(np.abs(fact_val - pred_val))
        
        print(f"Validate MAE (Zero baseline): {mae_zero_val:.2f} s")
        print(f"Validate MAE (cur_dev_s baseline): {mae_base_val:.2f} s")
        print(f"Validate MAE (CatBoost model): {mae_cb_val:.2f} s")
        print(f"Validate improvement: {mae_base_val - mae_cb_val:.2f} s ({(mae_base_val - mae_cb_val)/mae_base_val:.1%})")
    
    # Save submission file
    submission = pd.DataFrame({
        'sample_id': df_val_feat['sample_id'],
        'prediction': np.round(pred_val, 1)
    })
    
    sub_path = "submission_catboost.csv"
    submission.to_csv(sub_path, sep=';', index=False)
    print(f"\nSaved submission to {sub_path} with {len(submission)} rows.")
    print("Head of submission:")
    print(submission.head(5))

if __name__ == '__main__':
    main()
