"""Offline C3 tool-routing exercise using fictional aggregate evidence only."""
import json

from .tool_router import Adapter, ToolRouter


def synthetic_router():
    """Explicit fixture registry; this function is never used by production routes."""
    def core(args):
        return dict(kind='core_summary', demo=True, core_version='synthetic-core-v1',
                    observed_date='2020-01-01', topic=args.topic,
                    metrics={'total_animals': 20} if args.topic == 'herd' else {'mean_daily_thi': 75})
    def forecast(args):
        return dict(kind='c1_forecast', demo=True, core_version='synthetic-core-v1',
                    model_version=args.model_version, origin_date=args.origin_date or args.reference_date,
                    target_period=args.target_period, grain=args.grain, series=args.series,
                    forecast=100, lower=80, upper=120, quality_flags=['synthetic'])
    def simulation(args):
        # Deliberately fixed fixture, never a formula for intervention effectiveness.
        return dict(kind='c2_simulation', demo=True, core_version='synthetic-core-v1',
                    model_version='synthetic-simulator-fixture', **args.model_dump(),
                    baseline_litres=100, simulated_litres=105,
                    assumptions=['Fixed fictional test values; not a trained simulator.'])
    return ToolRouter(dict(core_summary=Adapter(core, True), c1_forecast=Adapter(forecast, True),
                           c2_simulation=Adapter(simulation, True)))


def main():
    router = synthetic_router()
    cases = [dict(tool='core_summary', arguments=dict(topic='herd')),
             dict(tool='c1_forecast', arguments=dict(reference_date='2020-01-01',
                 target_period='2020-01-02', grain='daily', series='herd_milk')),
             dict(tool='c2_simulation', arguments=dict(intervention='synthetic scenario')),
             dict(tool='c2_simulation', arguments=dict(intervention='synthetic scenario',
                 change_percent=10, horizon_days=7))]
    for case in cases:
        print(router.execute(case).model_dump_json())
    print(ToolRouter().execute(cases[-1]).model_dump_json())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
