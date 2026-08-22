import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib
import os

DATA_CSV = "extracted_features.csv"

def train():
    print(f"Loading data from {DATA_CSV}...")
    if not os.path.exists(DATA_CSV):
        print(f"File {DATA_CSV} not found! Run extract_dataset.py first.")
        return
        
    df = pd.read_csv(DATA_CSV)
    
    # Drop rows with NaN
    df = df.dropna()
    print(f"Total samples: {len(df)}")
    
    # Features and Targets
    features = ['hr', 'ptt_mean', 'ptt_std', 'ppg_amp_mean', 'rr_std']
    X = df[features].values
    
    y_sbp = df['sbp'].values
    y_dbp = df['dbp'].values
    
    # Split data (80% train, 20% test)
    X_train, X_test, y_sbp_train, y_sbp_test, y_dbp_train, y_dbp_test = train_test_split(
        X, y_sbp, y_dbp, test_size=0.2, random_state=42
    )
    
    print("\n--- Training SBP Model (XGBoost) ---")
    sbp_model = xgb.XGBRegressor(
        n_estimators=100, 
        learning_rate=0.1, 
        max_depth=5,
        random_state=42,
        tree_method="hist"
    )
    sbp_model.fit(X_train, y_sbp_train)
    sbp_preds = sbp_model.predict(X_test)
    
    print(f"SBP MAE:  {mean_absolute_error(y_sbp_test, sbp_preds):.2f} mmHg")
    print(f"SBP RMSE: {np.sqrt(mean_squared_error(y_sbp_test, sbp_preds)):.2f} mmHg")
    print(f"SBP R2:   {r2_score(y_sbp_test, sbp_preds):.4f}")
    
    print("\n--- Training DBP Model (XGBoost) ---")
    dbp_model = xgb.XGBRegressor(
        n_estimators=100, 
        learning_rate=0.1, 
        max_depth=5,
        random_state=42,
        tree_method="hist"
    )
    dbp_model.fit(X_train, y_dbp_train)
    dbp_preds = dbp_model.predict(X_test)
    
    print(f"DBP MAE:  {mean_absolute_error(y_dbp_test, dbp_preds):.2f} mmHg")
    print(f"DBP RMSE: {np.sqrt(mean_squared_error(y_dbp_test, dbp_preds)):.2f} mmHg")
    print(f"DBP R2:   {r2_score(y_dbp_test, dbp_preds):.4f}")
    
    # Export models
    os.makedirs("bp_model", exist_ok=True)
    joblib.dump(sbp_model, "bp_model/sbp_xgboost.pkl")
    joblib.dump(dbp_model, "bp_model/dbp_xgboost.pkl")
    print("\nModels exported to bp_model/sbp_xgboost.pkl and bp_model/dbp_xgboost.pkl")

if __name__ == "__main__":
    train()
