# Row-window grant pins (K-1 contract §8). Literals only: the kit parses this file's AST
# before use and refuses anything but exactly one assignment to each name below. Each pin is
# (grant_sha256, packet_sha256, approved_until). A reviewed change that touches only this
# file sets a pin, so release_identity() does not move. Retired pins serve verification only.
ROW_GRANTS = {}
RETIRED_ROW_GRANTS = {}
