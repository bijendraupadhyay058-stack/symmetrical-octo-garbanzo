"""A stand-in for TallyPrime's XML server, for trying the Tally import without Tally.

Usage:  python scripts/tally_simulator.py tally_purchase_vouchers_2025-04.xml [--port 9000] [--company NAME]

It answers the three requests FIN TAX PRO makes (company list, GST ledgers, vouchers for
a date range) from an XML file such as ``sample_data/tally_purchase_vouchers_2025-04.xml``.
It is only a simulation of the documented XML interface; check real imports against
TallyPrime itself.
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET


def _date(text: str) -> str:
    return datetime.strptime(text, "%d-%b-%Y").strftime("%Y%m%d")


def make_handler(source: bytes, company: str):
    root = ET.fromstring(re.sub(rb"^\s*<\?xml[^>]*\?>", b"", source))
    ledgers = "".join(ET.tostring(x, encoding="unicode") for x in root.iter("LEDGER"))
    vouchers = list(root.iter("VOUCHER"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            asked = re.search(r"<SVCURRENTCOMPANY>(.*?)</SVCURRENTCOMPANY>", body)
            if "FinTaxCompanies" in body:
                data = f'<COLLECTION><COMPANY NAME="{company}"><NAME>{company}</NAME></COMPANY></COLLECTION>'
            elif asked and asked.group(1).replace("&amp;", "&") != company:
                data = "<LINEERROR>Could not set &apos;SVCurrentCompany&apos; to &apos;" + asked.group(1) + \
                       "&apos;</LINEERROR>"
            elif "FinTaxLedgers" in body:
                data = f"<COLLECTION>{ledgers}</COLLECTION>"
            else:
                start = _date(re.search(r"<SVFROMDATE[^>]*>(.*?)</SVFROMDATE>", body).group(1))
                end = _date(re.search(r"<SVTODATE[^>]*>(.*?)</SVTODATE>", body).group(1))
                data = "<COLLECTION>" + "".join(ET.tostring(v, encoding="unicode") for v in vouchers
                                                if start <= (v.findtext("DATE") or "") <= end) + "</COLLECTION>"
            out = f"<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA>" \
                  f"{data}</DATA></BODY></ENVELOPE>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    return Handler


def serve(source: Path, port: int = 9000, company: str = "Shree Ganesh Traders", background: bool = False):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Path(source).read_bytes(), company))
    if background:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    print(f"Simulated Tally on http://127.0.0.1:{server.server_address[1]} – company '{company}' (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--company", default="Shree Ganesh Traders")
    a = ap.parse_args()
    serve(Path(a.file), a.port, a.company)
    sys.exit(0)
