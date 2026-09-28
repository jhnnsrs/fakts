"""The login manifest is built on arkitekt-spec's AppManifest, and its hash did not move.

The hash keys the token cache and binds a grant, so a changed hash sends every app
back through the device-code login. The digests below were computed with fakts'
own Manifest before it was built on the spec.
"""

import pytest
from arkitekt_spec import AppManifest, Requirement

from fakts.models import Manifest
from fakts.models import Requirement as FaktsRequirement

VECTORS = [{'manifest': {'identifier': 'starmist', 'version': '0.1.0', 'scopes': ['openid']},
  'hash': 'c3253e77a90f97c4675523590ba0febcc2c9375174b7ddbb9ef7e21412512cfa'},
 {'manifest': {'identifier': 'com.x',
               'version': '1.2.3',
               'scopes': ['read', 'openid'],
               'logo': 'http://l',
               'description': 'What it is',
               'requirements': [{'key': 'rekuest',
                                 'service': 'live.arkitekt.rekuest',
                                 'optional': False,
                                 'description': 'r'},
                                {'key': 'mikro',
                                 'service': 'live.arkitekt.mikro',
                                 'optional': True}],
               'device_id': 'dev-1',
               'public_sources': [{'kind': 'github', 'url': 'https://github.com/x/y'}]},
  'hash': 'de81a64bdfb85ed125301d4c30f1f5562e50bc49a201c7489b07aea528c53dbf'},
 {'manifest': {'identifier': 'app',
               'version': '0.0.1',
               'scopes': [],
               'requirements': None,
               'public_sources': None},
  'hash': 'cd432252e48177d2b07f85ee36f3296595f8ac55eb269f92a91567d951b3f802'}]


@pytest.mark.parametrize("vector", VECTORS)
def test_the_hash_is_what_it_was_before_the_spec(vector):
    assert Manifest(**vector["manifest"]).hash() == vector["hash"]


def test_the_spec_identity_fields_do_not_move_the_hash():
    base = VECTORS[0]["manifest"]
    assert Manifest(**base, author="someone", entrypoint="main:api").hash() == VECTORS[0]["hash"]


def test_the_login_manifest_is_the_spec_manifest():
    assert issubclass(Manifest, AppManifest)
    assert FaktsRequirement is Requirement


def test_a_misspelled_field_is_still_refused():
    with pytest.raises(ValueError):
        Manifest(identifier="a", version="1", scopes=[], authr="x")
