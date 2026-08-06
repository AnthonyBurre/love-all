"""Live tournament data for the Pages site: the swappable source adapter (ESPN),
bracket ordering, and player-name matching to the Match Charting universe."""

# Every outbound request identifies the project the way a bot-policy filter expects:
# product/version plus a contact URL. A bare token is refused with a 403 by ESPN's edge,
# which is indistinguishable from an outage at the call site.
#
UA = "love-all/0.1 (https://github.com/anthonyburre/love-all)"
