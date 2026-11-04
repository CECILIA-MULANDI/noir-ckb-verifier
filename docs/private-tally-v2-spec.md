# Private tally v2 — draft specification

Status: **implemented and deployed on CKB testnet** with the verification key
from the public setup ceremony; circuit, setup, secret handling, Type Script
CKB-VM matrix, mutation tests, client, local lifecycle on macOS and Linux, and a
testnet lifecycle (see [testnet evidence](../evidence/private-tally-testnet.md)).
Circuit: [`circuits/private-tally-v2/`](../circuits/private-tally-v2/). Profile `noir-ckb/private-tally/v2`
is a new, separate application. It does not change `owned-counter/v1`, its
deployment or its evidence. Feasibility results that informed this draft are in
[portable evidence](../evidence/week-15-portable.md) (private tally spike).

## 1. Purpose and statement

A Cell holds a hidden tally: a 64-bit value committed with fresh randomness on
every update. Whoever knows a secret key can increase the tally by a hidden
amount, including zero. **The proof is the authority:** no signature is
required to update the application Cell; the Type Script accepts a transition
only with a valid proof bound to that exact transition.

For an update the proof states:

> I know `(value_old, r_old, key, delta, r_new)` such that
> `c_old = C(value_old, r_old, key)`, `c_new = C(value_old + delta, r_new, key)`,
> `0 ≤ delta ≤ MAX_DELTA`, `value_old + delta < 2^64`, and this proof is for the
> operation whose context digest is `(ctx_lo, ctx_hi)`.

For creation (`c_old = 0`) it states that `c_new` commits to value 0 under some
key, with `delta = 0`.

Why the proof matters here, unlike in v1: the Type cannot check a hidden
transition itself, and with no signature, the context binding is the only thing
that stops a proof observed in the mempool from authorizing a different
transition.

## 2. Commitment

```text
inner = Poseidon2([TAG_INNER, r, key])        // 3 inputs
C(v, r, key) = Poseidon2([TAG_STATE, v, inner])  // 3 inputs
```

- Poseidon2 sponge from `noir-lang/poseidon` v0.2.6
  (`00f879180a56720169cff92a56778d40678d8e26`), pinned. **Every call takes at
  most 3 inputs**; v0.2.6 retains a stale-cache bug for longer inputs (fixed in
  v0.4.0, which does not compile on Noir beta.18). A test must fail the build if
  any longer call appears.
- `TAG_STATE`, `TAG_INNER`: distinct domain tags, defined as the big-endian
  integer of the ASCII strings `noir-ckb:tally:v2:state` and
  `noir-ckb:tally:v2:inner` (both below the BN254 scalar modulus).
- `r` and `key` are uniformly random BN254 scalars from a CSPRNG, generated
  locally by the client. User-typed or imported low-entropy values are refused.
- Hiding relies on fresh `r` per state; binding relies on Poseidon2 collision
  resistance. `0` is reserved as the creation sentinel and is never a valid
  stored commitment.

## 3. Circuit

Private first, then public (the layout the Week 14 backend correction covers):

```text
private: value_old, r_old, key, delta, r_new
public:  c_old, c_new, ctx_lo, ctx_hi
```

Constraints:

1. `value_old`, `delta` fit in 64 bits.
2. If `c_old == 0`: `value_old == 0` and `delta == 0` (creation).
   Else: `C(value_old, r_old, key) == c_old` and `delta` fits in 32 bits
   (that is, `delta ≤ MAX_DELTA`).
3. `value_new = value_old + delta` fits in 64 bits; `c_new ≠ 0`;
   `C(value_new, r_new, key) == c_new`.
4. `ctx_lo`, `ctx_hi` fit in 128 bits.

Range checks use `Field::assert_max_bit_size`, the standard library method for
constraining a field element to a bit width. The commitment and domain tags live
in a shared library package (`commitment`) used by both the circuit and a
`commit-helper` package that prints commitments for off-circuit tools, so the
tags are defined once.

`MAX_DELTA = 2^32 − 1` (decided: no application-specific cap in this demo profile;
a real application sets its own cap in its own profile). Measured on 16 October 2026 with the pinned backend: **3,338 constraints**,
5 private and 4 public inputs. The Hermez power-12 Powers of Tau file
(up to 4,096) fits; power 13 is needed only if the circuit grows past about
4,090 constraints.

## 4. Cells

Application Cell:

