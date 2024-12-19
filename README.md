This program is intended for use in a crontab to update dynv6 records with current IP addresses.

To run it, you will need the following information in files in this directory:
- The hostname of your record; if your dynv6 zone is `dom.ain` and the record you want to update is
  `your.dom.ain`, this should be `your`. It should be stored in a file named `.hostname`.
- The ID of your zone in `.zone`. See [the API
  docs](https://dynv6.github.io/api-spec/#tag/zones/operation/findZones) for instructions on getting
  your zone ID. At some point, I hope to automate this.
- An authorization (HTTP) token in `.token`. You can generate these from the drop-down menu for your
  account on dynv6.com and selecting `Keys`.

The script attempts to minimize the load on dynv6.com by storing a cache of records information in
`.records`. If there is no relevant information in `.records`, it will first attempt to retrieve
information from dynv6. It sends new records or updates only as needed.

I created a cron entry in `/etc/cron.hourly/dynv6` with contents like the following:

    #!/usr/bin/sh
    python3 /path/to/update_records.py 2>&1 | tee -a /path/to/log
