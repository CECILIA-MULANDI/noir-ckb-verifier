# Private tally v2 on CKB testnet

Profile `noir-ckb/private-tally/v2` ([design](../docs/private-tally-v2-spec.md)),
deployed with the verification key from the
[public setup ceremony](../ceremony/private-tally-v2/) (four contributions plus
the beacon of CKB mainnet block 20,870,000). Machine-readable record:
[`private-tally-testnet/deployment.json`](private-tally-testnet/deployment.json).
Host: macOS ARM64.

## Ceremony key as the proving setup (4 November 2026)

`scripts/setup-private-tally.py --ceremony ceremony/private-tally-v2` replaced
the development setup with the ceremony's final key. The run (status `passed`,
leak scan clean):

- rebuilt the circuit with the pinned backend and Nargo 1.0.0-beta.18 and
  obtained the frozen R1CS (`5bd9cf5e…`);
- checked `tally_final.zkey` (`01f76014…`) and `verification_key.json`
  (`7749a5fb…`) against the transcript, and the phase 1 file against its BLAKE2b
  hash;
- passed `snarkjs zkey verify`, and the key exported exactly the published
  verification key;
- proved a creation and an update with fresh secrets, rejected all 8 altered
  public inputs, and converted the key and proof with the adapter.

The full local lifecycle then ran with this setup on a loopback CKB 0.210.0
chain (`local-private-tally.py --full`), status **`local-validated`**: deploy,
create, update +7, cover update +0, final value and state versions matched,
**49 of 49** CKB-VM matrix cases and **4 of 4** mutations as required, all with
`ceremony.zkey`.

## Release

| Artifact | Bytes | Data hash |
| --- | --- | --- |
| Type Script (`private-tally`, testnet network domain) | 113,464 | `0x3cc448db51cdc14453fff7bdf2c3d39e1dd7a238091b982069d20e169e8337d1` |
| Verification key (Molecule, from the ceremony key) | 430 | `0x91ad18ee79bb03a2702545bf4a8d095189139dfa9d320fcf047a33fce5912e5b` |
| Guard Lock code (always-success) | 7,184 | `0xe683b04139344768348499c23eb1326d5a52d6db006c0d2fece00a831f3660d7` |

The release is marked as a ceremony release (`development_only: false`) and
records the ceremony's final hashes.

## Testnet transactions (5 November 2026)

| Stage | Transaction | Result |
| --- | --- | --- |
| Deploy Type Script, verification key and guard code | [0x39ef90b8…47b1f9](https://testnet.explorer.nervos.org/transaction/0x39ef90b8e6a882af3a658dc5c01cf17476e39907741541358d7155954547b1f9) | Committed; the three live Cells matched the release byte for byte |
| Create at 0 | [0x58d64623…6eca67](https://testnet.explorer.nervos.org/transaction/0x58d646231e2dfc66f3cf2d07199ad6863e733489342b811c5473e223be6eca67) | Proof re-checked after signing; committed; live Cell checked; state version 1 |
| Update by a hidden amount | [0xa93b9ed5…1c4a73](https://testnet.explorer.nervos.org/transaction/0xa93b9ed57c45ca3a031b92b1e0bf68851796c2eb3aabdcab61a14383ca1c4a73) | Same; state version 2 |
| Cover update (+0) | [0xbc062ecc…66046c](https://testnet.explorer.nervos.org/transaction/0xbc062ecc84515e573a5c723f36b081733b8d95c71fb15ef7e414ee2ad766046c) | Same; new commitment, unchanged value; state version 3 |

The deployment was funded from two plain Cells of the deployer account. The
client's `prepare-deploy` accepts several funding Cells and refuses any Cell
with data or a Type, so the existing owned-counter deployment Cells held by the
same account could not be spent.

Each update consumed the previous tally Cell and produced a new one with the
same capacity (200 CKB) under the guard Lock. On chain, each update shows only a
new commitment and a proof; the amount added is not visible, and the cover
update is indistinguishable from an update that adds a value.

## Join path (5 November 2026)

`scripts/join-private-tally.py init` lets a participant use this deployment
without deploying anything. Given the participant's own `--ceremony` setup, it
checked that the RPC is CKB testnet, that the three live Cells match the public
record, that the live verification key is byte for byte the key the
participant's setup derived from the ceremony key, and that the guard code
equals the local `ckb-always-success-script` 0.0.1 crate. It then wrote the
release and deployment files used by `private-tally-client.py`.

A second, separate testnet account then created its own tally through this path,
with its own secret key, and added a hidden amount to it:

| Stage | Transaction | Result |
| --- | --- | --- |
| Create at 0 | [0x86e7f5c9…26fe71](https://testnet.explorer.nervos.org/transaction/0x86e7f5c9d64f0a0a1db8d4e893cc115ab6cc9b84630962c6718b00d94226fe71) | Proof re-checked after signing; committed; state version 1 |
| Update by a hidden amount | [0x5b2d128d…29caff](https://testnet.explorer.nervos.org/transaction/0x5b2d128dab1f3b888f2cc98b2fa844dc67b1e9eec24eeeee354da6bcd029caff) | Same; state version 2; the private state's value matched the amount added |

Participant guide: [Try the private tally](../docs/try-the-private-tally.md).

## Limits

- Both accounts belong to the deployer. No outside participant has used this
  deployment yet.
- The join path checks the deployed Type Script bytes against the public record;
  it does not rebuild them from source.
- The ceremony is a public developer-preview ceremony, not an audited
  production setup.
- One tally Cell's updates are linkable to each other; update count, timing and
  fee payer are visible. Losing the private folder freezes the tally.
