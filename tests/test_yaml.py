from fakts import Fakts
from fakts.grants.yaml import YamlGrant
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_loading():
    konfik = Fakts(grants=[YamlGrant(filepath=TESTS_FOLDER + "/bergen.yaml")])
    konfik.load()

    assert konfik.load_group("herre") != {}, "No Konfik for group {herre} found"
    assert konfik.load_group("ss") == {}, "Received not empty dictionary on loading group for non exisiting Group"