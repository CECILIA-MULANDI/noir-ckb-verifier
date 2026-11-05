# The private tally on testnet, step by step

The private tally is a CKB Cell that holds a **hidden number**. Only the holder of
a secret key can add to it, and each addition is authorized by a zero-knowledge
proof made on the holder's own computer. The chain sees a new commitment (a
fingerprint of the hidden number that reveals nothing about it) and a proof,
never the number or the amount added. Adding 0 (a "cover update") looks exactly
like adding any other amount.

This is the manual version of [Try the private tally](try-the-private-tally.md):
the same flow, one command at a time, for readers who want to see or script
every step. Most people should use the two-command guide instead.

In this guide you create **your own tally** on the deployment that is already on
testnet, then add a hidden amount to it. It costs about **262 testnet CKB**,
which is free from the faucet: 200 CKB is locked in your tally Cell and the rest
comes back to you as change.

The design is in the [private tally v2 design](private-tally-v2-spec.md), and the
deployment's records are in the [testnet evidence](../evidence/private-tally-testnet.md).

## What you are trusting

- **The proving key comes from a public setup ceremony** with four
  contributors, sealed with a CKB mainnet block hash. Nobody can forge proofs as
  long as at least one contributor discarded their randomness. The
  [ceremony folder](../ceremony/private-tally-v2/) has everything needed to check
  it. It is a public developer-preview ceremony, not an audited production setup.
- **The proof is the only authority over your tally.** The tally Cell has no
  signature lock. Your account signs only for the CKB that pays for the
  transaction.
- **Your secret key exists only on your computer**, in your work folder. If you
  lose it, your tally is frozen forever and its 200 CKB stay locked. There is no
  withdrawal. Testnet only; never use mainnet.

## Before you start

**1. Clone this repository** onto your computer and go into it:

```bash
git clone https://github.com/wamimi/noir-ckb-verifier.git
cd noir-ckb-verifier
```

Run every command in this guide from inside this `noir-ckb-verifier` folder.

**2. Install the tools.** Follow [Try the counter](try-the-counter.md), Part 1,
option B (native), steps 1–6. They install the Rust versions, the pinned proving
backend (cloned next to this folder as `../Noir-Groth16`), snarkjs, the CKB
tools and the Noir compiler. The last step checks everything:

```bash
python3 -B scripts/start-counter.py doctor
```

Every line should say `OK`. You don't need to run the counter demo itself.

Supported: macOS on Apple silicon, and Linux (x86_64 and ARM64).

**3. Keep one terminal window open** until the end. Several steps store values
(your address, the Cell you pay with) that later steps reuse. If you do close
it, `cd` back into `noir-ckb-verifier` and paste the `export` lines from Step 4
and Step 5 again.

## Step 1. Download the phase 1 file

Groth16 keys are made in two phases. Phase 1 is a large public file shared by
many projects; this ceremony used PSE's Perpetual Powers of Tau (4.8 MB). Step 2
checks it against the hash recorded in the ceremony.

```bash
curl -L -o target/ppot_0080_12.ptau https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_12.ptau
```

## Step 2. Rebuild the setup from the ceremony key

```bash
python3 -B scripts/setup-private-tally.py --out target/my-tally-setup --backend ../Noir-Groth16 --ptau target/ppot_0080_12.ptau --ceremony ceremony/private-tally-v2
```

This takes a few minutes. On your own computer it:
- compiles the tally circuit and checks that it is exactly the circuit the
  ceremony was run for, so the key fits it;
- checks the ceremony's final key and verification key against the ceremony
  record, and verifies the key with `snarkjs`;
- makes two test proofs and checks that changing any public value makes them fail.

It ends with `passed: …/manifest.json`.

## Step 3. Check the live deployment

```bash
python3 -B scripts/join-private-tally.py init --setup target/my-tally-setup --out target/my-tally-join
```

This only reads from testnet. It checks that the three Cells of the deployment
(the tally contract, its verification key and a small lock program it uses)
match the public record, and that **the verification key on chain is exactly
the one your own setup derived from the ceremony key**. You don't have to take
anyone's word for which key is deployed. It ends with `Verified.`

## Step 4. Make a testnet account

This makes a new account just for this guide, in its own wallet folder, so it
never mixes with any other wallet:

```bash
export CKB_CLI_HOME="$HOME/.ckb-cli-noir-ckb-tally"
export COUNTER_CLI="$(ls target/counter-tools/*/ckb-cli | head -1)"
"$COUNTER_CLI" account new
```

It asks you to choose a password. Keep it to yourself: it is the only secret in
this step. It then prints your account. You need two values from it:

```text
- "#": 0
  address:
    mainnet: ckb1qzda0cr08m85...        <- ignore
    testnet: ckt1qzda0cr08m85...        <- your testnet address
  address(deprecated):                  <- ignore this whole section
    ...
  lock_arg: 0x1a2b3c4d5e6f7a8b...       <- your lock_arg (0x + 40 characters)
```

Both are public; sharing them is safe. Set them in this terminal, replacing the
placeholders with your own values:

```bash
export COUNTER_OWNER=0x...your lock_arg...
export TALLY_ADDRESS=ckt1...your testnet address...
```

The tool commands use the name `COUNTER_OWNER` for your account; it is the same
setting the counter guide uses.

## Step 5. Get testnet CKB and choose the Cell to pay with

