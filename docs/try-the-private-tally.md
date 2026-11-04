# Try the private tally on CKB testnet

The private tally is a CKB Cell that holds a **hidden number**. Only the holder of
a secret key can add to it, and each addition is authorized by a zero-knowledge
proof made on the holder's own computer. The chain sees a new commitment and a
proof, never the number or the amount added. Adding 0 (a "cover update") looks
exactly like adding any other amount.

This guide creates **your own tally** on the deployment that is already on
testnet, then adds a hidden amount to it. It costs about **262 testnet CKB**
(free from the faucet): 200 CKB is locked in your tally Cell, the rest comes
back as change.

The design is in the [private tally v2 design](private-tally-v2-spec.md), and the
deployment's records are in the [testnet evidence](../evidence/private-tally-testnet.md).

## What you are trusting

- **The proving key comes from a public setup ceremony** with four
  contributors, sealed with a CKB mainnet block hash. Nobody can forge proofs
  as long as at least one contributor discarded their randomness. You can
  check the ceremony yourself: see the [ceremony folder](../ceremony/private-tally-v2/).
  It is a public developer-preview ceremony, not an audited production setup.
- **The proof is the only authority over your tally.** There is no signature
  on the tally Cell itself. Your account signs only the CKB that pays the fee.
- **Your secret key lives only in your work folder** (`my-tally/private`).
  If you lose it, your tally is frozen forever and its 200 CKB stay locked.
  There is no withdrawal. Testnet only; never use mainnet.

## Before you start

Complete **Part 1, option B (native), steps 1–6** of
[Try the counter](try-the-counter.md), so that this passes:

```bash
python3 -B scripts/start-counter.py doctor
```

Supported: macOS on Apple silicon, and Linux (x86_64 and ARM64). Keep one
terminal window open for the whole guide: later steps reuse values set in it.

## Step 1. Download the phase 1 file

The ceremony was built on a public Perpetual Powers of Tau file (4.8 MB). Your
setup in Step 2 checks it against the hash recorded in the ceremony transcript.

```bash
cd ~/noir-ckb-verifier
curl -L -o target/ppot_0080_12.ptau https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_12.ptau
```

## Step 2. Rebuild the setup from the ceremony key

```bash
python3 -B scripts/setup-private-tally.py --out target/my-tally-setup --backend ../Noir-Groth16 --ptau target/ppot_0080_12.ptau --ceremony ceremony/private-tally-v2
```

This takes a few minutes. On your own computer it:
- compiles the tally circuit and checks that it becomes exactly the circuit the
  ceremony was run for;
- checks the ceremony's final key and verification key against the transcript,
  and verifies the key with `snarkjs`;
- makes two test proofs and checks that changing any public value makes them fail.

