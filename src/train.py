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
from submission_journal import save_submission
from validate_submission import validate

def main():
    print("=== 1. Loading raw data ===")
    train_labels = pd.read_csv("data/labels/labels_train.csv", dtype={"sample_id": str})
    test_labels = pd.read_csv("data/labels/labels_test.csv", dtype={"sample_id": str})
    val_points = pd.read_csv("data/validate/points.csv", dtype={"sample_id": str})
    
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
    
    X_train = df_train_feat[feature_cols]  # NaN остаются NaN: CatBoost обрабатывает их сам
    y_train = (df_train_feat['target_delay_s'] - df_train_feat['cur_dev_s']).values
    
    X_test = df_test_feat[feature_cols]  # NaN остаются NaN: CatBoost обрабатывает их сам
    y_test = (df_test_feat['target_delay_s'] - df_test_feat['cur_dev_s']).values
    
    X_val = df_val_feat[feature_cols]  # NaN остаются NaN: CatBoost обрабатывает их сам
    
    print(f"\nFeature matrix shapes: X_train {X_train.shape}, X_test {X_test.shape}, X_val {X_val.shape}")
    
    print("=== 3. Training CatBoostRegressor ===")
    # Параметры фиксированные: без early stopping и без подбора по test/validate.
    # Test используется только для печати MAE после обучения.
    cb = CatBoostRegressor(
        iterations=700,
        learning_rate=0.03,
        depth=6,
        loss_function='MAE',
        random_seed=42,
        verbose=0,
        allow_writing_files=False,
    )
    
    cb.fit(X_train, y_train)
    
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
    
    # Save submission file
    submission = pd.DataFrame({
        'sample_id': df_val_feat['sample_id'],
        'prediction': np.round(pred_val, 1)
    })
    
    sub_path = save_submission(submission, tag="baseline_v1", model="catboost_delta_legacy28",
                               features_version="legacy28", test_mae=mae_cb_test)
    errors = validate(sub_path)
    print(f"\nSaved submission to {sub_path} with {len(submission)} rows; validator: {errors or 'OK'}")

if __name__ == '__main__':
    main()
