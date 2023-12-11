from fakts import Fakts
from fakts.grants.io.yaml import YamlGrant
from fakts.grants.meta import CacheGrant
import os


TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_cache():
    grant = CacheGrant(grant=YamlGrant(filepath=f"{TESTS_FOLDER}/test.yaml"))

    fakts = Fakts(grant=grant)

    with fakts:
        assert fakts.get("test")["hello"]["world"] == "Hello world"
        assert fakts.get("test.hello.world") == "Hello world"
