import importlib
import inspect
import pytest


def test_quant_services_exist():
    """Verify that all core quant services exist and contain expected functions/classes."""
    services = [
        "quant_engine.cvar_service",
        "quant_engine.tail_var_service",
        "quant_engine.garch_service",
        "quant_engine.stress_severity_service",
        "quant_engine.optimizer_service",
        "quant_engine.black_litterman_service",
        "quant_engine.backtest_service",
        "quant_engine.return_statistics_service",
        "quant_engine.rolling_service",
        "quant_engine.drawdown_service",
        "quant_engine.portfolio_metrics_service",
        "quant_engine.attribution_service",
        "quant_engine.factor_model_service",
        "quant_engine.correlation_regime_service",
        "quant_engine.risk_budgeting_service",
        "quant_engine.peer_group_service",
        "quant_engine.scoring_service",
        "quant_engine.active_share_service",
        "quant_engine.monte_carlo_service",
        "quant_engine.regime_service",
        "quant_engine.drift_service",
        "quant_engine.talib_momentum_service",
    ]

    for service_name in services:
        try:
            module = importlib.import_module(service_name)
        except ImportError as e:
            pytest.fail(f"Missing service {service_name}: {e}")

        # Ensure it has some functions or classes
        members = inspect.getmembers(module, predicate=lambda m: inspect.isfunction(m) or inspect.isclass(m))
        assert len(members) > 0, f"Service {service_name} appears to be empty."


def test_wealth_workers_exist():
    """Verify that background workers mentioned in the reference exist."""
    workers = [
        "app.domains.wealth.workers.instrument_ingestion",
        "app.domains.wealth.workers.benchmark_ingest",
        "app.domains.wealth.workers.portfolio_nav_synthesizer",
        "app.domains.wealth.workers.macro_ingestion",
        "app.domains.wealth.workers.treasury_ingestion",
        "app.domains.wealth.workers.ofr_ingestion",
        "app.domains.wealth.workers.bis_ingestion",
        "app.domains.wealth.workers.imf_ingestion",
        "app.domains.wealth.workers.nport_ingestion",
        "app.domains.wealth.workers.sec_13f_ingestion",
        "app.domains.wealth.workers.sec_adv_ingestion",
        "app.domains.wealth.workers.sec_bulk_ingestion",
        "app.domains.wealth.workers.form345_ingestion",
        "app.domains.wealth.workers.nport_fund_discovery",
        "app.domains.wealth.workers.universe_sync",
        "app.domains.wealth.workers.esma_ingestion",
        "app.domains.wealth.workers.risk_calc",
        "app.domains.wealth.workers.portfolio_eval",
        "app.domains.wealth.workers.drift_check",
        "app.domains.wealth.workers.regime_fit",
        "app.domains.wealth.workers.screening_batch",
        "app.domains.wealth.workers.watchlist_batch",
        "app.domains.wealth.workers.wealth_embedding_worker",
    ]

    for worker_module in workers:
        try:
            importlib.import_module(worker_module)
        except ImportError as e:
            pytest.fail(f"Missing worker {worker_module}: {e}")


def test_wealth_routes_exist():
    """Verify that the key endpoints routers mentioned in the reference exist."""
    routers = [
        "app.domains.wealth.routes.analytics",
        "app.domains.wealth.routes.entity_analytics",
        "app.domains.wealth.routes.risk",
    ]

    for route_module in routers:
        try:
            module = importlib.import_module(route_module)
        except ImportError as e:
            pytest.fail(f"Missing route module {route_module}: {e}")

        # Check for router attribute common to FastAPI route modules
        assert hasattr(module, "router"), f"Route module {route_module} is missing a 'router' object."
