# Try the noir-ckb counter

This is the only guide you need to try noir-ckb. Follow it top to bottom.

**What you will do**

1. **Part 1, run it locally** (no wallet, no money). Your computer compiles a
   Noir circuit, makes a real zero-knowledge proof, starts a private throwaway CKB
   chain, and sends real signed transactions that create a counter and update it
   from 0 to 1 using that proof.
2. **Part 2, your own counter on CKB testnet** (optional). You create your own
   counter on the public testnet and update it with a proof made on your machine.
   Costs about 262 testnet CKB (free from the faucet).
3. **Part 3, tell us how it went.**

**What the counter is.** A CKB Cell holding a number. Its Type Script only accepts
an update if it comes with a valid proof that the new number is the old number
plus one, *and* the proof was made for this exact Cell, this exact change and
this network. Your own signature is also required. It is a small, public example
built to test that binding; it hides nothing.

---

## Before you start: pick your setup

| Your computer | Part 1 | Part 2 (testnet) |
| --- | --- | --- |
| Mac with Apple Silicon (M1–M4) | Container (easiest) or native | Native |
| Linux, Ubuntu 24.04 (x86_64 or ARM64) | Container (easiest) or native | Native |
| Intel Mac, Windows, other Linux | Not supported yet | Not supported yet |

- **Container** = everything runs inside a prepared Linux box (Docker). You only
  install Docker. Best if you just want to see it work.
- **Native** = you install the tools on your machine directly. Needed for Part 2,
  because the container is deliberately cut off from the internet while it runs.

Both start with the same step:

```bash
git clone https://github.com/wamimi/noir-ckb-verifier.git
cd noir-ckb-verifier
```

All commands in this guide are run from inside that `noir-ckb-verifier` folder.

---

## Part 1, option A: run it in a container

**Step 1. Install Docker.** Docker has two parts: the *engine*, which runs
containers in the background, and the `docker` command, which you type. You need
both. Pick the instructions for your computer, then do the check at the end.

**Mac (Apple Silicon).** Docker Desktop is not needed. These steps install Colima,
a small free engine, with the Homebrew package manager.

1. Check that Homebrew is installed:
   ```bash
   brew --version
   ```
   If this prints `command not found`, install Homebrew: open <https://brew.sh>,
   copy the single install command shown on that page into Terminal and press
   Enter. When it finishes, it prints "Next steps" with two or three commands that
   add `brew` to your PATH. Run those, then open a new Terminal window.
2. Install Colima, the `docker` command and its build plugin:
   ```bash
   brew install colima docker docker-buildx
   ```
3. Tell `docker` where Homebrew put the build plugin. This is needed once. It
   adds one setting to `~/.docker/config.json` and keeps anything already there:
   ```bash
   mkdir -p ~/.docker
   python3 - <<'EOF'
   import json, pathlib
   p = pathlib.Path.home() / ".docker/config.json"
   cfg = json.loads(p.read_text()) if p.exists() else {}
   dirs = cfg.setdefault("cliPluginsExtraDirs", [])
   if "/opt/homebrew/lib/docker/cli-plugins" not in dirs:
       dirs.append("/opt/homebrew/lib/docker/cli-plugins")
   p.write_text(json.dumps(cfg, indent=2) + "\n")
   print("updated", p)
   EOF
   ```
4. Start the engine with 4 CPU cores, 8 GB of memory and 60 GB of disk:
   ```bash
   colima start --cpu 4 --memory 8 --disk 60
   ```
   The first start downloads a small Linux system and takes a few minutes.
   Colima keeps running in the background. After restarting your Mac, run
   `colima start` again; it remembers these sizes. `colima stop` shuts it down.

**Ubuntu 24.04.**

