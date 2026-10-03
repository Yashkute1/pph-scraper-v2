import json, pathlib, pytest
FX = pathlib.Path(__file__).parent / "fixtures"

@pytest.fixture(scope="session")
def titles(): return json.loads((FX / "titles.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="session")
def golden(): return json.loads((FX / "golden_normalize.json").read_text(encoding="utf-8"))
