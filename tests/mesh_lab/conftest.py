"""A throwaway mesh for the mesh tests: ionskale, and a peer serving HTTP.

The session fixture renders the control server's config and a throwaway CA,
brings ionskale up, creates a tailnet with an ACL, mints a key for the peer
and one for the app node the tests start, and then starts the peer. It is the
shape of arkirust's ``testing/mesh-lab/lab.sh``, self-contained.

The address the mesh advertises (``public_addr``, the DERP and STUN address)
has to be reachable from this process *and* from the peer container, so it is
not 127.0.0.1: it is the docker bridge's gateway (or ``FAKTS_MESH_TEST_ADDR``).
"""

import datetime
import ipaddress
import json
import os
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest

from ..conftest import _reserve_free_ports

COMPOSE_FILE = str(Path(__file__).parent / "docker-compose.yml")
TAILNET = "fakts"
PEER = "fakts-peer"

# The app node (tag:app) reaches the peer (tag:peer) on any port; nothing else.
ACL = {
    "tagOwners": {"tag:app": [], "tag:peer": []},
    "acls": [{"action": "accept", "src": ["tag:app"], "dst": ["tag:peer:*"]}],
}


@dataclass(frozen=True)
class MeshLab:
    coord_url: str
    """The control server, as the app node is told to join it."""
    app_key: str
    """A pre-authorized, reusable key for tag:app."""
    ca_file: str
    """The throwaway CA the control server's certificate is signed with."""
    peer: str = PEER
    """The peer's hostname on the mesh; it serves HTTP on :80."""


def _mesh_address() -> str:
    """An address of this host that its containers reach too."""
    configured = os.environ.get("FAKTS_MESH_TEST_ADDR")
    if configured:
        return configured
    try:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "docker0"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return out.split("inet ", 1)[1].split("/", 1)[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass
    # No docker0 (e.g. Docker Desktop): the address of the default route.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def _write_tls(directory: Path, address: str) -> None:
    """A P-256 CA and a server certificate for ionskale, signed by it."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fakts mesh lab CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        # Python 3.13's default context is VERIFY_X509_STRICT: without the key
        # identifiers it rejects the chain, and the health check just times out.
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName("ionskale"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        names.append(x509.IPAddress(ipaddress.ip_address(address)))
    except ValueError:
        names.append(x509.DNSName(address))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ionskale")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    tls = directory / "tls"
    tls.mkdir()
    pem = serialization.Encoding.PEM
    (tls / "ca.pem").write_bytes(ca.public_bytes(pem))
    (tls / "ionskale.pem").write_bytes(cert.public_bytes(pem) + ca.public_bytes(pem))
    (tls / "ionskale.key").write_bytes(
        key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    # Read by the container's unprivileged user; throwaway material.
    tls.chmod(0o755)
    for file in tls.iterdir():
        file.chmod(0o644)


def _write_config(directory: Path, address: str, https: int, stun: int, admin: str) -> None:
    (directory / "config.yaml").write_text(
        f"""listen_addr: ":443"
public_addr: "{address}:{https}"
stun_listen_addr: ":3478"
stun_public_addr: "{address}:{stun}"
tls:
  disable: false
  cert_file: /etc/ionscale/tls/ionskale.pem
  key_file: /etc/ionscale/tls/ionskale.key
keys:
  system_admin_key: "{admin}"
database:
  type: sqlite
  url: /data/ionscale/ionscale.db?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)
logging:
  level: info
"""
    )
    (directory / "acl.json").write_text(json.dumps(ACL))
    for file in ("config.yaml", "acl.json"):
        (directory / file).chmod(0o644)


def _wait_healthy(url: str, ca_file: str, timeout: float = 60) -> None:
    context = ssl.create_default_context(cafile=ca_file)
    deadline = time.monotonic() + timeout
    last: object = None
    while True:
        try:
            with urllib.request.urlopen(url, context=context, timeout=2) as response:
                if response.status == 200:
                    return
                last = f"HTTP {response.status}"
        except OSError as e:
            last = e
        if time.monotonic() > deadline:
            raise TimeoutError(f"ionskale did not become healthy at {url} (last: {last})")
        time.sleep(0.5)


@pytest.fixture(scope="session")
def mesh_lab() -> Iterator[MeshLab]:
    """The running mesh: ionskale with a tailnet, and the peer on it."""
    pytest.importorskip("arkitekt_mesh")
    if os.environ.get("FAKTS_SKIP_MESH_LAB"):
        pytest.skip("FAKTS_SKIP_MESH_LAB is set")
    from dokker import testing

    address = _mesh_address()
    https, stun = _reserve_free_ports(2)
    admin = secrets.token_hex(32)
    coord_url = f"https://{address}:{https}"

    with tempfile.TemporaryDirectory(prefix="fakts-mesh-lab-") as tmp:
        directory = Path(tmp)
        directory.chmod(0o755)
        _write_tls(directory, address)
        _write_config(directory, address, https, stun, admin)
        ca_file = str(directory / "tls" / "ca.pem")

        env = {
            "MESH_LAB_DIR": tmp,
            "MESH_LAB_URL": coord_url,
            "IONSKALE_HTTPS_PORT": str(https),
            "IONSKALE_STUN_PORT": str(stun),
            "PEER_KEY": "",
        }
        previous = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            setup = testing(COMPOSE_FILE)
            with setup as deployed:
                deployed.pull()
                deployed.up(services=["ionskale"])
                try:
                    _wait_healthy(f"{coord_url}/healthz", ca_file)
                except TimeoutError as e:
                    # Say why: a runner's docker differs in ways a local run hides.
                    state = deployed.ps(services=["ionskale"])
                    logs = "\n".join(line for _, line in deployed.logs(services=["ionskale"], tail=60))
                    raise TimeoutError(f"{e}\ncontainer: {state}\nlogs:\n{logs}") from None

                cli_env = {
                    "IONSCALE_ADDR": "https://localhost:443",
                    "IONSCALE_SKIP_VERIFY": "true",
                    "IONSCALE_SYSTEM_ADMIN_KEY": admin,
                }

                def ionscale(*args: str) -> str:
                    roll = deployed.exec("ionskale", ["ionscale", *args], env=cli_env)
                    return "\n".join(roll.stdout_list)

                def key(tag: str) -> str:
                    out = ionscale(
                        "auth-keys", "create", "--tailnet", TAILNET,
                        "--pre-authorized", "--tag", tag,
                    )
                    return out.split()[-1]

                ionscale("tailnets", "create", "-n", TAILNET)
                ionscale(
                    "tailnets", "set-acl-policy", "--tailnet", TAILNET,
                    "--file", "/etc/ionscale/acl.json",
                )
                os.environ["PEER_KEY"] = key("tag:peer")
                app_key = key("tag:app")

                deployed.up(services=["peer", "web"])
                deadline = time.monotonic() + 60
                while PEER not in ionscale("machines", "list", "--tailnet", TAILNET):
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"{PEER} did not join the mesh")
                    time.sleep(1)

                yield MeshLab(coord_url=coord_url, app_key=app_key, ca_file=ca_file)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
