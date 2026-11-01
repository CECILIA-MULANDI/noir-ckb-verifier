# Private tally v2 setup ceremony

**Complete.** Final key `tally_final.zkey` (SHA-256 `01f76014a6fbad1a0433781aa6518ec36fea27536e71354d88f134bc04a180fe`), verification key `verification_key.json` (SHA-256 `7749a5fbdb778598ac514441f374c89a1890ce0e1e00cf34e8465891f69b5055`).

Every key below was checked with `snarkjs zkey verify` against the frozen
circuit and the phase 1 file before it was accepted. Anyone can repeat the whole
check: `python3 -B scripts/ceremony-private-tally.py check` (or the manual
commands in the [contributor guide](../../docs/setup-ceremony.md#verifying-the-ceremony-yourself)).

| Item | Value |
| --- | --- |
| Circuit | `circuits/private-tally-v2` at commit `774aafdad1d8d56f589509890d1920a7e762157e` |
| R1CS | `circuit.r1cs`, SHA-256 `5bd9cf5e4c3ffec727ac298b055feb0518f213418aaee9694ea388841b59dcef`, 3338 constraints |
| Phase 1 | `ppot_0080_12.ptau` from [PSE Perpetual Powers of Tau](https://github.com/privacy-ethereum/perpetualpowersoftau#prepared-and-truncated-files), BLAKE2b-512 `3ee85ae13672d1d742117566126f31d678cf72d480f0df8e2aec78d77771433392ae01bb2b11c4ea0e60b244415be0a12a02e51d3f7a4a8b5c1c982fa208c4cd` (not stored here) |
| Initial key | `zkeys/tally_0000.zkey`, SHA-256 `fae8844ba9ae7dbf43acc9c20d13aa56d995dac42765d67de7b5028be4f125e2` |
| Tool | snarkjs 0.7.5 |
| Beacon | CKB mainnet block **20870000**, announced before the first contribution. Applied with `snarkjs zkey beacon … <block hash> 10`. Block hash: `0x0734b3f08b5e78144c73a58313647a94f053223d8b71ae17ed18cf3140dbb44d`. |

## Contributions

| # | Contributor | Input key SHA-256 | Contribution hash | Attestation | Key |
| --- | --- | --- | --- | --- | --- |
| 1 | Xiaomao | `fae8844ba9ae7dbf…` | `b00a21cf520183f0…` | [link](https://x.com/nellycyberpro/status/2112485476976431408) | `tally_0001.zkey` |
| 2 | truthixify | `a3c80a9886eb2e3b…` | `1f06854b054d584b…` | — | `tally_0002.zkey` |
| 3 | alienate | `8304e36ee8826f4c…` | `707e9bd622e8cbb2…` | — | `tally_0003.zkey` |
| 4 | CECILIA-MULANDI | `af7c36e723a41516…` | `136116c8a5e84f8b…` | — | `tally_0004.zkey` |

This is a public ceremony for a testnet developer preview, not an audited
production ceremony. It guarantees that nobody can forge private tally proofs as
long as at least one contributor's randomness was discarded.
