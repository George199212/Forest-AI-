"""Read-only ISO 15143-3 diagnostics, separate from Operations Center JSON APIs."""
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from services.integrations import john_deere as jd

# Deere precision/get-started documents /Fleet/{pageNumber} on this sandbox host.
FLEET_URL = 'https://sandboxaemp.deere.com/Fleet/1'


def fleet_url(uri):
    try:
        p = urlsplit(uri)
        valid = (p.scheme == 'https' and p.hostname == 'sandboxaemp.deere.com'
                 and p.port in (None, 443) and not p.username and not p.password
                 and not p.fragment and p.path.startswith('/Fleet/')
                 and not any(ord(c) < 32 for c in uri))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise jd.DeereError('ISO Fleet returned a link outside the sandbox Fleet host.')
    return uri


def parse_fleet(content):
    # ElementTree does not fetch external entities. Reject DTD/entity declarations
    # and oversized payloads before parsing, including UTF-16 encoded declarations.
    if len(content) > 5_000_000 or b'<!DOCTYPE' in content.upper().replace(b'\x00', b'') or b'<!ENTITY' in content.upper().replace(b'\x00', b''):
        raise jd.DeereError('ISO Fleet returned an unsafe or oversized XML document.')
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError):
        raise jd.DeereError('ISO Fleet returned invalid XML.') from None
    local = lambda tag: tag.rsplit('}', 1)[-1]
    if local(root.tag) != 'Fleet':
        raise jd.DeereError('ISO Fleet returned an unexpected XML document.')
    equipment, links = [], {}
    for node in root:
        if local(node.tag) == 'Equipment':
            equipment.append(node)
        elif local(node.tag) in ('Links', 'Link'):
            fields = {local(child.tag): (child.text or '').strip() for child in node}
            rel, uri = fields.get('rel') or node.get('rel'), fields.get('href') or node.get('href')
            if rel and uri:
                links[rel] = jd.safe_link(uri, True) if rel in ('connections', 'manage_connection', 'manage_connections') else fleet_url(uri) if rel == 'next' else uri
    return equipment, links


class FleetDiagnostics:
    def __init__(self, client):
        self.client = client

    def get(self, uri):
        uri = fleet_url(uri)
        with jd._lock:
            tokens = self.client.tokens()
            if jd.expired(tokens):
                tokens = self.client.refresh()
            def request():
                return jd._request('GET', uri, headers={'Accept': 'application/xml',
                                   'Authorization': 'Bearer '+tokens['access_token']})
            response = request()
            if response.status_code == 401:
                tokens = self.client.refresh()
                response = request()
            if response.status_code == 204:
                return [], {}
            if response.status_code != 200:
                # Neither forbidden nor not found proves an empty fleet.
                raise jd.DeereError('ISO Fleet request failed (HTTP %d).' % response.status_code)
            return parse_fleet(response.content)

    def run(self):
        total, uri, seen, actions = 0, FLEET_URL, set(), {}
        while uri:
            if uri in seen or len(seen) >= 100:
                raise jd.DeereError('ISO Fleet pagination exceeded its safe limit.')
            seen.add(uri)
            values, links = self.get(uri)
            total += len(values)
            actions.update({rel: value for rel, value in links.items()
                            if rel in ('connections', 'manage_connection', 'manage_connections')})
            uri = links.get('next')
        return dict(status='available' if total else 'empty', machines=total,
                    connection_status='Authorization required' if 'connections' in actions else 'Not required',
                    checked_at=time.time()), actions