| Field | Value |
| --- | --- |
| capacity | chosen at creation; never changes; **permanently locked** (no withdrawal or destruction) |
| lock | the pinned **guard Lock**: always-success code by data hash, `hash_type = data1`, empty args |
| type | private tally Type, `hash_type = data1`, args = `0x01 ‖ type_id(32)` |
| data | `0x01 ‖ commitment` (33 bytes; commitment little-endian, canonical `< p`, non-zero) |

The guard Lock performs no authorization by design. Every consumption of the
Cell runs the Type, which requires a successor and a valid bound proof, so the
Lock cannot be used to move capacity or change state. The Type pins the guard
Lock so a tally cannot be created or moved under a different Lock.

Dependencies (code by data hash, one each): Type binary, verification key Cell,
guard Lock binary. Owner-controlled dependency Cells must stay live for the
application to remain usable (as in v1).

## 5. Context digest and public input

```text
digest = blake2b_256(ckb-default-hash,
    "noir-ckb/private-tally/context/v2\0"
  ‖ network_domain(32)            // genesis hash, compiled into the Type
  ‖ blake2b_256("noir-ckb/private-tally/v2")
  ‖ type_script_hash(32)
  ‖ type_id(32)
  ‖ action(1)                      // 0 create, 1 update
  ‖ consumed_outpoint(36)          // 36 zero bytes on create
  ‖ c_old(32) ‖ c_new(32)          // little-endian field elements
  ‖ successor_lock_hash(32)
  ‖ capacity(8, LE))
ctx_lo = digest[0..16] (LE u128), ctx_hi = digest[16..32]
```

Public vector, as encoded for the verifier: `u32 count = 4`, then `c_old`,
`c_new`, `ctx_lo`, `ctx_hi` as 32-byte little-endian field elements. The Type
builds this vector from the actual transaction and compares it byte for byte
with the proof payload before verifying.

The digest deliberately excludes fee inputs and change. Consequence: someone
who copies a pending update can resubmit the **same** transition paid with their
own fee Cell. That is griefing at their own expense; the resulting state is
exactly the one the key holder authorized.

## 6. Type Script rules

Cheap checks first, Groth16 verification last:

1. Args: 33 bytes, version byte `0x01`, `hash_type = data1`.
2. Shape: at most one tally input, exactly one tally output, one Cell per group;
   input/output/dependency counts bounded (as v1).
3. Type ID validation.
4. Successor Lock equals the pinned guard Lock (on update, input Lock too).
5. Successor data: 33 bytes, version `0x01`, commitment canonical and non-zero.
   On update, input data equally valid; capacity unchanged.
6. Exactly one dependency matching the pinned VK data hash.
7. Proof location: `WitnessArgs.input_type` of the group input on update;
   `WitnessArgs.output_type` of the group output's witness on create.
   The whole witness is bounded before parsing.
8. Expected public vector equals the payload's vector; then `verify`.

No destruction, transfer, withdrawal, upgrade or batching. A different
circuit, VK or rule set is a new profile and a new deployment.

## 7. Privacy: what is hidden and what is not

Hidden from observers: the tally value, each increment, the key, all blinding
factors, and whether an update added anything (delta = 0 updates are
indistinguishable from real ones).

Still visible:

- **Linkability.** The Type ID and the OutPoint chain link every update of one
  Cell. Fresh blinding makes the commitments look unrelated, but the Cell's
  history is public. Unlinkable updates need a shielded pool (commitment tree
  plus nullifiers); that is a different design.
- **Count, timing and an upper bound.** The number and timing of updates are
  public, so the value is at most `updates × MAX_DELTA`.
- **Fee payer.** Fee inputs and change reveal whoever pays. The client should
  use a fresh fee address per update; the application cannot hide L1 metadata.
