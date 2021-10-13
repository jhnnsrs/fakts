from konfik.grants.yaml import YamlGrant
from konfik.grants.beacon import BeaconGrant
from konfik.konfik import Konfik


konfik = Konfik(grants=[YamlGrant(filepath="bergen.yaml"), BeaconGrant()])
konfik.load()


print(konfik.load_group("herre"))