Open the [CKB testnet faucet](https://faucet.nervos.org), paste your `ckt1…`
address and request CKB. Wait a minute, then list what you received:

```bash
"$COUNTER_CLI" --url https://testnet.ckb.dev wallet get-live-cells --address "$TALLY_ADDRESS"
```

On CKB, money is not one balance. Every payment you receive is a separate box
of CKB called a **Cell**. To pay for something you name one Cell exactly, by the
**transaction hash** of the payment that created it and its **output index**
(its position in that transaction, counting from 0). The output looks like this:

```text
live_cells:
  - capacity: 10000.0 (CKB)             <- at least 262 CKB
    data_bytes: 0                       <- must be 0
    index:
      output_index: 0
      tx_index: 1
    lock_hash: 0x...
    mature: true
    number: 22900000
    output_index: 0                     <- the output index
    tx_hash: 0x3f5c9d0e7b1a24...        <- the transaction hash
    type_hashes: ~                      <- must be ~ (nothing)
```

A fresh faucet payment always looks like this. Choose a Cell with **at least
262 CKB**, `data_bytes: 0` and `type_hashes: ~`, and write its transaction hash
and output index with a colon between them:

```bash
export TALLY_FUNDING=0x3f5c9d0e7b1a24...the full tx_hash...:0
```

Keep the `:` and the number at the end, and use the `output_index` shown for
your Cell. A Cell with data or type hashes is not plain CKB: it is part of an
application, for example a counter. The tools refuse those, so you can't spend
one by mistake.

## Step 6. Create your tally at 0

```bash
python3 -B scripts/private-tally-client.py create --release target/my-tally-join/release.json --deployment target/my-tally-join/deployment.json --work target/my-tally-join/my-tally --rpc https://testnet.ckb.dev --owner "$COUNTER_OWNER" --funding "$TALLY_FUNDING"
```

This creates your secret key and a random blinding factor (extra randomness
that keeps the commitment from revealing the number) in
`target/my-tally-join/my-tally/private`. It makes a proof, on your computer, that
your new tally starts at 0, and prepares the transaction. It does **not** sign
or send anything.

It then prints six numbered commands. **Copy and run them one at a time,
exactly as printed**:

1. Selects the transaction file.
2. Shows the transaction for you to review: one input (your faucet Cell) and two
   outputs, the tally Cell (200 CKB, `data-length: 33`, type script `some`) and
   your change.
3. Signs it. This asks for the password from Step 4.
4. Re-checks the proof against the signed transaction. It must print
   `"status": "checked"`.
5. Sends it. Run this **once**. It prints the transaction hash (`0x…`).
6. Records it. Replace `0xPASTE_THE_HASH` with the hash from step 5. If it says
   `not committed yet`, wait a minute and run the same command again; do not
   send again.

Then **back up your private folder**. It holds the only copy of your secret key;
without it, nobody (including you) can ever update your tally again:

```bash
python3 -B scripts/private-tally-client.py backup --work target/my-tally-join/my-tally --to ~/my-tally-backup-1
```

Keep the backup on your own computer, outside the `noir-ckb-verifier` folder.

## Step 7. Add a hidden amount

Each transaction gives your leftover CKB back as its output 1 (your change).
You pay for the update with the change of your creation: its transaction hash
from step 5 above, followed by `:1`.

In the command below, replace `0xCREATION_HASH` with that hash, and replace the
**number at the end** (`5`) with the amount you want to add:

```bash
python3 -B scripts/private-tally-client.py update --work target/my-tally-join/my-tally --funding 0xCREATION_HASH:1 --delta 5
```

The amount can be any whole number from 0 to 4,294,967,295. That is the largest
32-bit number: the circuit limits each single addition to 32 bits, so that a
tally (a 64-bit number) can't overflow in one step. 0 is allowed and gives a
cover update.

It prints the same six commands; run them the same way. This time the review
shows two inputs (your tally Cell and your change) and two outputs (the new
tally Cell and new change). When it is recorded, check your tally:

```bash
python3 -B scripts/private-tally-client.py status --work target/my-tally-join/my-tally --show-value
```

`value` is read from your private folder; it is not on chain. Back up again
after each update, with a new name (`--to ~/my-tally-backup-2`). For another
update, pay with output 1 of your previous update: `0xPREVIOUS_UPDATE_HASH:1`.

## What the chain shows

Open your transactions on the [testnet explorer](https://testnet.explorer.nervos.org)
by pasting a transaction hash into its search box. Output 0 is your tally Cell.
Its data is 33 bytes: `01` (the format version) followed by the 32-byte
commitment. An update replaces one commitment with another, and nothing in the
transaction shows how much was added: an update adding 0 looks exactly like one
adding 5. What anyone can see: that your tally exists, when and how often it was
updated, and which account paid.

## Share how it went

Please share your computer and setup (for example "MacBook M2, native"), which
steps finished, and the output of `status` **without** `--show-value`. For
anything that failed, include the last 20–30 lines of output. Open an issue on
[GitHub](https://github.com/wamimi/noir-ckb-verifier/issues/new/choose) or reply
on the Nervos Talk thread.

**Never share** your password, your wallet folder (`~/.ckb-cli-noir-ckb-tally`),
or anything in `my-tally/private` or your backups.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `no matches found` or `No such file` for `ckb-cli` | The tools are missing; run Part 1, option B, step 5 of [Try the counter](try-the-counter.md). |
| `--ptau is not the ceremony's phase 1 file` | The download was incomplete; run Step 1 again. |
| `this build's R1CS differs from the frozen ceremony circuit` | Your Nargo or backend version differs; run the doctor again. |
| `exists; choose a new directory` | That folder is already used; pick a new `--out` name. |
| `funding must be one empty Cell owned by your account` | Use a plain faucet Cell of this account (Step 5), not already spent. |
| `Check password failed` | The password was mistyped; run the same sign command again. |
| `not committed yet` | Wait a minute and run the same record command again. Do not send again. |
| `the live tally commitment differs from your private state` | Your private folder does not match the chain; restore your latest backup. |