1. Install the engine and the build plugin. `sudo` asks for your computer
   password:
   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-buildx
   ```
2. Start the engine now and every time the computer boots:
   ```bash
   sudo systemctl enable --now docker
   ```
3. Allow your user account to use Docker without `sudo`:
   ```bash
   sudo usermod -aG docker "$USER"
   ```
4. Log out of your desktop session and log back in (or restart the computer).
   The permission from step 3 only applies to new logins. To use it in the
   current terminal straight away instead, run `newgrp docker`.

   Note: members of the `docker` group can control the whole computer through
   Docker, so only do this on a machine you own.

**Check that Docker works (Mac and Ubuntu):**

```bash
docker version
```

The output has two parts, `Client:` and `Server:`. If both are there, Docker is
ready. If not:

| You see | Fix |
| --- | --- |
| `Cannot connect to the Docker daemon` | The engine is not running. Mac: `colima start`. Ubuntu: `sudo systemctl start docker`. |
| `permission denied` mentioning `docker.sock` (Ubuntu) | Log out and back in after step 3, or run `newgrp docker`. |
| `docker: command not found` (Mac) | Run `brew link --overwrite docker`, then open a new Terminal window. |

**Step 2. Build the container.** This downloads Rust, Noir, the CKB node and
everything else, inside the container only. The first build takes a while
(about 20 minutes on a laptop). If a download stalls, run the same command again;
it continues where it stopped.

```bash
scripts/run-counter-container.sh build
```

**Step 3. Run the demo.**

```bash
scripts/run-counter-container.sh quick
```

This one command does the whole demo by itself. There is nothing to type, sign
or approve while it runs, and no wallet or password is involved. You will see it
print seven numbered stages (`== Stage 1/7: local chain` up to `7/7`), explained
in [what the stages mean](#what-the-stages-mean), and finally `Container exit 0`.
It takes a few minutes. The run has no internet access: the CKB chain exists only
inside the container and is thrown away afterwards.

**Step 4 (optional). Run the full test suite** as well: 48 attack cases against
the contract, range checks, and three deliberately broken contracts that must be
caught.

```bash
scripts/run-counter-container.sh local
```

Your results are in `target/container-runs/<mode>-<time>/`. Go to [Part 3](#part-3-tell-us-how-it-went).

---

## Part 1, option B: run it natively

**Step 1. Install the base tools.**

- Mac:
  ```bash
  brew install git python node llvm@18
  ```
- Ubuntu 24.04:
  ```bash
  sudo apt install git python3 build-essential pkg-config clang-18 lld-18 nodejs npm
  ```
- Both: install `rustup` from <https://rustup.rs> and open a new terminal.

**Step 2. Get the pinned proving backend.** noir-ckb uses a maintained fork of
Noir-Groth16 at one exact version. It must sit next to `noir-ckb-verifier`:

```bash
git clone https://github.com/wamimi/Noir-Groth16.git ../Noir-Groth16
git -C ../Noir-Groth16 checkout --detach 828025f3a0090e2934940956c0f5dc8093eb5532
```

**Step 3. Install the exact Rust versions** (one for your computer, one that
compiles CKB contracts):

```bash
rustup toolchain install 1.95.0 --profile minimal
rustup toolchain install 1.94.1 --profile minimal --target riscv64imac-unknown-none-elf
```

**Step 4. Download the code libraries once**, so later steps can run offline:

```bash
cargo +1.95.0 fetch --locked --manifest-path Cargo.toml
cargo +1.94.1 fetch --locked --manifest-path contracts/Cargo.toml
cargo +1.95.0 fetch --locked --manifest-path ../Noir-Groth16/Cargo.toml
npm exec --yes --package=snarkjs@0.7.5 -- node -e 'console.log("snarkjs ready")'
```

**Step 5. Download the CKB node, CKB wallet tool and Noir compiler.** The script
lists exactly what it will download, then checks every file against a published
fingerprint (SHA-256) before installing it into `target/counter-tools/`. Nothing is
installed system-wide.

```bash
python3 scripts/fetch-counter-tools.py --yes
```

If it says "The read operation timed out", run it again.

**Step 6. Check everything is ready.**

```bash
python3 -B scripts/start-counter.py doctor
```

Every line should say `OK`, ending with `Prerequisite checks passed.` Each
`MISSING` line prints the exact command that fixes it. The doctor only looks; it
never installs or changes anything.

**Step 7. Run the demo.**

```bash
python3 -B scripts/start-counter.py quick
```

This one command does the whole demo by itself. There is nothing to type, sign
or approve while it runs, and no wallet or password is involved. It prints seven
numbered stages, explained in [what the stages mean](#what-the-stages-mean), and
finishes with `Stage 3/3: local runner completed`. The first run takes several
minutes because it compiles the proving backend; later runs take one to two
minutes.

**Step 8 (optional). Full test suite**, including the 48 attack cases and three
broken-contract checks:

```bash
python3 -B scripts/start-counter.py local
```

Your results are in `target/counter-local-<time>/manifest.json`.

---

## What the stages mean

In Part 1 you only start the demo and watch. The script does every step below
by itself, on a private chain that runs only on your computer, using a throwaway
key it creates for the run. No real or testnet funds are involved.

Two sets of numbers appear. `Stage 1/3` to `3/3` are the launcher's own steps
(check the tools, run the demo, report the result). The demo itself prints
`== Stage 1/7` to `7/7`:

| Stage | What the script does |
| --- | --- |
| 1/7 local chain | Starts a private CKB chain and creates a throwaway key that holds test coins on it. |
| 2/7 setup + fresh proof | Compiles the Noir counter circuit, generates a development proving key and verification key, and makes a test proof. |
| 3/7 contract build | Compiles the counter Type Script (the on-chain rules) with that verification key built in. |
| 4/7 deployment | Signs and sends a transaction that stores the contract and the verification key on the chain. |
| 5/7 creation | Creates a counter Cell holding 0. Creation needs no proof; the contract checks the zero start directly. |
| 6/7 update proof | Builds the transaction that changes the counter from 0 to 1, and makes a proof tied to that exact transaction. |
| 7/7 pre-signing check, sign, submit, confirm update | Checks that the proof matches the transaction, signs it, sends it, and confirms the chain accepted it with the counter now at 1. |

The full `local` mode adds three more stages in between: range checks (values
the circuit must reject), the 48 attack cases against the contract, and the three
deliberately broken contracts. Its numbers run to `10/10`.

---

## Part 2: your own counter on CKB testnet

This uses the contract that is **already deployed** on testnet, so you don't
deploy anything. You need the native setup from Part 1, option B (steps 1–6).

**What you're trusting.** The proving key was made by the maintainer alone. In
principle that means the maintainer could fake counter proofs. But every update to
*your* counter also needs *your* signature, so nobody can change your counter
without your key. The 200 CKB you put into the counter stays locked in it
permanently (this demo contract has no withdraw). Testnet only; never use mainnet.

**Step 1 (recommended). Rehearse everything locally first.** This runs all of
Part 2 against a private local chain, with a second test key playing "you":

```bash
python3 -B scripts/start-counter.py join-test
```

It should finish with `Stage 3/3: local runner completed`.

**Step 2. Check the published files and your tools.**

```bash
python3 -B scripts/join-counter-testnet.py init --out target/my-testnet-counter
```

This reads (never writes) the testnet and checks, in plain terms:
- the published proving files are exactly the ones recorded when the contract was deployed;
- the contract and key stored on testnet are exactly those files;
- your own computer compiles the circuit to the same thing the proving key was made for;
- a test proof made on your machine is accepted.

If any check fails, it stops and tells you which one. It ends with "Verified."

**Step 3. Make a testnet-only account.** Use a separate wallet folder just for
this, so it never mixes with anything else. You'll choose a password; keep it to
yourself.

```bash
export CKB_CLI_HOME="$HOME/.ckb-cli-noir-ckb-testnet"
export COUNTER_CLI="$(ls target/counter-tools/*/ckb-cli | head -1)"
"$COUNTER_CLI" account new
```

If you installed the tools somewhere other than `target/counter-tools/`, set
`COUNTER_CLI` to the full path of that `ckb-cli` instead, and add
`--tools <that folder>` to the `init` command in Step 2.

It prints your new account under several headings. You need two values:
- the **testnet address**: the `testnet:` line under `address:` (starts with
  `ckt1`). Ignore the `mainnet:` lines and the `address(deprecated):` section;
  the deprecated one is an older, shorter format of the same account.
- the **lock_arg** (starts with `0x`, 42 characters). This is your public account ID.

All of these are public; sharing them is safe. Only the password and the wallet
folder are secret.

```bash
export COUNTER_OWNER=0x...your lock_arg...
```

Keep this terminal open: the next steps reuse these settings.

**Step 4. Get free testnet CKB.** Open the
[CKB testnet faucet](https://faucet.nervos.org), paste your `ckt1…` address and
request CKB. You need **at least 262 CKB in a
single payment** (200 locked in your counter, 61 returned to you as change,
and a tiny fee).

**Step 4b. Find the faucet payment's ID.** On CKB, money is not a balance on
an account. Each payment you receive is a separate box of CKB called a *Cell*.
To spend a Cell, a transaction must name it exactly, by two things:

- the **transaction hash** of the payment that created it (`0x` + 64 characters);
- the **output index**: its position in that transaction's list of outputs
  (`0` for the first, `1` for the second, …).

Together these are the Cell's *OutPoint*. The create step needs the OutPoint of
your faucet Cell, because that Cell pays for your counter.

List the unspent Cells at your address (use the testnet address from Step 3):

```bash
"$COUNTER_CLI" --url https://testnet.ckb.dev wallet get-live-cells --address ckt1...your address...
```

Each entry is one Cell. Pick one that has a capacity of at least 262 CKB and no
data or type (a faucet payment has neither). Copy its `tx_hash` and its output
index. If the command fails, open your address on the
[testnet explorer](https://testnet.explorer.nervos.org), open the faucet
transaction, and read the transaction hash and which output (counting from 0)
was paid to your address.

Write them as `hash:index`:

```bash
export COUNTER_FUNDING=0x...tx_hash...:0
```

Keep the `:` and the number at the end: the hash alone is not enough. Replace
`0` with the output index if it is not 0. The `create` step checks this
Cell before building anything and stops if it is not yours, already spent, too
small or not a plain payment.

**Step 5. Create your counter at 0.** This step has two parts: a script
prepares the transaction, then you sign and send it yourself with `ckb-cli`.
The script never signs or sends anything.

**5a. Prepare the transaction:**

```bash
python3 -B scripts/join-counter-testnet.py create --work target/my-testnet-counter --owner "$COUNTER_OWNER" --funding "$COUNTER_FUNDING"
```

It saves an unsigned transaction and prints five numbered commands, each with
what to expect. The same five commands are written out below. Run them one at a
time, in order, in the same terminal (they use `COUNTER_CLI` and
`COUNTER_OWNER` from Step 3).

**5b. Run the five commands.**

1. Select the transaction file (no output):

   ```bash
   export COUNTER_TX="target/my-testnet-counter/create.json"
   ```

2. Review it:

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx info --tx-file "$COUNTER_TX"
   ```

   Expected output (your own address appears where `ckt1...` is shown):

   ```text
   [input] ckt1... => 10000.0, (data-length: 0, type-script: none, lock-kind: sighash(secp))
   [output] ckt1... => 200.0, (data-length: 9, type-script: some, lock-kind: sighash(secp))
   [output] ckt1... => 9799.99, (data-length: 0, type-script: none, lock-kind: sighash(secp))
   input_total: 10000.0 (CKB)
   output_total: 9999.99 (CKB)
   tx_fee: 0.01 (CKB)
   ```

   The first output is your counter: 200 CKB, owned by your address, with the
   counter Type Script (`type-script: some`) and 9 bytes of counter state. The
   second output is your change. The amounts differ if your funding Cell was not
   10,000 CKB. If there are more outputs, or the fee is much larger, stop.

