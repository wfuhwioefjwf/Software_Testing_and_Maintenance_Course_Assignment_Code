"""KAN-AD 短时故障数据实验"""
from EasyTSAD.Controller import TSADController
from kanad import KANAD  # noqa

if __name__ == "__main__":
    gctrl = TSADController()
    datasets = ["ChaosBoutiqueShort"]
    dataset_type = "UTS"
    gctrl.set_dataset(dataset_type=dataset_type, dirname="datasets", datasets=datasets)
    training_schema = "naive"
    method = "KANAD"
    gctrl.run_exps(method=method, training_schema=training_schema, cfg_path="kanad/config_short.toml")
    from EasyTSAD.Evaluations.Protocols import EventF1PA, PointF1PA, PointKthF1PA, PointAuprcPA
    gctrl.set_evals([PointF1PA(), EventF1PA(mode="squeeze"), PointKthF1PA(k=5), PointAuprcPA()])
    gctrl.do_evals(method=method, training_schema=training_schema)
    print("\n" + "="*60)
    print("KAN-AD 短时故障实验完成！")
    print("="*60)
