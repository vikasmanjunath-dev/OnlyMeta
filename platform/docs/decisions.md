# Open decisions for the team (settle at hour 1.5, before anyone builds against the contract)

1. **Pseudonyms vs the dependency map.** The SaaS only sees `node_pseudonym`, but `contracts/dependency_map.yaml` is keyed by logical node labels (`app-01`, `db-01`). Options:
   - **(A, assumed)** Pseudonym = HMAC(tenant_key, *logical label*). The tenant registers its topology (labels only, no FQDNs); the SaaS holds the per-tenant key and derives pseudonyms for the labels in the map. Real FQDNs and IPs never leave.
   - (B) The collector sends the dependency map already expressed in pseudonyms at registration. Safer (SaaS never holds the key) but needs a registration call.
   Decide before P3 writes correlation.
2. **Organizer stream format.** `contracts/sample_stream.jsonl` is our assumed raw format. When the real spec arrives only `collector/adapter.py` changes; the schema does not.
3. **Offline threshold.** 30 s (target is 60 s). If the stream interval is slower use max(30 s, 4 x interval), still under 60 s.
4. **Plan length.** Playbook is a 15-hour build inside the 24-hour event; hours 15–24 are buffer and judging slots.
