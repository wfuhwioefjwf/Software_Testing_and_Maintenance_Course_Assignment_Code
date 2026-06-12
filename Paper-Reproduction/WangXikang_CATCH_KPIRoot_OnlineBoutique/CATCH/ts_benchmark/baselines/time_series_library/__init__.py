# -*- coding: utf-8 -*-
import importlib

__all__ = [
    "Autoformer",
    "Crossformer",
    "DLinear",
    "ETSformer",
    "FEDformer",
    "FiLM",
    "Informer",
    "iTransformer",
    "Koopa",
    "LightTS",
    "Linear",
    "MICN",
    "NLinear",
    "Nonstationary_Transformer",
    "PatchTST",
    "Pyraformer",
    "Reformer",
    "TimesNet",
    "Transformer",
    "Triformer"
]

_MODEL_MODULES = {
    "Autoformer": "ts_benchmark.baselines.time_series_library.models.Autoformer",
    "Crossformer": "ts_benchmark.baselines.time_series_library.models.Crossformer",
    "DLinear": "ts_benchmark.baselines.time_series_library.models.DLinear",
    "ETSformer": "ts_benchmark.baselines.time_series_library.models.ETSformer",
    "FEDformer": "ts_benchmark.baselines.time_series_library.models.FEDformer",
    "FiLM": "ts_benchmark.baselines.time_series_library.models.FiLM",
    "Informer": "ts_benchmark.baselines.time_series_library.models.Informer",
    "iTransformer": "ts_benchmark.baselines.time_series_library.models.iTransformer",
    "Koopa": "ts_benchmark.baselines.time_series_library.models.Koopa",
    "LightTS": "ts_benchmark.baselines.time_series_library.models.LightTS",
    "Linear": "ts_benchmark.baselines.time_series_library.patchs.Linear",
    "MICN": "ts_benchmark.baselines.time_series_library.models.MICN",
    "NLinear": "ts_benchmark.baselines.time_series_library.patchs.NLinear",
    "Nonstationary_Transformer": "ts_benchmark.baselines.time_series_library.models.Nonstationary_Transformer",
    "PatchTST": "ts_benchmark.baselines.time_series_library.models.PatchTST",
    "Pyraformer": "ts_benchmark.baselines.time_series_library.models.Pyraformer",
    "Reformer": "ts_benchmark.baselines.time_series_library.models.Reformer",
    "TimesNet": "ts_benchmark.baselines.time_series_library.models.TimesNet",
    "Transformer": "ts_benchmark.baselines.time_series_library.models.Transformer",
    "Triformer": "ts_benchmark.baselines.time_series_library.patchs.Triformer",
}


def __getattr__(name):
    if name not in _MODEL_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(_MODEL_MODULES[name])
    return getattr(module, name)