- **No identity claim.** The proof shows knowledge of the key and a valid
  transition from a proven zero start, not who the holder is or why the tally
  matters. Statements about the tally to third parties (for example "at least
  N") are the planned v3 threshold proof.

## 8. Trusted setup

Soundness depends on the Groth16 setup; witness privacy is a separate property.

- Development (local runs): single-party setup is allowed and labelled as such.
- Before any testnet deployment of v2: phase 1 from a published BN254 Perpetual
  Powers of Tau transcript, verified by hash; phase 2 with at least two
  independently operated contributors plus a public random beacon; published
  transcript, R1CS hash, final zkey hash and VK hash, verifiable with
  `snarkjs zkey verify`. Soundness then holds if at least one contributor
  discarded their secret. This is still not an audited production ceremony.

Phase 2 procedure (sequential and asynchronous; contributors never meet or share
secrets):

1. Freeze the circuit. Any constraint change after this point voids the ceremony.
2. Coordinator: verify the phase 1 file hash, run `snarkjs groth16 setup` to
   produce the initial zkey, and publish the R1CS hash and initial zkey hash.
3. Coordinator: publicly announce the beacon source in advance, the hash of a
   named future CKB block that does not yet exist.
4. Each contributor in turn receives the latest zkey and its expected hash, runs
   `snarkjs zkey contribute <in> <out> --name=...`, returns the new file and
   publishes the printed contribution hash. The contribution secret exists only
   in memory during that command.
5. Coordinator runs `snarkjs zkey verify` (R1CS, phase 1 file, new zkey) after
   every contribution before passing it on, so files may travel over any channel.
6. After the beacon block exists: `snarkjs zkey beacon` with its hash, a final
   verify, VK export, and publication of the transcript (all hashes, contributor
   names, beacon block). Each contributor confirms their hash appears.

Planned participants (subject to their agreement): the maintainer as coordinator
and contributor, the author of the CKB Groth16 verifier, and the binding
reviewer. The contributor guide and the public procedure are in
[setup ceremony](setup-ceremony.md); file names and hashes are added when the
ceremony opens at D4.

## 9. Client and secret handling

- Generates `key` and every `r` locally; stores the state `(value, r, key)` in a
  0600 file inside a 0700 directory, never in logs, manifests or command records.
- Proving inputs and `.wtns` witnesses exist only in that private directory and
  are deleted immediately after proving.
- Command records keep arguments and exit codes; output of witness-handling
  steps is redacted.
- Every run ends with a leak scan of all kept files (decimal, hex, raw
  little/big-endian encodings of every secret); a hit fails the run.
- Blinding factors are fresh random values, not derived from the key (decided:
  derivation would recover blindings but not the hidden value, and full recovery
  would need new encryption design).
- Backup: the state file is versioned (previous states are kept, never
  overwritten in place), creation prints a one-time warning, and an explicit
  `backup` command copies the private directory to a location the user chooses.
  No printed recovery form: the state changes on every update.
- **Key or state loss freezes the tally permanently**; capacity stays locked.
  Key compromise lets the attacker change the tally but not take capacity.
- Never sends private inputs to a hosted prover or analytics service.

## 10. Required tests

- Spike differential cases (Noir vs backend R1CS) promoted to the regular suite:
  `scripts/check-private-tally-circuit.py`.
- Noir unit tests: `nargo test --workspace` in `circuits/private-tally-v2/`.
- Every Poseidon2 call ≤ 3 inputs, parameter layout and domain tags (static
  check): `scripts/tests/test_private_tally_circuit.py`.
- VM matrix: valid create/update/cover update; wrong key, blinding or value;
  proof replayed on another OutPoint, another Cell, another network, as a
  creation, or with `c_old`/`c_new` swapped; zero or non-canonical commitment;
  wrong version byte; Lock not the guard, Lock swapped on update; capacity
  changed; destruction; duplicate or ambiguous tally Cells; missing, wrong or
  duplicate VK; proof in the wrong witness field; oversized witness; resource
  limits.
- Mutations (incorrect acceptance with a passing control): removed verification,
  removed guard-Lock pin, removed canonical/non-zero check, removed creation
  rule.
- Leak scans on every run directory and CI artifact.

## 11. Implementation phases

| Phase | Delivers | Prerequisite |
| --- | --- | --- |
| D1 | Circuit, local single-party setup tooling, adapter reuse, client secret handling | This design (accepted) |
| D2 | Type Script, guard Lock pin, VM matrix, mutations | D1 |
| D3 | Local lifecycle in the launcher (`quick`/`local` for v2) on macOS and Linux | D2 |
| D4 | Ceremony, testnet deployment and a participant flow | D3, confirmed ceremony contributors, testnet funding |

## 12. Decisions (12 October 2026)

1. `MAX_DELTA = 2^32 − 1` for this profile.
2. Phase 2: maintainer, verifier author and binding reviewer (pending their
   agreement) plus a future CKB block hash as beacon; required before testnet only.
3. Backup: versioned 0600 state file, `backup` command and creation warning; no
   printed form.
4. Random blinding; no key-derived blinding in v2.
