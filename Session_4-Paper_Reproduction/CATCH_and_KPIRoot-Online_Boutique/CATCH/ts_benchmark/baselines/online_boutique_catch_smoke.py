from ts_benchmark.baselines.catch.CATCH import CATCH


DEFAULT_SMOKE_HYPER_PARAMS = {
    "batch_size": 4,
    "num_epochs": 1,
    "seq_len": 2,
    "patch_size": 2,
    "patch_stride": 1,
    "inference_patch_size": 2,
    "inference_patch_stride": 1,
    "d_model": 16,
    "d_ff": 16,
    "cf_dim": 8,
    "head_dim": 8,
    "e_layers": 1,
    "n_heads": 1,
    "patience": 1,
    "anomaly_ratio": [1.0],
}


def online_boutique_catch_smoke(**kwargs):
    hyper_params = DEFAULT_SMOKE_HYPER_PARAMS.copy()
    hyper_params.update(kwargs)
    return CATCH(**hyper_params)