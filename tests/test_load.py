from fakts import Fakts
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_loading():
    fakts = Fakts(fakts_path=f"{TESTS_FOLDER}/saved.fakts.yaml")
    assert fakts.get("test") != {}, f"No Konfik for group test found"
