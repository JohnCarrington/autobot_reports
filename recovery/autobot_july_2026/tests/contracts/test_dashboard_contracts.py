import inspect
import importlib
import sys
import types


class _NoOp:
    """Object that accepts any attribute access or call, always returning itself."""
    def __getattr__(self, name):
        return _NoOp()
    def __call__(self, *a, **kw):
        # If called with an int (e.g. st.columns(3)), return a list of that many _NoOps
        if a and isinstance(a[0], int):
            return [_NoOp() for _ in range(a[0])]
        return _NoOp()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def __iter__(self):
        # Yield enough _NoOp items for any tuple-unpacking (e.g. st.columns(3))
        return iter([_NoOp() for _ in range(20)])
    def __bool__(self):
        return False
    def __int__(self):
        return 0
    def __float__(self):
        return 0.0
    def __index__(self):
        return 0
    def __str__(self):
        return ""
    def __format__(self, fmt):
        return ""
    def __len__(self):
        return 0


class _FakeStreamlit(types.ModuleType):
    """Fake streamlit module that returns a no-op for any attribute access."""
    def __getattr__(self, name):
        return _NoOp()


def _import_dashboard(monkeypatch):
    """Import dashboard.py with fake dependencies that aren't installed in test env."""
    # Provide fake psutil
    if "psutil" not in sys.modules:
        fake_psutil = types.ModuleType("psutil")
        fake_psutil.cpu_percent = lambda *a, **kw: 0.0
        fake_psutil.virtual_memory = lambda *a, **kw: types.SimpleNamespace(percent=0.0)
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    # Provide fake streamlit that accepts any call
    fake_st = _FakeStreamlit("streamlit")
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    import dashboard
    importlib.reload(dashboard)
    return dashboard


def test_dashboard_imports_successfully(monkeypatch):
    dashboard = _import_dashboard(monkeypatch)
    assert dashboard is not None


def test_dashboard_has_load_json(monkeypatch):
    dashboard = _import_dashboard(monkeypatch)
    assert hasattr(dashboard, "load_json")
    assert callable(dashboard.load_json)
    sig = inspect.signature(dashboard.load_json)
    assert "path" in sig.parameters


def test_dashboard_has_load_candles(monkeypatch):
    dashboard = _import_dashboard(monkeypatch)
    assert hasattr(dashboard, "load_candles")
    assert callable(dashboard.load_candles)
    sig = inspect.signature(dashboard.load_candles)
    assert "name" in sig.parameters


def test_dashboard_no_removed_helpers(monkeypatch):
    dashboard = _import_dashboard(monkeypatch)
    assert not hasattr(dashboard, "api_get")
    assert not hasattr(dashboard, "today_only")
    assert not hasattr(dashboard, "color_text")
