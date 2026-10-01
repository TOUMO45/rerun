"""Phase D product surface (passports, REPLAY, dashboard): offline, built from committed records only.

Nothing in this package imports the harness (`backend/app`, `scripts`) or opens a network connection.
It lives outside the sealed harness paths, so harness-v1.3.4 stays byte-identical to its tag.
"""
