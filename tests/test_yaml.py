from fakts import Fakts
from fakts.grants.yaml import YamlGrant
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_loading():
    fakts = Fakts(fakts_path=f"{TESTS_FOLDER}/fakts.yaml")
    assert fakts.get("test") != {}, f"No Konfik for group test found"
