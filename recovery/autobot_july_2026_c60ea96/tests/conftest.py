import warnings
import pytest

@pytest.fixture(autouse=True)
def silence_pandas_concat_warning():
    warnings.filterwarnings(
        "ignore",
        message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated",
        category=FutureWarning,
        module="candle_builder",
    )
