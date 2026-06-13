"""
DiMER Loss Functions:
- L_rec: Reconstruction loss (MSE)
- L_rec*: Temporal reconstruction loss (autocorrelation)
- L_sparse: Sparse loss on memory usage
- L_contrast: Contrast loss (triplet-based)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def compute_autocorrelation(x, max_lag=None):
    """
    Compute autocorrelation function (ACF) of time series.
    Args:
        x: (batch, T, F) - time series
        max_lag: maximum lag for ACF
    Returns:
        acf: (batch, max_lag, F) - autocorrelation values
    """
    batch, T, F = x.shape
    if max_lag is None:
        max_lag = T // 2

    # Normalize
    mean = x.mean(dim=1, keepdim=True)
    x_centered = x - mean
    var = x_centered.var(dim=1, keepdim=True) + 1e-8

    # Compute ACF for each lag
    acf_list = []
    for lag in range(max_lag):
        if lag == 0:
            acf_list.append(torch.ones(batch, 1, F, device=x.device))
        else:
            # Correlation between x[t] and x[t-lag]
            x1 = x_centered[:, lag:, :]  # (batch, T-lag, F)
            x2 = x_centered[:, :T-lag, :]  # (batch, T-lag, F)
            corr = (x1 * x2).mean(dim=1) / var.squeeze(1)  # (batch, F)
            acf_list.append(corr.unsqueeze(1))

    acf = torch.cat(acf_list, dim=1)  # (batch, max_lag, F)
    return acf


class DiMERLoss(nn.Module):
    """
    Combined loss function for DiMER.
    L = L_rec + λ_rec* · L_rec* + λ_sparse · L_sparse + λ_contrast · L_contrast
    """
    def __init__(self, lambda_rec_star=1.0, lambda_sparse=0.1, lambda_contrast=0.5):
        super().__init__()
        self.lambda_rec_star = lambda_rec_star
        self.lambda_sparse = lambda_sparse
        self.lambda_contrast = lambda_contrast

    def forward(self, x, x_hat, z, z_enhanced, attn_weights, contrast_memory):
        """
        Args:
            x: (batch, T, F) - original time series
            x_hat: (batch, T, F) - reconstructed time series
            z: (batch, T, d) - latent vectors
            z_enhanced: (batch, T, d) - memory-enhanced latent vectors
            attn_weights: (batch, T, K) - memory attention weights
            contrast_memory: ContrastMemory module
        Returns:
            total_loss: combined loss
            loss_dict: dictionary of individual losses
        """
        # L_rec: MSE reconstruction loss
        l_rec = F.mse_loss(x_hat, x)

        # L_rec*: Temporal reconstruction loss (autocorrelation)
        acf_x = compute_autocorrelation(x)
        acf_x_hat = compute_autocorrelation(x_hat)
        l_rec_star = F.mse_loss(acf_x_hat, acf_x)

        # L_sparse: Encourage sparse memory usage
        # Use entropy of attention weights
        attn_mean = attn_weights.mean(dim=(0, 1))  # (K,)
        l_sparse = -(attn_mean * torch.log(attn_mean + 1e-8)).sum()

        # L_contrast: Contrast loss
        l_contrast = contrast_memory.compute_contrast_loss(z, z_enhanced, attn_weights)

        # Total loss
        total_loss = (l_rec
                      + self.lambda_rec_star * l_rec_star
                      + self.lambda_sparse * l_sparse
                      + self.lambda_contrast * l_contrast)

        loss_dict = {
            'total': total_loss.item(),
            'rec': l_rec.item(),
            'rec_star': l_rec_star.item(),
            'sparse': l_sparse.item(),
            'contrast': l_contrast.item(),
        }

        return total_loss, loss_dict
