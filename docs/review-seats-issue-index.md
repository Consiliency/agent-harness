# Review seats issue index

This index gives every issue and PR named in `specs/phase-plans-seats-v1.md` one owning
exit criterion, or records it as a reference or out of scope. It is rendered from
`plans/evidence/seat-inventory/index.json`, bound to roadmap SHA-256
`1c9e2d40089c5f70b23ff6233ad06da3d8edcd69e643681bdc342e76298ca0c0`.

Exit criteria are cited by ID; the roadmap is authoritative for their text. Other exit
criteria may cite an item they do not own. An item has more than one row only where the
roadmap itself separates parts.

## Ownership

| Identifier | Part | Kind | Owning EC | Rationale | Links |
| --- | --- | --- | --- | --- | --- |
| agent-harness#826 | whole | reference | — | Cited as the source of the standing no-silence-kill policy under OD-11. | [826](https://github.com/Consiliency/agent-harness/issues/826) |
| agent-harness#848 | whole | owned | EC-INVENTORY-4 | The proposal issue this phase marks superseded. | [848](https://github.com/Consiliency/agent-harness/issues/848) |
| agent-harness#896 | whole | owned | EC-INVENTORY-6 | Carries the retirement record for its SSH-first follow-on plans. | [896](https://github.com/Consiliency/agent-harness/issues/896) |
| agent-harness#941 | whole | owned | EC-CODEX-1 | Listed for expected closure by the CODEX phase. | [941](https://github.com/Consiliency/agent-harness/issues/941) |
| agent-harness#1003 | whole | owned | EC-CODEX-1 | Listed for expected closure by the CODEX phase. | [1003](https://github.com/Consiliency/agent-harness/issues/1003) |
| agent-harness#1091 | whole | owned | EC-GROK-2 | Named by this EC for the Grok phase. | [1091](https://github.com/Consiliency/agent-harness/issues/1091) |
| agent-harness#1108 | whole | owned | EC-TEAMHOST-2 | Named by this EC for the team-host phase. | [1108](https://github.com/Consiliency/agent-harness/issues/1108) |
| agent-harness#1132 | whole | owned | EC-CLOSEOUT-3 | Closes at CLOSEOUT, citing the readiness matrix. | [1132](https://github.com/Consiliency/agent-harness/issues/1132) |
| agent-harness#1170 | whole | reference | — | Closed; cited as a named case by EC-REMOTE-5. | [1170](https://github.com/Consiliency/agent-harness/issues/1170) |
| agent-harness#1244 | seats-v1-matrix | owned | EC-CLOSEOUT-3 | Standing rule; receives the readiness matrix at CLOSEOUT. | [1244](https://github.com/Consiliency/agent-harness/issues/1244) |
| agent-harness#1244 | per-os-jails | out_of_scope | — | Stays open for the per-OS jails, a roadmap non-goal. | [1244](https://github.com/Consiliency/agent-harness/issues/1244) |
| agent-harness#1250 | whole | owned | EC-CLOSEOUT-4 | Sunset carried out under OD-8. EC-JAILCORE-2 cites it as precedent. | [1250](https://github.com/Consiliency/agent-harness/issues/1250) |
| agent-harness#1254 | whole | owned | EC-CLAUDE-7 | Absorbed at CLAUDE phase level; login-wait scope fits this EC. | [1254](https://github.com/Consiliency/agent-harness/issues/1254) |
| agent-harness#1255 | whole | owned | EC-CLAUDE-7 | Named by this EC for the CLAUDE phase. | [1255](https://github.com/Consiliency/agent-harness/issues/1255) |
| agent-harness#1282 | whole | reference | — | Closed PR; cited as a falsifier source by EC-JAILCORE-2. | [1282](https://github.com/Consiliency/agent-harness/pull/1282) |
| agent-harness#1287 | whole | owned | EC-JAILCORE-4 | Named by this EC for the qualification key. | [1287](https://github.com/Consiliency/agent-harness/issues/1287) |
| agent-harness#1288 | whole | owned | EC-CLOSEOUT-3 | Closes at CLOSEOUT. EC-JAILCORE-2 also cites it. | [1288](https://github.com/Consiliency/agent-harness/issues/1288) |
| agent-harness#1289 | whole | owned | EC-GROK-5 | Named by this EC for the Grok phase. | [1289](https://github.com/Consiliency/agent-harness/issues/1289) |
| agent-harness#1335 | whole | owned | EC-CODEX-4 | Listed for expected closure by the CODEX phase; this EC is its reproduction proof. | [1335](https://github.com/Consiliency/agent-harness/issues/1335) |
| agent-harness#1357 | whole | owned | EC-TEAMHOST-3 | Named by this EC for the team-host phase. | [1357](https://github.com/Consiliency/agent-harness/issues/1357) |
| agent-harness#1391 | jailed-scope | owned | EC-CLAUDE-6 | Absorbed at CLAUDE phase level; default-route scope fits this EC. | [1391](https://github.com/Consiliency/agent-harness/issues/1391) |
| agent-harness#1391 | solo-runner | out_of_scope | — | The solo-runner SDK rollout re-files here, a roadmap non-goal. | [1391](https://github.com/Consiliency/agent-harness/issues/1391) |
| agent-harness#1398 | whole | owned | EC-TEAMHOST-3 | Named by this EC for doctor reporting. | [1398](https://github.com/Consiliency/agent-harness/issues/1398) |
| agent-harness#1399 | whole | owned | EC-TEAMHOST-3 | Named by this EC for the fix text. | [1399](https://github.com/Consiliency/agent-harness/issues/1399) |
| agent-harness#1413 | whole | owned | EC-TEAMHOST-1 | Named by this EC for the team-host phase. | [1413](https://github.com/Consiliency/agent-harness/issues/1413) |
| agent-harness#1419 | whole | owned | EC-FIRSTSEAT-5 | Named by this EC for the FIRSTSEAT phase. | [1419](https://github.com/Consiliency/agent-harness/issues/1419) |
| agent-harness#1420 | whole | owned | EC-TEAMHOST-7 | Named by this EC for agy qualification. | [1420](https://github.com/Consiliency/agent-harness/issues/1420) |
| agent-harness#1422 | whole | owned | EC-CLAUDE-1 | Absorbed at CLAUDE phase level; launch-admission scope fits this EC. | [1422](https://github.com/Consiliency/agent-harness/issues/1422) |
| agent-harness#1460 | whole | owned | EC-GROK-1 | Named by this EC for the Grok phase. | [1460](https://github.com/Consiliency/agent-harness/issues/1460) |
| agent-harness#1461 | whole | owned | EC-CLAUDETUI-1 | Diagnosis lands here. EC-CLAUDE-5 only measures the same failure mode. | [1461](https://github.com/Consiliency/agent-harness/issues/1461) |
| agent-harness#1472 | whole | owned | EC-CODEX-4 | CODEX lane C carries the probe work; qualification proves it. | [1472](https://github.com/Consiliency/agent-harness/issues/1472) |
| agent-harness#1479 | whole | owned | EC-TEAMHOST-5 | Named by this EC for doctor reporting. | [1479](https://github.com/Consiliency/agent-harness/issues/1479) |
| agent-harness#1480 | whole | owned | EC-CODEX-5 | Only EC that names it, including its recorded decision. | [1480](https://github.com/Consiliency/agent-harness/issues/1480) |
| agent-harness#1494 | whole | owned | EC-CLAUDE-7 | Absorbed at CLAUDE phase level; login-wait scope fits this EC. | [1494](https://github.com/Consiliency/agent-harness/issues/1494) |
| agent-harness#1520 | whole | owned | EC-TEAMHOST-5 | Named by this EC for agy reporting. | [1520](https://github.com/Consiliency/agent-harness/issues/1520) |
| agent-harness#1528 | whole | owned | EC-CODEX-2 | Named by this EC for the Codex login probe. | [1528](https://github.com/Consiliency/agent-harness/issues/1528) |
| agent-harness#1531 | whole | owned | EC-CLAUDE-7 | Absorbed at CLAUDE phase level; login-proof scope fits this EC. | [1531](https://github.com/Consiliency/agent-harness/issues/1531) |
| agent-harness#1532 | whole | owned | EC-CLAUDE-7 | Named by this EC for the CLAUDE phase. | [1532](https://github.com/Consiliency/agent-harness/issues/1532) |
| agent-harness#1555 | whole | reference | — | Closed PR; cited as the existing Gemini route. | [1555](https://github.com/Consiliency/agent-harness/pull/1555) |
| agent-harness#1585 | whole | owned | EC-CLAUDE-7 | Absorbed at CLAUDE phase level; login-proof scope fits this EC. | [1585](https://github.com/Consiliency/agent-harness/issues/1585) |
| agent-harness#1602 | whole | out_of_scope | — | Lifecycle owned outside this roadmap. EC-TEAMHOST-7 consumes its pointer where one exists. | [1602](https://github.com/Consiliency/agent-harness/issues/1602) |
| agent-harness#1623 | whole | owned | EC-CLAUDETUI-1 | Draft closed by this EC after the split in the disposition table. EC-FIRSTSEAT-5 cites its resolver part. | [1623](https://github.com/Consiliency/agent-harness/pull/1623) [1652](https://github.com/Consiliency/agent-harness/pull/1652) |
| agent-harness#1641 | whole | owned | EC-CLAUDETUI-1 | Draft closed by this EC after salvage. | [1641](https://github.com/Consiliency/agent-harness/pull/1641) [1740](https://github.com/Consiliency/agent-harness/pull/1740) |
| agent-harness#1644 | whole | owned | EC-INVENTORY-3 | Draft closed by this phase under OD-2, with the OD-4 reopening condition. | [1644](https://github.com/Consiliency/agent-harness/pull/1644) |
| agent-harness#1652 | whole | reference | — | Closed PR; cited as the Grok allow-list route. | [1652](https://github.com/Consiliency/agent-harness/pull/1652) |
| agent-harness#1653 | codex | owned | EC-CODEX-3 | Codex vendor part. | [1653](https://github.com/Consiliency/agent-harness/issues/1653) |
| agent-harness#1653 | grok | owned | EC-GROK-3 | Grok vendor part. | [1653](https://github.com/Consiliency/agent-harness/issues/1653) |
| agent-harness#1682 | whole | owned | EC-CLAUDE-2 | Absorbed at CLAUDE phase level; print-route scope fits this EC. | [1682](https://github.com/Consiliency/agent-harness/issues/1682) |
| agent-harness#1686 | whole | owned | EC-GROK-1 | Named by this EC for the Grok phase. | [1686](https://github.com/Consiliency/agent-harness/issues/1686) |
| agent-harness#1704 | seat-side-interface | owned | EC-JAILCORE-2 | Acceptance item 3, for seats only, delivered by JAILCORE. | [1704](https://github.com/Consiliency/agent-harness/issues/1704) |
| agent-harness#1704 | package-extraction | out_of_scope | — | Extracting the sandbox code to its own package is a roadmap non-goal. | [1704](https://github.com/Consiliency/agent-harness/issues/1704) |
| agent-harness#1706 | whole | owned | EC-TEAMHOST-6 | Named by this EC for the Gemini follow-ups. | [1706](https://github.com/Consiliency/agent-harness/issues/1706) |
| agent-harness#1729 | whole | owned | EC-FIRSTSEAT-1 | Closes when this EC holds, not at CLOSEOUT. | [1729](https://github.com/Consiliency/agent-harness/issues/1729) |
| agent-harness#1731 | whole | owned | EC-INVENTORY-3 | Draft closed by this phase with agent-harness#1644. | [1731](https://github.com/Consiliency/agent-harness/pull/1731) [1644](https://github.com/Consiliency/agent-harness/pull/1644) |
| agent-harness#1740 | whole | owned | EC-CLAUDE-2 | Draft closed by this EC after the mine. | [1740](https://github.com/Consiliency/agent-harness/pull/1740) |
| agent-harness#1744 | whole | owned | EC-CLAUDE-3 | Draft closed by this EC after salvage. | [1744](https://github.com/Consiliency/agent-harness/pull/1744) |
| agent-harness#1774 | whole | owned | EC-CODEX-2 | Only EC that names it; covers the Codex launcher projection. | [1774](https://github.com/Consiliency/agent-harness/issues/1774) |
| agent-harness#1775 | whole | reference | — | Closed PR; cited as the decision-record section input. | [1775](https://github.com/Consiliency/agent-harness/pull/1775) |
| agent-harness#1781 | whole | out_of_scope | — | No action. Unrelated to seats; no hold claimed. | [1781](https://github.com/Consiliency/agent-harness/pull/1781) |
| agent-harness#1782 | whole | reference | — | Closed PR; cited as the projection contract. | [1782](https://github.com/Consiliency/agent-harness/pull/1782) |
| agent-harness#1787 | whole | owned | EC-REMOTE-4 | Named by this EC for the remote rung. | [1787](https://github.com/Consiliency/agent-harness/issues/1787) |
| agent-harness#1804 | whole | owned | EC-CLAUDENET-2 | Named by this EC for the Claude digest change. | [1804](https://github.com/Consiliency/agent-harness/issues/1804) |
| agent-harness#1819 | whole | reference | — | Closed PR; cited as the interim banner pattern. | [1819](https://github.com/Consiliency/agent-harness/pull/1819) |
| agent-harness#1821 | whole | owned | EC-FIRSTSEAT-3 | Closes when this EC holds, not at CLOSEOUT. | [1821](https://github.com/Consiliency/agent-harness/issues/1821) |
| agent-harness#1822 | whole | owned | EC-FIRSTSEAT-2 | Closes when this EC holds, not at CLOSEOUT. | [1822](https://github.com/Consiliency/agent-harness/issues/1822) |
| agent-harness#1823 | whole | owned | EC-FIRSTSEAT-3 | Closes when this EC holds, not at CLOSEOUT. | [1823](https://github.com/Consiliency/agent-harness/issues/1823) |
| agent-harness#1824 | whole | reference | — | Closed PR; cited for the registry status workaround. | [1824](https://github.com/Consiliency/agent-harness/pull/1824) |

