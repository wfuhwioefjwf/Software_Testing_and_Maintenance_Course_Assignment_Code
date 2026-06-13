"""
DiMER Experiment on ChaosBoutique Dataset
==========================================
Trains DiMER on normal (baseline) data and evaluates anomaly detection
on fault-injected data from Online-Boutique microservices.
"""
import os
import sys
import json
import time
import numpy as np
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dimer.model import DiMER
from dimer.losses import DiMERLoss
from dimer.dataset import prepare_dimer_data, get_all_fault_scenarios


def train_epoch(model, dataloader, optimizer, criterion, device):
    """Train for one epoch."""
    model.train()
    total_loss = 0
    loss_sums = {'rec': 0, 'rec_star': 0, 'sparse': 0, 'contrast': 0}
    n_batches = 0

    for batch in dataloader:
        if len(batch) == 2:
            x, _ = batch
        else:
            x = batch

        x = x.to(device)
        optimizer.zero_grad()

        # Forward pass
        x_hat, z, z_enhanced, attn_weights = model(x)

        # Compute loss
        loss, loss_dict = criterion(x, x_hat, z, z_enhanced, attn_weights,
                                     model.contrast_memory)

        # Backward pass
        loss.backward()
        optimizer.step()

        total_loss += loss.item()
        for k in loss_sums:
            loss_sums[k] += loss_dict[k]
        n_batches += 1

    avg_loss = total_loss / max(n_batches, 1)
    avg_losses = {k: v / max(n_batches, 1) for k, v in loss_sums.items()}
    return avg_loss, avg_losses


def evaluate(model, dataloader, device):
    """
    Evaluate anomaly detection performance.
    Returns anomaly scores and ground truth labels.
    """
    model.eval()
    all_scores = []
    all_labels = []

    with torch.no_grad():
        for batch in dataloader:
            if len(batch) == 2:
                x, labels = batch
            else:
                x = batch
                labels = None

            x = x.to(device)

            # Compute anomaly score
            scores, omega, psi = model.compute_anomaly_score(x)

            # Use the score of the last time step in the window
            score_last = scores[:, -1].cpu().numpy()
            all_scores.extend(score_last)

            if labels is not None:
                all_labels.extend(labels.numpy())

    return np.array(all_scores), np.array(all_labels)


