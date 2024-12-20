import argparse
import datetime
import json
import requests
import socket
import sys

from pathlib import Path


ROOT = Path(__file__).parent
RECORDS_FILE = ROOT / ".records"

DYNV6_PREFIX = "https://dynv6.com/api/v2/zones"


def get_zone(domain, headers):
    """Retrieve the ID of the zone that matches `domain`."""
    zones = requests.get(
        DYNV6_PREFIX,
        headers=headers,
    ).json()
    for zone in zones:
        if zone.get("name") == domain:
            return zone
    return {}


def main():
    print(f"dynv6 update script {datetime.datetime.now(datetime.UTC)}")

    parser = argparse.ArgumentParser(
        description="A simple client for use with dynv6's REST API"
    )
    # To get the host's ipv6 address, we have to connect to something. This is a Google public DNS
    # server.
    parser.add_argument(
        "-6",
        "--ipv6",
        default="2001:4860:4860:0:0:0:0:8888",
        metavar="REMOTE_IPV6_ADDRESS",
    )
    parser.add_argument(
        "-z",
        "--zone",
        help="""Either the domain name for a zone (e.g., `example.com`) or a zone ID from dynv6 (see
        https://dynv6.github.io/api-spec/#tag/zones/operation/findZones""",
    )
    parser.add_argument(
        "-t", "--token", required=True, help="An HTTP token from https://dynv6.com/keys"
    )
    parser.add_argument(
        "-p",
        "--prefix",
        help="""The prefix for the record to be updated. If your dynv6 zone has the domain
        `my.zone`, then specifying a prefix of example updates `example.my.zone`. If left blank,
        updates will apply to the zone itself instead of to records.""",
    )
    args = parser.parse_args()
    ipv6_external_address = args.ipv6
    token = args.token
    prefix = args.prefix
    zone = args.zone

    # Attempt to use `zone` as an integral zone ID. If not, assume it's a domain name.
    try:
        zone_id = int(zone)
    except ValueError:
        zone_id = None

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    ipv4_record = None
    ipv6_record = None
    ipv4_record_address = None
    ipv6_record_address = None
    zone_ipv4 = None
    zone_ipv6 = None
    try:
        with open(RECORDS_FILE, "r", encoding="utf8") as state:
            contents = json.load(state)
            for record in contents:
                # One object in the JSON array dumped to `.record` may contain just a zone ID
                if "zone_id" in record:
                    record_zone_id = record["zone_id"]
                    zone_ipv4 = record.get("ipv4")
                    zone_ipv6 = record.get("ipv6")
                    if zone_id:
                        assert record_zone_id == zone_id
                    else:
                        zone_id = record_zone_id
                    continue
                # Other objects in the JSON array will contain either "A" (ipv4) or "AAAA" (ipv6)
                # records.
                if record.get("type") == "A":
                    ipv4_record = record.get("id")
                    ipv4_record_address = record.get("data")
                elif record.get("type") == "AAAA":
                    ipv6_record = record.get("id")
                    ipv6_record_address = record.get("data")
    except FileNotFoundError:
        pass
    except json.decoder.JSONDecodeError:
        pass

    # If all else fails, ask dynv6.com for a list of zones and look for one that matches
    if not zone_id:
        zone_data = get_zone(zone, headers)
        zone_id = zone_data.get("id")
        zone_ipv4 = zone_data.get("ipv4_address")
        zone_ipv6 = zone_data.get("ipv6_prefix")

    current_ipv4_address = None
    # uncomment to enable updating of an A record
    # This line obtains a publicly-visible ipv4 address
    # current_ipv4_address = requests.get("https://api.ipify.org").content.decode("utf8")
    try:
        # Attempt to connect to an external host using ipv6 and then get the socket's IP address
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.connect((ipv6_external_address, 1))
        current_ipv6_address = sock.getsockname()[0]
    except OSError:
        current_ipv6_address = None

    results = []

    if zone_id and not prefix:
        # Update an existing zone
        addresses = {}
        if current_ipv4_address and zone_ipv4 != current_ipv4_address:
            addresses["ipv4_address"] = current_ipv4_address
        if current_ipv6_address and zone_ipv6 != current_ipv6_address:
            addresses["ipv6_prefix"] = current_ipv6_address
        if addresses:
            print(f"Updating an existing zone ({zone_id})")
            response = requests.patch(
                f"{DYNV6_PREFIX}/{zone_id}",
                headers=headers,
                params=addresses,
            )
            data = response.json()
            assert data["id"] == zone_id
            result = {"zone_id": zone_id}
            if current_ipv4_address:
                result["ipv4"] = current_ipv4_address
            if current_ipv6_address:
                result["ipv6"] = current_ipv6_address
            print(f"Successfully updated zone: {result}")
            results.append(result)
        else:
            print(
                f"Zone {zone_id} unchanged "
                f"(ipv4: {current_ipv4_address}; ipv6: {current_ipv6_address}"
            )
    else:
        if not zone_id:
            # register a new zone
            params = {"name": zone}
            if current_ipv4_address:
                params["ipv4_address"] = current_ipv4_address
            if current_ipv6_address:
                params["ipv6_prefix"] = current_ipv6_address
            print(f"Creating a new zone ({zone})")
            result = requests.post(DYNV6_PREFIX, headers=headers, params=params)
            data = result.json()
            zone_id = data.get("id")
            if zone_id:
                result = {"zone_id": zone_id}
                zone_ipv4 = data.get("ipv4_address")
                if zone_ipv4:
                    result["ipv4"] = zone_ipv4
                zone_ipv6 = data.get("ipv6_prefix")
                if zone_ipv6:
                    result["ipv6"] = zone_ipv6
                print(f"Successfully created a zone: {result}")
                results.append(result)

        if prefix:
            # If there is no cached record ID for the prefix, query dynv6 and look for a match
            if ipv4_record is None and ipv6_record is None:
                records = requests.get(
                    f"{DYNV6_PREFIX}/{zone_id}/records",
                    headers=headers,
                ).json()
                for record in records:
                    if record.get("name") == prefix:
                        if record.get("type") == "A":
                            ipv4_record_address = record["data"]
                            ipv4_record = record["id"]
                        elif record.get("type") == "AAAA":
                            ipv6_record_address = record["data"]
                            ipv6_record = record["id"]

            records = []

            if current_ipv4_address is not None:
                records.append(
                    (
                        ipv4_record,
                        ipv4_record_address,
                        {"type": "A", "name": prefix, "data": current_ipv4_address},
                    )
                )
            if current_ipv6_address is not None:
                records.append(
                    (
                        ipv6_record,
                        ipv6_record_address,
                        {"type": "AAAA", "name": prefix, "data": current_ipv6_address},
                    )
                )

            for record_id, address, record in records:
                if record_id is None:
                    print(f"Creating a new record: {record}")
                    result = requests.post(
                        f"{DYNV6_PREFIX}/{zone_id}/records",
                        headers=headers,
                        params=record,
                    )
                    print(result)
                    record["id"] = result.json().get("id")
                    print(record)
                elif address != record["data"]:
                    # PATCH
                    print(f"Updating an existing record ({record_id}")
                    result = requests.patch(
                        f"{DYNV6_PREFIX}/{zone_id}/records/{record_id}",
                        headers=headers,
                        params=record,
                    )
                    result_id = result.json().get("id")
                    if result_id:
                        if record_id == result_id:
                            print(f"Successfully updated {record_id}: {address}")
                        else:
                            print(
                                f"Error! Attempted to update record {record_id}"
                                f" but updated {result_id} instead."
                            )
                    else:
                        print(
                            f"Error updating record {record_id}: {result} ({result.json()})",
                            file=sys.stderr,
                        )
                else:
                    print(f"Address unchanged: {address}")
                results.append(record)

    with open(RECORDS_FILE, "w", encoding="utf8") as records_file:
        json.dump(results, records_file)
        print("", file=records_file)


if __name__ == "__main__":
    main()
