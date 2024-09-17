import pytest
from apps.pv_opt.pvpy import BatteryModel

def test_reuqires_args():
    # Dummy test to ensure that the pytest setup works.
    with pytest.raises(TypeError):
        BatteryModel()
