"""
DiMER: Diminutive Memory-Enhanced Reconstruction
Paper: ICASSP 2025 - Contrast Memory for Unsupervised Anomaly Detection

Architecture:
    Input X ∈ R^(T×F) → Encoder → Z ∈ R^d → Contrast Memory → Z_enhanced → Decoder → X̂ ∈ R^(T×F)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


class Encoder(nn.Module):
    """
    Encoder: compresses MTS data X ∈ R^(T×F) into latent vector Z ∈ R^d.
    Uses MLP to process each time step independently.
    """
    def __init__(self, input_dim, hidden_dim, latent_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, latent_dim),
            nn.ReLU(),
        )

    def forward(self, x):
        """
        Args:
            x: (batch, T, F) - multivariate time series
        Returns:
            z: (batch, T, d) - latent vectors for each time step
        """
        return self.net(x)


class Decoder(nn.Module):
    """
    Decoder: reconstructs MTS data from latent vector Z.
    """
    def __init__(self, latent_dim, hidden_dim, output_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(latent_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, z):
        """
        Args:
            z: (batch, T, d) - latent vectors
        Returns:
            x_hat: (batch, T, F) - reconstructed time series
        """
        return self.net(z)


class ContrastMemory(nn.Module):
    """
    Contrast Memory: K memory slots of dimension d.
    Uses attention mechanism to read from memory and contrastive learning to train.
    """
    def __init__(self, num_slots, latent_dim, temperature=0.1):
        super().__init__()
        self.num_slots = num_slots
        self.latent_dim = latent_dim
        self.temperature = temperature

        # Learnable memory matrix M ∈ R^(K×d)
        self.memory = nn.Parameter(torch.randn(num_slots, latent_dim))
        nn.init.xavier_uniform_(self.memory)

    def read(self, z):
        """
        Read from memory using soft attention.
        Args:
            z: (batch, T, d) - query vectors
        Returns:
            z_enhanced: (batch, T, d) - memory-enhanced vectors
            attn_weights: (batch, T, K) - attention weights for sparse loss
        """
        batch, T, d = z.shape

        # Compute attention: similarity between query and memory slots
        # z: (batch, T, d), memory: (K, d)
        attn = torch.matmul(z, self.memory.T)  # (batch, T, K)
        attn = attn / (self.latent_dim ** 0.5)
        attn_weights = F.softmax(attn / self.temperature, dim=-1)  # (batch, T, K)

        # Read from memory
        z_memory = torch.matmul(attn_weights, self.memory)  # (batch, T, d)

        # Enhanced representation: residual connection
        z_enhanced = z + z_memory

        return z_enhanced, attn_weights

    def compute_contrast_loss(self, z, z_memory, attn_weights):
        """
        Compute contrast loss using triplets in memory space.
        Anchor: z_memory (read from memory)
        Positive: memory slot with highest attention
        Negative: memory slots with low attention
        """
        batch, T, d = z.shape

        # Find the most attended memory slot for each query
        max_attn_idx = attn_weights.argmax(dim=-1)  # (batch, T)
        positive = self.memory[max_attn_idx]  # (batch, T, d)

        # Negative: randomly sample from other memory slots
        neg_idx = torch.randint(0, self.num_slots, (batch, T), device=z.device)
        # Ensure negative is different from positive
        neg_idx = (neg_idx + 1) % self.num_slots
        negative = self.memory[neg_idx]  # (batch, T, d)

        # Triplet loss with margin
        pos_dist = F.pairwise_distance(z_memory.reshape(-1, d), positive.reshape(-1, d))
        neg_dist = F.pairwise_distance(z_memory.reshape(-1, d), negative.reshape(-1, d))

        # Contrastive loss: encourage anchor closer to positive than negative
        margin = 1.0
        contrast_loss = F.relu(pos_dist - neg_dist + margin).mean()

        return contrast_loss

    def compute_memory_distance(self, z):
        """
        Compute distance from z to the nearest memory slot (for anomaly detection).
        Args:
            z: (batch, T, d)
        Returns:
            dist: (batch, T) - distance to nearest memory slot
        """
        # z: (batch, T, d), memory: (K, d)
        dist = torch.cdist(z, self.memory.unsqueeze(0).expand(z.shape[0], -1, -1))  # (batch, T, K)
        min_dist, _ = dist.min(dim=-1)  # (batch, T)
        return min_dist


class DiMER(nn.Module):
    """
    DiMER: Diminutive Memory-Enhanced Reconstruction
    """
    def __init__(self, input_dim, hidden_dim=64, latent_dim=32,
                 num_memory_slots=10, temperature=0.1):
        super().__init__()
        self.input_dim = input_dim
        self.latent_dim = latent_dim

        self.encoder = Encoder(input_dim, hidden_dim, latent_dim)
        self.decoder = Decoder(latent_dim, hidden_dim, input_dim)
        self.contrast_memory = ContrastMemory(num_memory_slots, latent_dim, temperature)

    def forward(self, x):
        """
        Args:
            x: (batch, T, F) - input multivariate time series
        Returns:
            x_hat: (batch, T, F) - reconstructed time series
            z: (batch, T, d) - latent vectors
            z_enhanced: (batch, T, d) - memory-enhanced latent vectors
            attn_weights: (batch, T, K) - memory attention weights
        """
        # Encode
        z = self.encoder(x)  # (batch, T, d)

        # Read from contrast memory
        z_enhanced, attn_weights = self.contrast_memory.read(z)  # (batch, T, d)

        # Decode
        x_hat = self.decoder(z_enhanced)  # (batch, T, F)

        return x_hat, z, z_enhanced, attn_weights

    def compute_anomaly_score(self, x):
        """
        Compute anomaly score using multi-space composite detection criterion.
        ω_t: temporal space (reconstruction error)
        ψ_t: latent space (memory distance)
        """
        self.eval()
        with torch.no_grad():
            x_hat, z, z_enhanced, attn_weights = self.forward(x)

            # ω_t: reconstruction error
            omega = ((x - x_hat) ** 2).mean(dim=-1)  # (batch, T)

            # ψ_t: distance to nearest memory slot
            psi = self.contrast_memory.compute_memory_distance(z)  # (batch, T)

            # Composite score
            anomaly_score = omega + 0.5 * psi

        return anomaly_score, omega, psi
