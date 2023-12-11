from fakts import Fakts, EnvGrant
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_env_grant():
    os.environ["FAKTS_TEST__HELLO__WORLD"] = "Hello World"

    fakts = Fakts(grant=EnvGrant())
    with fakts:
        assert (
            fakts.get("test")["hello"]["world"] == "Hello World"
        ), "Incorrectly loaded the fakts"


def test_env_grant_with_prepend():
    os.environ["TEST_FAKTS_TEST__HELLO__WORLD"] = "Hello World"

    fakts = Fakts(grant=EnvGrant(prepend="TEST_FAKTS_"))
    with fakts:
        assert (
            fakts.get("test.hello.world") == "Hello World"
        ), "Incorrectly loaded the fakts"


def test_env_grant_with_delimiter():
    os.environ["FAKTS_TEST-HELLO-WORLD"] = "Hello World"

    fakts = Fakts(grant=EnvGrant(delimiter="-"))
    with fakts:
        assert (
            fakts.get("test")["hello"]["world"] == "Hello World"
        ), "Incorrectly loaded the fakts"