It ends with `passed: …/manifest.json`. If it stops with an error, see
[If something goes wrong](#if-something-goes-wrong).

## Step 3. Check the live deployment

```bash
python3 -B scripts/join-private-tally.py init --setup target/my-tally-setup --out target/my-tally-join
```

This only reads public chain data. It checks that the RPC is CKB testnet, that
the three deployed Cells (Type Script, verification key, guard Lock code) match
the public record, and that **the verification key on chain is exactly the one
your own setup derived from the ceremony key**. It ends with `Verified.`

## Step 4. A testnet account

If you already made one for the counter, reuse it. Otherwise:

```bash
export CKB_CLI_HOME="$HOME/.ckb-cli-noir-ckb-testnet"
export COUNTER_CLI="$(ls target/counter-tools/*/ckb-cli | head -1)"
"$COUNTER_CLI" account new
```

You choose a password; keep it to yourself. From the output you need the
**testnet address** (the `testnet:` line under `address:`, starting with
`ckt1`) and the **lock_arg** (starting with `0x`, 42 characters). Both are
public. Then set them in this terminal:

```bash
export CKB_CLI_HOME="$HOME/.ckb-cli-noir-ckb-testnet"
export COUNTER_CLI="$(ls target/counter-tools/*/ckb-cli | head -1)"
export COUNTER_OWNER=0x...your lock_arg...
export TALLY_ADDRESS=ckt1...your testnet address...
```

If you installed the tools somewhere other than `target/counter-tools/`, set
`COUNTER_CLI` to the full path of that `ckb-cli` instead.

## Step 5. Get testnet CKB and pick a funding Cell

Request CKB from the [CKB testnet faucet](https://faucet.nervos.org) with your
`ckt1…` address. Then list your Cells:

```bash
"$COUNTER_CLI" --url https://testnet.ckb.dev wallet get-live-cells --address "$TALLY_ADDRESS"
```

Pick one with **at least 262 CKB**, `data_bytes: 0` and no `type_hashes` (a
faucet payment looks like this). Write its `tx_hash` and `output_index` as
`hash:index`:

```bash
export TALLY_FUNDING=0x...tx_hash...:0
```

Replace `0` with the output index if it is not 0. Cells that hold data or a Type
(for example a counter) are refused, so they can't be spent by mistake.

## Step 6. Create your tally at 0

```bash
python3 -B scripts/private-tally-client.py create --release target/my-tally-join/release.json --deployment target/my-tally-join/deployment.json --work target/my-tally-join/my-tally --rpc https://testnet.ckb.dev --owner "$COUNTER_OWNER" --funding "$TALLY_FUNDING"
```

This creates a new secret key and a random blinding factor in
`target/my-tally-join/my-tally/private`, makes a proof that your new hidden
tally starts at 0, and prepares the transaction. It does **not** sign or send
anything. It prints six numbered commands. Run them yourself, one at a time:

1. select the transaction file;
2. review it: one input (your faucet Cell), and two outputs: the tally Cell
   (200 CKB, `data-length: 33`, with a type script) and your change;
3. sign it (your account password, typed in the terminal);
4. re-check the proof after signing: it must print `"status": "checked"`;
5. send it, **once**: it prints a transaction hash;
6. record it with that hash. If it says `not committed yet`, wait a minute and
   run the same command again. Do not send again.

Then back up your private folder, somewhere outside the repository:

```bash
python3 -B scripts/private-tally-client.py backup --work target/my-tally-join/my-tally --to ~/my-tally-backup-1
```

## Step 7. Add a hidden amount

Pay for the update with the change of your creation, which is output 1 of the
creation transaction. Replace `0xCREATION_HASH` with the hash from step 5 above,
and `5` with any whole number from 0 to 4,294,967,295:

```bash
python3 -B scripts/private-tally-client.py update --work target/my-tally-join/my-tally --funding 0xCREATION_HASH:1 --delta 5
```

It prints the same six commands. This time the review shows two inputs (your
tally Cell and your change) and two outputs (the new tally Cell and change).
When it is recorded, check your value:

```bash
python3 -B scripts/private-tally-client.py status --work target/my-tally-join/my-tally --show-value
```

`--show-value` reads the value from your private folder. It is not on chain.
Make another backup after each update (`--to ~/my-tally-backup-2`, and so on).
For the next update, pay with output 1 of the previous update transaction.

## What the chain shows

Open your transactions on the [testnet explorer](https://testnet.explorer.nervos.org).
In each, output 0 is your tally Cell, and its data is 33 bytes: a version byte
`01` followed by the 32-byte commitment. An update replaces one commitment with
another. Nothing in the transaction shows the amount you added, and an update
adding 0 looks the same as any other. What is visible: that a tally exists,
when and how often it was updated, and which account paid the fee.

## Share how it went

Please share your computer and setup (for example "MacBook M2, native"), which
steps finished, and the output of `status` **without** `--show-value`. For
anything that failed, include the last 20–30 lines of output. Open an issue on
[GitHub](https://github.com/wamimi/noir-ckb-verifier/issues/new/choose) or reply
on the Nervos Talk thread.

**Never share** your password, your wallet folder, or anything in
`my-tally/private` or its backups.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `--ptau is not the ceremony's phase 1 file` | The download was incomplete or wrong. Run Step 1 again. |
| `this build's R1CS differs from the frozen ceremony circuit` | Your Nargo or backend version differs. Run the doctor from Before you start. |
| `exists; choose a new directory` | Each run needs a new `--out` folder. |
| `funding must be one empty Cell owned by your account` | Use a plain faucet Cell of your own account, not already spent. |
| `not committed yet` | Wait a minute and run the same `confirm` again. Do not send again. |
| `the live tally commitment differs from your private state` | Your private folder does not match the chain. Restore your latest backup. |