3. Sign it. `ckb-cli` asks for the password you chose in Step 3:

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx sign-inputs --tx-file "$COUNTER_TX" --from-account "$COUNTER_OWNER" --add-signatures --skip-check
   ```

   Expected: your `lock-arg` and a long `signature`.

4. Send it to testnet:

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx send --tx-file "$COUNTER_TX" --skip-check
   ```

   Expected: one transaction hash, `0x` followed by 64 characters. Copy it.
   **Run this only once.** If it seems to fail, look the hash up on the
   [testnet explorer](https://testnet.explorer.nervos.org) before trying again.

5. Record it. Replace `0xPASTE_THE_HASH` with the hash that command 4 printed:

   ```bash
   python3 -B scripts/join-counter-testnet.py confirm --work target/my-testnet-counter --hash 0xPASTE_THE_HASH
   ```

   Expected: `Confirmed creation: counter is now 0.` If it says the transaction
   is not committed yet, wait 30 seconds and run the same command again.

**Step 6. Update it to 1 with a proof made on your machine.** Same pattern:
prepare, then six commands to run yourself.

**6a. Prepare the update:**

```bash
python3 -B scripts/join-counter-testnet.py update --work target/my-testnet-counter
```

This builds the update transaction, makes a fresh proof bound to your counter
and to this exact change, and checks it. It takes a minute or two, then prints
six numbered commands.

**6b. Run the six commands.**

1. Select the transaction file (no output):

   ```bash
   export COUNTER_TX="target/my-testnet-counter/update-1-proof/transaction.json"
   ```

   For later updates the number changes (`update-2-proof`, …); use the line the
   script printed.

2. Review it:

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx info --tx-file "$COUNTER_TX"
   ```

   Expected: **two inputs** (your counter, and your change Cell from Step 5)
   and two outputs: your counter (200.0, `type-script: some`) and your change
   (`type-script: none`). Fee about 0.01 CKB.

3. Sign it (asks for your password):

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx sign-inputs --tx-file "$COUNTER_TX" --from-account "$COUNTER_OWNER" --add-signatures --skip-check
   ```

4. Re-check the proof after signing:

   ```bash
   python3 -B scripts/join-counter-testnet.py check --work target/my-testnet-counter
   ```

   Expected: a line containing `"status": "checked-before-signing"`. This
   confirms that signing did not change anything the proof depends on. If it
   fails, do not send.

5. Send it to testnet (only once):

   ```bash
   "$COUNTER_CLI" --url https://testnet.ckb.dev tx send --tx-file "$COUNTER_TX" --skip-check
   ```

6. Record it. Replace `0xPASTE_THE_HASH` with the hash that command 5 printed:

   ```bash
   python3 -B scripts/join-counter-testnet.py confirm --work target/my-testnet-counter --hash 0xPASTE_THE_HASH
   ```

   Expected: `Confirmed update-1: counter is now 1.`

Your counter is now 1. Run Step 6 again to go to 2, 3, …

Your transactions are visible on
`https://testnet.explorer.nervos.org/transaction/<hash>`.

---

## Optional: the private tally (local only)

The private tally is the next example: the Cell holds a hidden number, and
whoever knows a secret key can add to it with a proof, without a signature.
Its design is in the [private tally v2 design](private-tally-v2-spec.md). It is
deployed on testnet with the key from the public [setup ceremony](setup-ceremony.md);
to create your own tally there, follow [Try the private tally](try-the-private-tally.md).
The commands below run it on a private local chain instead.

**Container** (after `scripts/run-counter-container.sh build`):

```bash
scripts/run-counter-container.sh tally-quick
```

**Native** (after Part 1, option B):

```bash
python3 -B scripts/start-counter.py tally-quick
```

Like the counter, this one command does everything by itself on a private local
chain. It prints eight stages:

| Stage | What the script does |
| --- | --- |
| 1 local chain | Starts a private CKB chain and creates a throwaway key with test coins. |
| 2 development setup | Compiles the tally circuit, makes a development proving key (single party, not the ceremony) and test proofs. |
| 3 Type Script build | Compiles the tally Type Script with that key built in. |
| 4 deployment | Signs and sends the Type Script, the verification key and the guard Lock code to the chain. |
| 5 create at 0 | Generates a secret key and a random blinding factor, proves that a new hidden tally starts at 0, and creates the Cell. |
| 6 update +7 | Proves that the new hidden value is the old one plus 7, without revealing either, and updates the Cell. |
| 7 cover update +0 | Updates again adding nothing. On chain this looks like any other update. |
| 8 status, backup and leak scan | Confirms the private state says 7 and matches the chain, makes a backup, and checks that no secret appears in any kept file. |

It finishes with `Stage 3/3: local runner completed` and a manifest whose status
is `local-lifecycle-validated`. `tally-local` instead of `tally-quick` also runs
49 attack cases in CKB-VM and 4 deliberately broken contracts that must be caught.

In the run folder, `tally/public/` holds the transactions and proofs, which
anyone could see on chain. `tally/private/` holds the key and blinding factors.
Never share that folder.

## Part 3: tell us how it went

Please share:
- your computer and setup (for example "MacBook M2, native" or "Ubuntu 24.04 x86_64, container");
- which parts you ran and whether they finished;
- `manifest.json` from your run folder (for Part 2: the output of
  `python3 -B scripts/join-counter-testnet.py status --work target/my-testnet-counter`);
- for anything that failed: the last 20–30 lines of output.

Post it as an issue using the "Owned counter v1 preview review" template on
[GitHub](https://github.com/wamimi/noir-ckb-verifier/issues/new/choose), or reply on
the Nervos Talk thread.

**Never share** your password, your wallet folder, or the whole run folder. The
run folders contain throwaway keys and logs nobody needs.

---

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `MISSING:` lines from the doctor | Run the command printed under each one, then run the doctor again. |
| A download stops with "timed out" | Run the same command again. |
| "Output already exists" | Each run needs a new folder; leave out `--out` or pick another name. |
| Port already in use | Add `--rpc-port 19124 --p2p-port 19125` to the command. |
| `docker: command not found` on a Mac | `brew install docker`, and if it says "not linked", `brew link docker`. |
| A testnet command fails with a network error | Check your internet, then retry the read-only command. Never re-send a transaction without checking its hash first. |
| `create` says the funding Cell is unsuitable | It must be a plain payment to your own address, with no data, not already spent, and at least 262 CKB. |

## What this is, and what it isn't

- A fixed, public counter example: not a privacy application, and not a way to
  deploy arbitrary Noir circuits yet.
- The proving key comes from a single-party development setup, not a production
  ceremony. Testnet only. Not audited.
- No withdrawal: CKB placed in a counter stays there.
- Want to deploy your own separate copy of the contract instead of joining this
  one? That's the [advanced operator guide](owned-counter-testnet.md) (needs
  about 114,000 testnet CKB).
- How it works, and the design behind it: see the [documentation map](README.md).
