"""Local TLS material for the demo: a throw-away CA plus a server certificate for localhost / 127.0.0.1 signed by it.
    python3 tools/make_cert.py [DIR]      -> DIR/ca.pem (trust this), DIR/server.pem, DIR/server.key
The collector trusts ONLY the CA it is given (CA_BUNDLE), so a different server cannot impersonate the SaaS.
For a browser that trusts it without a warning use mkcert instead and pass TLS_CERT / TLS_KEY / TLS_CA to `demo.py up --tls`."""
import datetime as dt
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CICADA demo"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make(out, days: int = 7, host_names=("localhost",), ips=("127.0.0.1", "::1")) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    ca_key, key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca = (x509.CertificateBuilder().subject_name(_name("CICADA demo CA")).issuer_name(_name("CICADA demo CA")).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=days))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    san = [x509.DNSName(h) for h in host_names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    leaf = (x509.CertificateBuilder().subject_name(_name("cicada-saas")).issuer_name(ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = serialization.Encoding.PEM
    (out / "ca.pem").write_bytes(ca.public_bytes(pem))
    (out / "server.pem").write_bytes(leaf.public_bytes(pem))
    (out / "server.key").write_bytes(key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (out / "server.key").chmod(0o600)
    return {"ca": str(out / "ca.pem"), "cert": str(out / "server.pem"), "key": str(out / "server.key")}


if __name__ == "__main__":
    print(make(sys.argv[1] if len(sys.argv) > 1 else "data/tls"))
