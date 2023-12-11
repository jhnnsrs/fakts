from fakts import Fakts
from fakts.grants.io.yaml import YamlGrant
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_yaml_grant():
    fakts = Fakts(grant=YamlGrant(filepath=f"{TESTS_FOLDER}/test.yaml"))
    with fakts:
        assert fakts.get("test")["hello"]["world"] == "Hello world"
