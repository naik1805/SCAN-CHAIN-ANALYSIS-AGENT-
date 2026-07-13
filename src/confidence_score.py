import json
import numpy as np
import pandas as pd
from pathlib import Path

class LogisticRegressionModel:
    """Zero-dependency Logistic Regression classifier using binary cross-entropy gradient descent."""
    def __init__(self, n_features: int):
        self.weights = np.zeros(n_features)
        self.bias = 0.0
        
    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 1500, lr: float = 0.1):
        m = len(y)
        for _ in range(epochs):
            # Sigmoid activation
            z = np.dot(X, self.weights) + self.bias
            h = 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))
            
            # Gradients
            dw = (1.0 / m) * np.dot(X.T, (h - y))
            db = (1.0 / m) * np.sum(h - y)
            
            # Gradient descent step
            self.weights -= lr * dw
            self.bias -= lr * db
            
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = np.dot(X, self.weights) + self.bias
        return 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))

def _extract_features(records: list[dict]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Helper to convert raw PFA dict records into features X, targets y, and metadata."""
    df = pd.DataFrame(records)
    
    # Continuous features
    df["offset_ratio"] = df["offset_from_scan_in"] / df["chain_length"]
    df["log_pattern_count"] = np.log(1.0 + df["pattern_count"])
    
    # One-hot encode root causes
    for rc in ["SHIFT", "SETUP", "HOLD", "DEFECT"]:
        df[f"rc_{rc}"] = (df["root_cause_type"] == rc).astype(float)
        
    feature_cols = [
        "pattern_consistency", "offset_ratio", "log_pattern_count",
        "rc_SHIFT", "rc_SETUP", "rc_HOLD", "rc_DEFECT"
    ]
    
    X = df[feature_cols].to_numpy().astype(float)
    y = df["pfa_confirmed"].to_numpy().astype(float) if "pfa_confirmed" in df.columns else np.zeros(len(df))
    
    # Compute mean and standard deviation for normalization (of continuous columns only)
    means = {}
    stds = {}
    for idx, col in enumerate(feature_cols):
        if not col.startswith("rc_"):
            means[col] = float(np.mean(X[:, idx]))
            stds[col] = float(np.std(X[:, idx]))
            if stds[col] == 0:
                stds[col] = 1.0
        else:
            means[col] = 0.0
            stds[col] = 1.0
            
    meta = {
        "feature_cols": feature_cols,
        "means": means,
        "stds": stds
    }
    
    return X, y, meta

def train_confidence_model(data_path: str | Path, model_dir: str | Path = "data/models") -> dict:
    """Train the Logistic Regression model on historical PFA confirmation records."""
    data_path = Path(data_path)
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    
    if not data_path.exists():
        raise FileNotFoundError(f"Historical database not found at {data_path}")
        
    records = json.loads(data_path.read_text(encoding="utf-8"))
    X_raw, y, meta = _extract_features(records)
    
    # Standardize continuous features
    X_norm = X_raw.copy()
    for idx, col in enumerate(meta["feature_cols"]):
        if not col.startswith("rc_"):
            X_norm[:, idx] = (X_raw[:, idx] - meta["means"][col]) / meta["stds"][col]
            
    # Train
    model = LogisticRegressionModel(X_raw.shape[1])
    model.fit(X_norm, y)
    
    # Serialize weights
    model_data = {
        "feature_cols": meta["feature_cols"],
        "means": meta["means"],
        "stds": meta["stds"],
        "weights": model.weights.tolist(),
        "bias": float(model.bias)
    }
    
    out_path = model_dir / "confidence_classifier.json"
    out_path.write_text(json.dumps(model_data, indent=2), encoding="utf-8")
    return model_data

def load_confidence_model(model_dir: str | Path = "data/models") -> dict:
    """Load pre-trained weights, or train a new model if weights are missing."""
    model_dir = Path(model_dir)
    model_path = model_dir / "confidence_classifier.json"
    
    if not model_path.exists():
        # Fall back to training model from data/historical_pfa_accuracy.json
        hist_path = Path("data/historical_pfa_accuracy.json")
        if not hist_path.exists():
            # If historical data is missing, we initialize defaults
            feature_cols = [
                "pattern_consistency", "offset_ratio", "log_pattern_count",
                "rc_SHIFT", "rc_SETUP", "rc_HOLD", "rc_DEFECT"
            ]
            return {
                "feature_cols": feature_cols,
                "means": {c: 0.5 for c in feature_cols if not c.startswith("rc_")},
                "stds": {c: 1.0 for c in feature_cols if not c.startswith("rc_")},
                "weights": [2.5, -1.0, 0.8, 1.2, 0.4, -0.4, 0.1],
                "bias": -1.5
            }
        train_confidence_model(hist_path, model_dir)
        
    return json.loads(model_path.read_text(encoding="utf-8"))

def predict_diagnosis_confidence(suspects_df: pd.DataFrame, model_data: dict) -> pd.DataFrame:
    """Predict composite PFA confirmation confidence score for localized cells."""
    if suspects_df.empty:
        return suspects_df
        
    df = suspects_df.copy()
    
    # 1. Feature extraction
    if "pattern_consistency" not in df.columns:
        df["pattern_consistency"] = df["confidence"] if "confidence" in df.columns else 0.5
    df["offset_ratio"] = df["offset_from_scan_in"] / df["chain_length"]
    df["log_pattern_count"] = np.log(1.0 + df["observations"])
    
    # Map root causes to one-hot categories
    def get_rc_category(r):
        rc = str(r.get("predicted_root_cause", "UNKNOWN")).upper()
        if "SHIFT" in rc or "BREAK" in rc:
            return "SHIFT"
        elif "SETUP" in rc:
            return "SETUP"
        elif "HOLD" in rc:
            return "HOLD"
        else:
            return "DEFECT"
            
    df["rc_cat"] = df.apply(get_rc_category, axis=1)
    
    for rc in ["SHIFT", "SETUP", "HOLD", "DEFECT"]:
        df[f"rc_{rc}"] = (df["rc_cat"] == rc).astype(float)
        
    feature_cols = model_data["feature_cols"]
    X_raw = df[feature_cols].to_numpy().astype(float)
    
    # 2. Standardize
    X_norm = X_raw.copy()
    for idx, col in enumerate(feature_cols):
        if not col.startswith("rc_"):
            mean = model_data["means"].get(col, 0.0)
            std = model_data["stds"].get(col, 1.0)
            X_norm[:, idx] = (X_raw[:, idx] - mean) / std
            
    # 3. Predict probability
    weights = np.array(model_data["weights"])
    bias = float(model_data["bias"])
    
    z = np.dot(X_norm, weights) + bias
    probs = 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))
    
    # Replace the confidence column with the calculated ML probability
    suspects_df["confidence"] = probs.round(4)
    return suspects_df
