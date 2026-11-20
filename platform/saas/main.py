"""Run the SaaS:  python3 -m saas.main --port 8000   (add --certfile/--keyfile for TLS; mkcert makes local certs)
Tracker page: http://localhost:8000/tracker   dev logins: alpha-admin / alpha-demo-pass, beta-admin / beta-demo-pass"""
import argparse

import uvicorn

from saas.app import create_app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--certfile")
    ap.add_argument("--keyfile")
    a = ap.parse_args()
    from saas import envfile
    envfile.load()                                   # .env fills gaps; real env vars win
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning", ssl_certfile=a.certfile, ssl_keyfile=a.keyfile)


if __name__ == "__main__":
    main()
