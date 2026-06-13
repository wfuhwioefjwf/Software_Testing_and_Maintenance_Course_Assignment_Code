"""DiMER 短时故障数据实验"""
import os
import sys
import json
import numpy as np
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dimer.model import DiMER
from dimer.losses import DiMERLoss
from dimer.dataset import prepare_dimer_data, get_all_fault_scenarios

def train_epoch(model, dataloader, optimizer, criterion, device):
    model.train()
    total_loss = 0
    n_batches = 0
    for batch in dataloader:
        x = batch[0] if isinstance(batch, (list, tuple)) else batch
        x = x.to(device)
        optimizer.zero_grad()
        x_hat, z, z_enhanced, attn_weights = model(x)
        loss, _ = criterion(x, x_hat, z, z_enhanced, attn_weights, model.contrast_memory)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        n_batches += 1
    return total_loss / max(n_batches, 1)

def evaluate(model, dataloader, device):
    model.eval()
    all_scores, all_labels = [], []
    with torch.no_grad():
        for batch in dataloader:
            if isinstance(batch, (list, tuple)) and len(batch) == 2:
                x, labels = batch
            else:
                x = batch if not isinstance(batch, (list, tuple)) else batch[0]
                labels = None
            x = x.to(device)
            scores, _, _ = model.compute_anomaly_score(x)
            all_scores.extend(scores[:, -1].cpu().numpy())
            if labels is not None:
                all_labels.extend(labels.numpy())
    return np.array(all_scores), np.array(all_labels)

def find_best_threshold(scores, labels):
    best_f1, best_th = 0, 0
    for th in np.linspace(scores.min(), scores.max(), 200):
        f1 = f1_score(labels, (scores > th).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_th = f1, th
    return best_th, best_f1

def run_experiment(data_dir, scenario, config, device):
    print(f"\n{'='*60}\n{scenario}\n{'='*60}")
    train_ds, test_ds, features = prepare_dimer_data(data_dir, scenario, window_size=config['window_size'], train_ratio=config['train_ratio'])
    if len(train_ds) == 0 or len(test_ds) == 0:
        print("  Skipping: insufficient data")
        return None
    print(f"  Features: {len(features)}, Train: {len(train_ds)}, Test: {len(test_ds)}")
    train_loader = DataLoader(train_ds, batch_size=config['batch_size'], shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=config['batch_size'], shuffle=False)
    model = DiMER(input_dim=config['input_dim'], hidden_dim=config['hidden_dim'], latent_dim=config['latent_dim'], num_memory_slots=config['num_memory_slots'], temperature=config['temperature']).to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Parameters: {n_params:,}")
    criterion = DiMERLoss(lambda_rec_star=1.0, lambda_sparse=0.1, lambda_contrast=0.5)
    optimizer = torch.optim.Adam(model.parameters(), lr=config['lr'])
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)
    best_loss, patience, counter = float('inf'), 10, 0
    for epoch in range(1, config['epochs'] + 1):
        loss = train_epoch(model, train_loader, optimizer, criterion, device)
        scheduler.step()
        if epoch % 10 == 0 or epoch == 1:
            print(f"    Epoch {epoch}: loss={loss:.4f}")
        if loss < best_loss:
            best_loss, counter = loss, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            counter += 1
            if counter >= patience:
                print(f"    Early stopping at epoch {epoch}")
                break
    model.load_state_dict(best_state)
    scores, labels = evaluate(model, test_loader, device)
    if len(labels) == 0 or len(np.unique(labels)) < 2:
        return None
    best_th, _ = find_best_threshold(scores, labels)
    preds = (scores > best_th).astype(int)
    p = precision_score(labels, preds, zero_division=0)
    r = recall_score(labels, preds, zero_division=0)
    f1 = f1_score(labels, preds, zero_division=0)
    try:
        auc = roc_auc_score(labels, scores)
    except:
        auc = 0.0
    print(f"  P={p:.4f}, R={r:.4f}, F1={f1:.4f}, AUC={auc:.4f}")
    return {'scenario': scenario, 'precision': p, 'recall': r, 'f1': f1, 'auc': auc, 'n_params': n_params}

def main():
    config = {'input_dim': 24, 'hidden_dim': 64, 'latent_dim': 32, 'num_memory_slots': 20, 'temperature': 0.1, 'epochs': 100, 'batch_size': 16, 'lr': 0.001, 'window_size': 5, 'train_ratio': 0.7}
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Device: {device}")
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'chaos_data_short'))
    scenarios = get_all_fault_scenarios(data_dir)
    print(f"Scenarios: {len(scenarios)}")
    results = []
    for s in scenarios:
        r = run_experiment(data_dir, s, config, device)
        if r:
            results.append(r)
    if results:
        print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
        print(f"{'Scenario':<40} {'P':>8} {'R':>8} {'F1':>8} {'AUC':>8}")
        print("-" * 80)
        for r in results:
            print(f"{r['scenario']:<40} {r['precision']:>8.4f} {r['recall']:>8.4f} {r['f1']:>8.4f} {r['auc']:>8.4f}")
        print("-" * 80)
        avg = {k: np.mean([r[k] for r in results]) for k in ['precision', 'recall', 'f1', 'auc']}
        print(f"{'Average':<40} {avg['precision']:>8.4f} {avg['recall']:>8.4f} {avg['f1']:>8.4f} {avg['auc']:>8.4f}")
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, 'short_experiment_results.json'), 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {results_dir}/short_experiment_results.json")

if __name__ == '__main__':
    main()
