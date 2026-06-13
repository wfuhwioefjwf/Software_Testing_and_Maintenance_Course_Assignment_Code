"""
Dataset loading for DiMER on ChaosBoutique data.
Converts univariate time series from chaos_data JSON files into multivariate format.
"""
import json
import os
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler


class ChaosBoutiqueDataset(Dataset):
    """
    Multivariate time series dataset from ChaosBoutique chaos injection data.

    Data organization:
    - For each fault scenario, we combine all pod metrics into a single MTS
    - Features: 12 pods × 2 metrics (CPU, memory) = 24 features
    - Training: baseline (normal) data
    - Testing: fault injection data (with anomaly labels)
    """
    def __init__(self, data, labels=None, window_size=5):
        """
        Args:
            data: (T, F) numpy array of multivariate time series
            labels: (T,) numpy array of labels (0=normal, 1=anomaly), None for training
            window_size: sliding window size
        """
        self.data = torch.FloatTensor(data)
        self.labels = torch.LongTensor(labels) if labels is not None else None
        self.window_size = window_size

    def __len__(self):
        return max(0, len(self.data) - self.window_size + 1)

    def __getitem__(self, idx):
        x = self.data[idx:idx + self.window_size]  # (window, F)
        if self.labels is not None:
            # Use the label of the last point in the window
            label = self.labels[idx + self.window_size - 1]
            return x, label
        return x


def load_chaos_data(data_dir, fault_scenario):
    """
    Load chaos data for a specific fault scenario.

    Args:
        data_dir: path to chaos_data directory
        fault_scenario: name of fault scenario (e.g., 'network_delay_frontend')

    Returns:
        baseline_data: dict of baseline time series
        fault_data: dict of fault time series
    """
    baseline_path = os.path.join(data_dir, 'baseline_normal.json')
    fault_path = os.path.join(data_dir, f'{fault_scenario}_fault.json')

    with open(baseline_path, 'r') as f:
        baseline_data = json.load(f)
    with open(fault_path, 'r') as f:
        fault_data = json.load(f)

    return baseline_data, fault_data


def extract_multivariate_series(data_dict, pod_order=None):
    """
    Extract multivariate time series from the data dictionary.
    Combines CPU and memory metrics for all pods into a single MTS.

    Args:
        data_dict: dict from JSON file
        pod_order: list of pod names to use (for consistent ordering)

    Returns:
        mts: (T, F) numpy array where F = num_pods × num_metrics
        feature_names: list of feature names
    """
    # Get unique pods and metrics
    pods = sorted(set(s['pod'] for s in data_dict.values()))
    metrics = sorted(set(s['metric_name'] for s in data_dict.values()))

    if pod_order is not None:
        pods = pod_order

    # Get time series length
    first_key = list(data_dict.keys())[0]
    T = len(data_dict[first_key]['values'])

    # Build MTS
    F = len(pods) * len(metrics)
    mts = np.zeros((T, F))
    feature_names = []

    col_idx = 0
    for pod in pods:
        for metric in metrics:
            # Find the matching series
            found = False
            for key, series in data_dict.items():
                if series['pod'] == pod and series['metric_name'] == metric:
                    values = series['values']
                    if len(values) == T:
                        mts[:, col_idx] = values
                    found = True
                    break
            if not found:
                # Fill with zeros if not found
                mts[:, col_idx] = 0

            feature_names.append(f"{metric}_{pod.split('-')[0]}")
            col_idx += 1

    return mts, feature_names


def prepare_dimer_data(data_dir, fault_scenario, window_size=5, train_ratio=0.7):
    """
    Prepare data for DiMER training and testing.

    Args:
        data_dir: path to chaos_data directory
        fault_scenario: name of fault scenario
        window_size: sliding window size
        train_ratio: ratio of baseline data used for training

    Returns:
        train_dataset: ChaosBoutiqueDataset for training
        test_dataset: ChaosBoutiqueDataset for testing
        feature_names: list of feature names
    """
    baseline_data, fault_data = load_chaos_data(data_dir, fault_scenario)

    # Get consistent pod ordering
    pods = sorted(set(s['pod'] for s in baseline_data.values()))

    # Extract multivariate series
    baseline_mts, feature_names = extract_multivariate_series(baseline_data, pods)
    fault_mts, _ = extract_multivariate_series(fault_data, pods)

    # Normalize using baseline statistics
    scaler = StandardScaler()
    scaler.fit(baseline_mts)
    baseline_mts = scaler.transform(baseline_mts)
    fault_mts = scaler.transform(fault_mts)

    # Split baseline into train/validation
    n_train = int(len(baseline_mts) * train_ratio)
    train_data = baseline_mts[:n_train]
    valid_data = baseline_mts[n_train:]

    # Test data: baseline validation + fault
    test_data = np.concatenate([valid_data, fault_mts], axis=0)
    test_labels = np.concatenate([
        np.zeros(len(valid_data)),
        np.ones(len(fault_mts))
    ])

    # Create datasets
    train_dataset = ChaosBoutiqueDataset(train_data, window_size=window_size)
    test_dataset = ChaosBoutiqueDataset(test_data, labels=test_labels, window_size=window_size)

    return train_dataset, test_dataset, feature_names


def get_all_fault_scenarios(data_dir):
    """Get list of all fault scenarios in the data directory."""
    scenarios = []
    for f in os.listdir(data_dir):
        if f.endswith('_fault.json'):
            scenario = f.replace('_fault.json', '')
            scenarios.append(scenario)
    return sorted(scenarios)
