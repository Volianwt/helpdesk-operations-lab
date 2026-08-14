# Windows Network Connectivity Triage

## Intake

Confirm whether one user, one room, one VLAN, or the broader site is affected. Record the exact error, connection type, recent changes, device asset tag, and whether another service works.

## Safe Tier 1 checks

1. Check the service-status channel and known-issue list before changing the endpoint.
2. Confirm Wi-Fi/Ethernet state, airplane mode, cable or dock connection, and link lights.
3. Capture `ipconfig /all`; look for a valid address, gateway, DNS servers, and an unexpected `169.254.x.x` address.
4. Test the local gateway, a known IP address, and then a hostname to separate local, routing, and DNS failures.
5. Use `nslookup` or `Resolve-DnsName` to compare name-resolution results.
6. Renew DHCP only when policy permits and disruption has been explained to the user.
7. Document every test and result. Confirm service restoration with the user.

## Escalate when

Multiple users are affected, the switch or access point appears unavailable, privileged network changes are required, the endpoint repeatedly loses its lease, or the SLA/security threshold is approaching.
