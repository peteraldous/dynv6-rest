import argparse
import datetime
import json
import requests
import socket
import sys

from pathlib import Path


ROOT = Path(__file__).parent
RECORDS_FILE = ROOT / ".records"
ZONE_FILE = ROOT / ".zone"

DYNV6_PREFIX = "https://dynv6.com/api/v2/zones"


def get_zone(domain, headers):
    """Retrieve the ID of the zone that matches `domain`."""
    zones = requests.get(
        DYNV6_PREFIX,
        headers=headers,
    ).json()
    for zone in zones:
        if zone.get("name") == domain:
            return zone.get("id")
    return None


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
        help="""The domain name for a zone (e.g., `example.com`)""",
    )
    parser.add_argument(
        "-i",
        "--zone_id",
        help=(
            """A numerical zone ID from dynv6 (see """
            """https://dynv6.github.io/api-spec/#tag/zones/operation/findZones)"""
        ),
        type=int,
    )
    parser.add_argument(
        "-t", "--token", required=True, help="An HTTP token from https://dynv6.com/keys"
    )
    parser.add_argument(
        "-p",
        "--prefix",
        help="""The prefix for the record to be updated. If your dynv6 zone has the domain
        `my.zone`, then specifying a prefix of example updates `example.my.zone`.""",
        required=True,
    )
    args = parser.parse_args()
    ipv6_external_address = args.ipv6
    token = args.token
    prefix = args.prefix

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    cache_zone = None
    cache_zone_id = None
    try:
        with open(ZONE_FILE, "r", encoding="utf8") as zone_file:
            contents = json.load(zone_file)
            cache_zone = contents.get("name")
            cache_zone_id = contents.get("id")
    except FileNotFoundError:
        pass
    except json.decoder.JSONDecodeError:
        pass

    # Manual validation of zone and zone_id

    zone = args.zone
    if zone is None:
        zone = cache_zone
    else:
        assert cache_zone is None or cache_zone == zone

    zone_id = args.zone_id
    if zone_id is None:
        zone_id = cache_zone_id
    else:
        assert cache_zone_id is None or cache_zone_id == zone_id

    if zone is None and zone_id is None:
        raise argparse.ArgumentError(
            "A zone must be specified. It may be specified with -z "
            f"or -i on the command line or as `name` or `id` in {ZONE_FILE}"
        )

    if zone_id is None:
        zone_id = get_zone(zone, headers)

    cache_id4 = None
    cache_id6 = None
    cache_address4 = None
    cache_address6 = None
    try:
        with open(RECORDS_FILE, "r", encoding="utf8") as state:
            contents = json.load(state)
            for record in contents:
                # If there is a name but it doesn't match the specified prefix, ignore it
                name = record.get("name")
                if name and name != prefix:
                    continue
                # Look up A (ipv4) and AAAA (ipv6) data from the cache
                if record.get("type") == "A":
                    assert cache_id4 is None and cache_address4 is None
                    cache_id4 = record.get("id")
                    cache_address4 = record.get("data")
                elif record.get("type") == "AAAA":
                    assert cache_id6 is None and cache_address6 is None
                    cache_id6 = record.get("id")
                    cache_address6 = record.get("data")
    except FileNotFoundError:
        pass
    except json.decoder.JSONDecodeError:
        pass

    current_address4 = None
    # uncomment to enable updating of an A record
    # This line obtains a publicly-visible ipv4 address
    # current_address4 = requests.get("https://api.ipify.org").content.decode("utf8")
    try:
        # Attempt to connect to an external host using ipv6 and then get the socket's IP address
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.connect((ipv6_external_address, 1))
        current_address6 = sock.getsockname()[0]
    except OSError:
        current_address6 = None

    # If there is no cached record ID for the prefix, query dynv6 and look for a match
    update4 = cache_id4 is None and current_address4 is not None
    update6 = cache_id6 is None and current_address6 is not None
    if update4 or update6:
        records = requests.get(
            f"{DYNV6_PREFIX}/{zone_id}/records",
            headers=headers,
        ).json()
        for record in records:
            if record.get("name") == prefix:
                if update4 and record.get("type") == "A":
                    cache_address4 = record["data"]
                    cache_id4 = record["id"]
                elif update6 and record.get("type") == "AAAA":
                    cache_address6 = record["data"]
                    cache_id6 = record["id"]

    records = []
    results = []

    if current_address4 is not None:
        if cache_address4 == current_address4:
            print(f"Address unchanged: {current_address4}")
        records.append({"id": cache_id4, "type": "A", "name": prefix, "data": current_address4})
    if current_address6 is not None:
        if cache_address6 == current_address6:
            print(f"Address unchanged: {current_address6}")
        records.append(
            {
                "id": cache_id6,
                "type": "AAAA",
                "name": prefix,
                "data": current_address6,
            }
        )

    for record in records:
        if record["id"] is None:
            print(f"Creating a new record: {record}")
            result = requests.post(
                f"{DYNV6_PREFIX}/{zone_id}/records",
                headers=headers,
                params=record,
            )
            if result.status_code != 200:
                print(f"Error creating a new record: {result} ({result.reason})", file=sys.stderr)
                continue
            record["id"] = result.json().get("id")
            print(record)
        else:
            # PATCH
            print(f"Updating an existing record ({record['id']})")
            result = requests.patch(
                f"{DYNV6_PREFIX}/{zone_id}/records/{record['id']}",
                headers=headers,
                params=record,
            )
            if result.status_code != 200:
                print(f"Error updating a record: {result}", file=sys.stderr)
                continue
            result_id = result.json().get("id")
            if result_id:
                if record["id"] == result_id:
                    print(f"Successfully updated {record['id']}: {record['data']}")
                else:
                    print(
                        f"Error! Attempted to update record {record['id']}"
                        f" but updated {result_id} instead."
                    )
            else:
                print(
                    f"Error updating record {record['id']}: {result} ({result.json()})",
                    file=sys.stderr,
                )
        results.append(record)

    with open(ZONE_FILE, "w", encoding="utf8") as zone_file:
        zone_data = {"id": zone_id}
        if zone:
            zone_data["name"] = zone
        json.dump(zone_data, zone_file)
        print("", file=zone_file)

    with open(RECORDS_FILE, "w", encoding="utf8") as records_file:
        json.dump(results, records_file)
        print("", file=records_file)


if __name__ == "__main__":
    main()
