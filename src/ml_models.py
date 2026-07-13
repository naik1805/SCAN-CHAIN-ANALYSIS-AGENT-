import numpy as np
import pandas as pd

class StandardScaler:
    """Standardize features by removing the mean and scaling to unit variance."""
    def __init__(self):
        self.mean_ = None
        self.scale_ = None

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        self.mean_ = np.mean(X, axis=0)
        self.scale_ = np.std(X, axis=0)
        # Avoid division by zero
        self.scale_[self.scale_ == 0] = 1.0
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        return (X - self.mean_) / self.scale_

    def fit_transform(self, X):
        return self.fit(X).transform(X)


class KNNClassifier:
    """K-Nearest Neighbors classifier implemented in pure NumPy."""
    def __init__(self):
        self.X_train = None
        self.y_train = None

    def fit(self, X, y):
        self.X_train = np.asarray(X, dtype=float)
        self.y_train = np.asarray(y)
        return self

    def predict(self, X_new, k=5):
        X_new = np.asarray(X_new, dtype=float)
        if self.X_train is None or len(self.X_train) == 0:
            return np.array(["UNKNOWN"] * len(X_new))
            
        n_samples = len(X_new)
        k_val = min(k, len(self.X_train))
        if k_val <= 0:
            return np.array(["UNKNOWN"] * n_samples)
            
        predictions = []
        batch_size = 1000
        train_sq = np.sum(self.X_train ** 2, axis=1)
        
        for i in range(0, n_samples, batch_size):
            X_batch = X_new[i:i+batch_size]
            batch_sq = np.sum(X_batch ** 2, axis=1, keepdims=True)
            
            # Pairwise squared distances: (batch_size, n_train)
            dists_sq = batch_sq + train_sq - 2 * X_batch.dot(self.X_train.T)
            dists_sq = np.maximum(dists_sq, 0.0)
            dists = np.sqrt(dists_sq)
            
            # Find the index of the k smallest distances
            nearest_idx = np.argpartition(dists, kth=k_val-1, axis=1)[:, :k_val]
            
            for row_idx in range(len(X_batch)):
                idx = nearest_idx[row_idx]
                # Sort indices by actual distance for exact mode matching
                idx = idx[np.argsort(dists[row_idx, idx])]
                nearest_labels = self.y_train[idx]
                
                # Majority vote
                unique_labels, counts = np.unique(nearest_labels, return_counts=True)
                mode_label = unique_labels[np.argmax(counts)]
                predictions.append(mode_label)
                
        return np.array(predictions)


class KMeansClustering:
    """K-Means clustering algorithm implemented in pure NumPy."""
    def __init__(self, k=3, max_iters=20, random_state=42):
        self.k = k
        self.max_iters = max_iters
        self.random_state = random_state
        self.centroids = None

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        n_samples, n_features = X.shape
        if n_samples < self.k:
            # Return dummy labels if not enough samples
            return np.zeros(n_samples, dtype=int)
            
        # Seed random generator
        rng = np.random.default_rng(self.random_state)
        
        # Initialize centroids randomly from data points
        init_idx = rng.choice(n_samples, size=self.k, replace=False)
        self.centroids = X[init_idx].copy()
        
        labels = np.zeros(n_samples, dtype=int)
        for _ in range(self.max_iters):
            # Compute Euclidean distances from points to centroids using broadcasting
            # X[:, np.newaxis, :] is shape (n_samples, 1, n_features)
            # Centroids[np.newaxis, :, :] is shape (1, k, n_features)
            dists = np.sqrt(np.sum((X[:, np.newaxis, :] - self.centroids[np.newaxis, :, :]) ** 2, axis=2))
            
            new_labels = np.argmin(dists, axis=1)
            
            new_centroids = np.zeros((self.k, n_features))
            for cluster_idx in range(self.k):
                points = X[new_labels == cluster_idx]
                if len(points) > 0:
                    new_centroids[cluster_idx] = np.mean(points, axis=0)
                else:
                    new_centroids[cluster_idx] = self.centroids[cluster_idx]
            
            if np.allclose(self.centroids, new_centroids):
                labels = new_labels
                break
                
            self.centroids = new_centroids
            labels = new_labels
            
        return labels