def find_best_threshold(scores, labels, n_thresholds=100):
    """Find the threshold that maximizes F1 score."""
    best_f1 = 0
    best_threshold = 0

    for threshold in np.linspace(scores.min(), scores.max(), n_thresholds):
        preds = (scores > threshold).astype(int)
        f1 = f1_score(labels, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold

    return best_threshold, best_f1


def run_experiment(data_dir, fault_scenario, config, device):
    """Run DiMER experiment on a single fault scenario."""
    print(f"\n{'='*60}")
    print(f"Fault Scenario: {fault_scenario}")
    print(f"{'='*60}")

    # Prepare data
    train_dataset, test_dataset, feature_names = prepare_dimer_data(
        data_dir, fault_scenario,
        window_size=config['window_size'],
        train_ratio=config['train_ratio']
    )

    if len(train_dataset) == 0 or len(test_dataset) == 0:
        print(f"  Skipping: insufficient data")
        return None

    print(f"  Features: {len(feature_names)}")
    print(f"  Train samples: {len(train_dataset)}")
    print(f"  Test samples: {len(test_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=config['batch_size'], shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=config['batch_size'], shuffle=False)

    # Create model
    model = DiMER(
        input_dim=config['input_dim'],
        hidden_dim=config['hidden_dim'],
        latent_dim=config['latent_dim'],
        num_memory_slots=config['num_memory_slots'],
        temperature=config['temperature']
    ).to(device)

    # Count parameters
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Model parameters: {n_params:,}")

    # Loss and optimizer
    criterion = DiMERLoss(
        lambda_rec_star=config['lambda_rec_star'],
        lambda_sparse=config['lambda_sparse'],
        lambda_contrast=config['lambda_contrast']
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=config['lr'])
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)

    # Training
    print(f"\n  Training for {config['epochs']} epochs...")
    best_loss = float('inf')
    patience = 10
    patience_counter = 0

    for epoch in range(1, config['epochs'] + 1):
        avg_loss, loss_dict = train_epoch(model, train_loader, optimizer, criterion, device)
        scheduler.step()

        if epoch % 10 == 0 or epoch == 1:
            print(f"    Epoch {epoch:3d}: loss={avg_loss:.4f} "
                  f"(rec={loss_dict['rec']:.4f}, rec*={loss_dict['rec_star']:.4f}, "
                  f"sparse={loss_dict['sparse']:.4f}, contrast={loss_dict['contrast']:.4f})")

        # Early stopping
        if avg_loss < best_loss:
            best_loss = avg_loss
            patience_counter = 0
            # Save best model
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"    Early stopping at epoch {epoch}")
                break

    # Load best model
    model.load_state_dict(best_state)

    # Evaluation
    print(f"\n  Evaluating...")
    scores, labels = evaluate(model, test_loader, device)

    if len(labels) == 0 or len(np.unique(labels)) < 2:
        print(f"  Skipping evaluation: insufficient labels")
        return None

    # Find best threshold
    best_threshold, best_f1 = find_best_threshold(scores, labels)

    # Compute metrics with best threshold
    preds = (scores > best_threshold).astype(int)
    precision = precision_score(labels, preds, zero_division=0)
    recall = recall_score(labels, preds, zero_division=0)
    f1 = f1_score(labels, preds, zero_division=0)

    try:
        auc = roc_auc_score(labels, scores)
    except:
        auc = 0.0

    results = {
        'scenario': fault_scenario,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'auc': auc,
        'best_threshold': best_threshold,
        'n_params': n_params,
        'n_features': len(feature_names),
    }

    print(f"\n  Results:")
    print(f"    Precision: {precision:.4f}")
    print(f"    Recall:    {recall:.4f}")
    print(f"    F1 Score:  {f1:.4f}")
    print(f"    AUC:       {auc:.4f}")

    return results


def main():
    # Configuration
    config = {
        'input_dim': 24,        # 12 pods × 2 metrics
        'hidden_dim': 64,
        'latent_dim': 32,
        'num_memory_slots': 10,
        'temperature': 0.1,
        'epochs': 100,
        'batch_size': 16,
        'lr': 0.001,
        'window_size': 5,
        'lambda_rec_star': 1.0,
        'lambda_sparse': 0.1,
        'lambda_contrast': 0.5,
        'train_ratio': 0.7,
    }

    # Device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    # Data directory
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'chaos_data')
    data_dir = os.path.abspath(data_dir)

    if not os.path.exists(data_dir):
        print(f"ERROR: Data directory not found: {data_dir}")
        return

    # Get all fault scenarios
    scenarios = get_all_fault_scenarios(data_dir)
    print(f"Found {len(scenarios)} fault scenarios: {scenarios}")

    # Run experiments
    all_results = []
    for scenario in scenarios:
        result = run_experiment(data_dir, scenario, config, device)
        if result is not None:
            all_results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")

    if all_results:
        # Print results table
        print(f"\n{'Scenario':<35} {'P':>8} {'R':>8} {'F1':>8} {'AUC':>8}")
        print("-" * 75)
        for r in all_results:
            print(f"{r['scenario']:<35} {r['precision']:>8.4f} {r['recall']:>8.4f} "
                  f"{r['f1']:>8.4f} {r['auc']:>8.4f}")

        # Average
        avg_p = np.mean([r['precision'] for r in all_results])
        avg_r = np.mean([r['recall'] for r in all_results])
        avg_f1 = np.mean([r['f1'] for r in all_results])
        avg_auc = np.mean([r['auc'] for r in all_results])
        print("-" * 75)
        print(f"{'Average':<35} {avg_p:>8.4f} {avg_r:>8.4f} {avg_f1:>8.4f} {avg_auc:>8.4f}")

        print(f"\nModel Parameters: {all_results[0]['n_params']:,}")
        print(f"Features: {all_results[0]['n_features']}")

    # Save results
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
    os.makedirs(results_dir, exist_ok=True)
    results_path = os.path.join(results_dir, 'chaos_experiment_results.json')
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to: {results_path}")


if __name__ == '__main__':
    main()