## Split items

- agent-harness#1653 is partitioned by vendor: `codex` and `grok`, the two vendors the
  roadmap names for it.
- agent-harness#1391 separates the absorbed `jailed-scope` from the `solo-runner` route.
- agent-harness#1244 separates the `seats-v1-matrix` delivery from the `per-os-jails` non-goal.
- agent-harness#1704 separates the `seat-side-interface` from `package-extraction`.

## Outstanding records

`plans/evidence/seat-inventory/dispositions.json` holds the receipts. The disposition
comments, the Pi issue and the agent-harness#896 retirement comment are posted and
hash-checked. EC-INVENTORY-3 stays open until the four owner closures land in later phases.

| Record | Target | Owner | State |
| --- | --- | --- | --- |
| disposition comment | agent-harness#1740 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1740#issuecomment-6690192078) |
| owner closure | agent-harness#1740 | EC-CLAUDE-2 | pending (PR open) |
| disposition comment | agent-harness#1744 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1744#issuecomment-6690192495) |
| owner closure | agent-harness#1744 | EC-CLAUDE-3 | pending (PR open) |
| disposition comment | agent-harness#1641 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1641#issuecomment-6690192894) |
| owner closure | agent-harness#1641 | EC-CLAUDETUI-1 | pending (PR open) |
| disposition comment | agent-harness#1623 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1623#issuecomment-6690193407) |
| owner closure | agent-harness#1623 | EC-CLAUDETUI-1 | pending (PR open) |
| disposition comment | agent-harness#1644 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1644#issuecomment-6690193918) |
| phase closure | agent-harness#1644 | EC-INVENTORY-3 | closed |
| disposition comment | agent-harness#1731 | EC-INVENTORY-3 | [posted](https://github.com/Consiliency/agent-harness/pull/1731#issuecomment-6690194320) |
| phase closure | agent-harness#1731 | EC-INVENTORY-3 | closed |
| file issue | [Pi review-seat issue](https://github.com/Consiliency/agent-harness/issues/1854) | EC-INVENTORY-4 | filed as agent-harness#1854 |
| retirement comment | agent-harness#896 | EC-INVENTORY-6 | [posted](https://github.com/Consiliency/agent-harness/issues/896#issuecomment-6690196586) |

agent-harness#1781 takes no action. The proposal banner for agent-harness#848 is in place.

## Search census (non-blocking)

This appendix is informational and is not an exit criterion.

- Captured: 2026-11-06T15:57:20Z
- Query: `repo:Consiliency/agent-harness seat OR jail OR sandbox OR panel`
- Results: 539 issues and 536 pull requests, all in Consiliency/agent-harness
- Coverage: Two partitions (is:issue, is:pull-request) of the stated query, each under the API's 1,000-result limit and each reporting complete results. Fields are limited to number, repository, type and state. Matching is GitHub's own text search, so a match does not imply seat scope, and items created after the timestamp are absent.

Open matches not named in the roadmap (338) are listed below. The full census is in the evidence record.

agent-harness#248, agent-harness#352, agent-harness#353, agent-harness#358, agent-harness#359, agent-harness#369,
agent-harness#374, agent-harness#376, agent-harness#385, agent-harness#386, agent-harness#388, agent-harness#398,
agent-harness#401, agent-harness#405, agent-harness#428, agent-harness#438, agent-harness#439, agent-harness#442,
agent-harness#444, agent-harness#445, agent-harness#446, agent-harness#447, agent-harness#463, agent-harness#466,
agent-harness#478, agent-harness#497, agent-harness#525, agent-harness#554, agent-harness#561, agent-harness#567,
agent-harness#569, agent-harness#573, agent-harness#575, agent-harness#585, agent-harness#628, agent-harness#633,
agent-harness#638, agent-harness#639, agent-harness#642, agent-harness#648, agent-harness#655, agent-harness#657,
agent-harness#660, agent-harness#673, agent-harness#678, agent-harness#679, agent-harness#688, agent-harness#718,
agent-harness#720, agent-harness#730, agent-harness#733, agent-harness#734, agent-harness#735, agent-harness#743,
agent-harness#770, agent-harness#778, agent-harness#783, agent-harness#789, agent-harness#791, agent-harness#795,
agent-harness#802, agent-harness#806, agent-harness#808, agent-harness#817, agent-harness#820, agent-harness#831,
agent-harness#835, agent-harness#836, agent-harness#837, agent-harness#838, agent-harness#839, agent-harness#842,
agent-harness#843, agent-harness#844, agent-harness#845, agent-harness#851, agent-harness#852, agent-harness#854,
agent-harness#856, agent-harness#857, agent-harness#875, agent-harness#884, agent-harness#889, agent-harness#891,
agent-harness#895, agent-harness#897, agent-harness#898, agent-harness#899, agent-harness#900, agent-harness#902,
agent-harness#905, agent-harness#910, agent-harness#915, agent-harness#923, agent-harness#924, agent-harness#926,
agent-harness#927, agent-harness#930, agent-harness#934, agent-harness#945, agent-harness#962, agent-harness#965,
agent-harness#966, agent-harness#976, agent-harness#979, agent-harness#983, agent-harness#985, agent-harness#986,
agent-harness#988, agent-harness#989, agent-harness#1000, agent-harness#1006, agent-harness#1007, agent-harness#1008,
agent-harness#1011, agent-harness#1023, agent-harness#1039, agent-harness#1062, agent-harness#1063, agent-harness#1068,
agent-harness#1078, agent-harness#1082, agent-harness#1093, agent-harness#1097, agent-harness#1098, agent-harness#1099,
agent-harness#1104, agent-harness#1106, agent-harness#1107, agent-harness#1110, agent-harness#1112, agent-harness#1113,
agent-harness#1114, agent-harness#1123, agent-harness#1124, agent-harness#1129, agent-harness#1131, agent-harness#1137,
agent-harness#1143, agent-harness#1149, agent-harness#1150, agent-harness#1151, agent-harness#1153, agent-harness#1154,
agent-harness#1156, agent-harness#1167, agent-harness#1168, agent-harness#1171, agent-harness#1179, agent-harness#1180,
agent-harness#1182, agent-harness#1183, agent-harness#1184, agent-harness#1185, agent-harness#1186, agent-harness#1187,
agent-harness#1196, agent-harness#1197, agent-harness#1198, agent-harness#1199, agent-harness#1200, agent-harness#1203,
agent-harness#1206, agent-harness#1208, agent-harness#1216, agent-harness#1217, agent-harness#1218, agent-harness#1220,
agent-harness#1223, agent-harness#1227, agent-harness#1228, agent-harness#1235, agent-harness#1236, agent-harness#1242,
agent-harness#1243, agent-harness#1251, agent-harness#1252, agent-harness#1256, agent-harness#1258, agent-harness#1260,
agent-harness#1263, agent-harness#1271, agent-harness#1272, agent-harness#1273, agent-harness#1275, agent-harness#1278,
agent-harness#1290, agent-harness#1306, agent-harness#1321, agent-harness#1345, agent-harness#1346, agent-harness#1347,
agent-harness#1353, agent-harness#1358, agent-harness#1359, agent-harness#1362, agent-harness#1381, agent-harness#1405,
agent-harness#1407, agent-harness#1416, agent-harness#1417, agent-harness#1418, agent-harness#1423, agent-harness#1424,
agent-harness#1433, agent-harness#1434, agent-harness#1436, agent-harness#1437, agent-harness#1439, agent-harness#1440,
agent-harness#1443, agent-harness#1444, agent-harness#1447, agent-harness#1459, agent-harness#1462, agent-harness#1464,
agent-harness#1466, agent-harness#1471, agent-harness#1473, agent-harness#1474, agent-harness#1475, agent-harness#1477,
agent-harness#1478, agent-harness#1481, agent-harness#1482, agent-harness#1483, agent-harness#1484, agent-harness#1485,
agent-harness#1486, agent-harness#1487, agent-harness#1488, agent-harness#1490, agent-harness#1493, agent-harness#1495,
agent-harness#1496, agent-harness#1497, agent-harness#1498, agent-harness#1500, agent-harness#1501, agent-harness#1502,
agent-harness#1503, agent-harness#1505, agent-harness#1506, agent-harness#1507, agent-harness#1509, agent-harness#1510,
agent-harness#1511, agent-harness#1512, agent-harness#1513, agent-harness#1514, agent-harness#1515, agent-harness#1516,
agent-harness#1521, agent-harness#1522, agent-harness#1523, agent-harness#1524, agent-harness#1525, agent-harness#1526,
agent-harness#1527, agent-harness#1530, agent-harness#1533, agent-harness#1534, agent-harness#1535, agent-harness#1536,
agent-harness#1538, agent-harness#1539, agent-harness#1540, agent-harness#1542, agent-harness#1543, agent-harness#1544,
agent-harness#1546, agent-harness#1556, agent-harness#1579, agent-harness#1580, agent-harness#1582, agent-harness#1589,
agent-harness#1590, agent-harness#1604, agent-harness#1613, agent-harness#1619, agent-harness#1624, agent-harness#1632,
agent-harness#1634, agent-harness#1639, agent-harness#1640, agent-harness#1642, agent-harness#1643, agent-harness#1668,
agent-harness#1669, agent-harness#1672, agent-harness#1673, agent-harness#1674, agent-harness#1675, agent-harness#1677,
agent-harness#1681, agent-harness#1683, agent-harness#1696, agent-harness#1702, agent-harness#1703, agent-harness#1705,
agent-harness#1707, agent-harness#1710, agent-harness#1711, agent-harness#1712, agent-harness#1713, agent-harness#1714,
agent-harness#1715, agent-harness#1716, agent-harness#1717, agent-harness#1718, agent-harness#1719, agent-harness#1722,
agent-harness#1723, agent-harness#1724, agent-harness#1725, agent-harness#1726, agent-harness#1734, agent-harness#1746,
agent-harness#1754, agent-harness#1755, agent-harness#1766, agent-harness#1770, agent-harness#1777, agent-harness#1779,
agent-harness#1780, agent-harness#1788, agent-harness#1789, agent-harness#1790, agent-harness#1791, agent-harness#1792,
agent-harness#1793, agent-harness#1795, agent-harness#1797, agent-harness#1818, agent-harness#1825, agent-harness#1832,
agent-harness#1845, agent-harness#1846
