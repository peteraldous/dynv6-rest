import datetime
import json
import requests
import socket
import sys

from pathlib import Path


ROOT = Path(__file__).parent
# To get the host's ipv6 address, we have to connect to something. This is a Google public DNS
# server.
IPV6_EXTERNAL_ADDRESS = "2001:4860:4860:0:0:0:0:8888"
# TODO consider making this command-line arguments
RECORDS_FILE = ROOT / ".records"
TOKEN_FILE = ROOT / ".token"
HOSTNAME_FILE = ROOT / ".hostname"
ZONE_FILE = ROOT / ".zone"

# TODO change so that an empty hostname updates the zone instead of a record


def read_file(filename, tag):
    """Read the contents of `filename` and return them. Exit with an error if
    the file does not exist."""
    try:
        with open(filename, "r", encoding="utf8") as input_file:
            return input_file.readline().strip()
    except FileNotFoundError:
        print(f"Please provide {tag} in `{TOKEN_FILE}`", file=sys.stderr)
        sys.exit()


def main():
    print(f"dynv6 update script {datetime.datetime.now(datetime.UTC)}")
    token = read_file(TOKEN_FILE, "an authorization token")
    hostname = read_file(HOSTNAME_FILE, "a hostname")
    zone_id = read_file(ZONE_FILE, "a zone ID")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    ipv4_record = None
    ipv6_record = None
    ipv4_record_address = None
    ipv6_record_address = None
    try:
        with open(RECORDS_FILE, "r", encoding="utf8") as state:
            contents = json.load(state)
            for record in contents:
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

    if ipv4_record is None or ipv6_record is None:
        records = requests.get(
            f"https://dynv6.com/api/v2/zones/{zone_id}/records",
            headers=headers,
        ).json()
        for record in records:
            if record.get("name") == hostname:
                if record.get("type") == "A":
                    ipv4_record_address = record["data"]
                    ipv4_record = record["id"]
                elif record.get("type") == "AAAA":
                    ipv6_record_address = record["data"]
                    ipv6_record = record["id"]

    current_ipv4_address = None
    # uncomment to enable updating of an A record
    # current_ipv4_address = requests.get("https://api.ipify.org").content.decode("utf8")
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.connect((IPV6_EXTERNAL_ADDRESS, 1))
        current_ipv6_address = sock.getsockname()[0]
    except OSError:
        current_ipv6_address = None

    records = []

    if current_ipv4_address is not None:
        records.append(
            (
                ipv4_record,
                ipv4_record_address,
                {"type": "A", "name": hostname, "data": current_ipv4_address},
            )
        )
    if current_ipv6_address is not None:
        records.append(
            (
                ipv6_record,
                ipv6_record_address,
                {"type": "AAAA", "name": hostname, "data": current_ipv6_address},
            )
        )

    results = []

    for record_id, address, record in records:
        if record_id is None:
            print(f"Creating a new record: {record}")
            result = requests.post(
                f"https://dynv6.com/api/v2/zones/{zone_id}/records",
                headers=headers,
                params=record,
            )
            print(result)
            record["id"] = result.json().get("id")
            print(record)
        elif address != record["data"]:
            # PATCH
            print(f"Updating an existing record ({record_id})")
            result = requests.patch(
                f"https://dynv6.com/api/v2/zones/{zone_id}/records/{record_id}",
                headers=headers,
                params=record,
            )
            result_id = result.json().get("id")
            if result_id:
                if record_id == result_id:
                    print(f"Successfully updated {record_id}")
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
