# Try the private tally on CKB testnet

The private tally is a CKB Cell that holds a **hidden number**. Only the holder of
a secret key can add to it, and each addition is authorized by a zero-knowledge
proof made on the holder's own computer. The chain sees a new commitment (a
fingerprint of the number that reveals nothing about it) and a proof, never the
number or the amount added. Adding 0 (a "cover update") looks exactly like adding
any other amount.

This guide creates **your own tally** on the deployment already on testnet and
lets you add hidden amounts to it.

- **Who it's for:** developers comfortable with a terminal.
- **Computer:** macOS on Apple silicon, or Linux (x86_64 or ARM64).
- **Time:** about 20–30 minutes the first time, most of it downloading and
  compiling. Later runs take a few minutes.
- **Cost:** about 262 testnet CKB, free from the faucet. 200 CKB stays locked in
  your tally Cell; the rest comes back as change.

The design is in the [private tally v2 design](private-tally-v2-spec.md), and the
deployment's records are in the [testnet evidence](../evidence/private-tally-testnet.md).

## What you are trusting

- **The proving key comes from a public setup ceremony** with four
  contributors, sealed with a CKB mainnet block hash. Nobody can forge proofs as
  long as at least one contributor discarded their randomness. See the
  [ceremony folder](../ceremony/private-tally-v2/). It is a public
  developer-preview ceremony, not an audited production setup.
- **The proof is the only authority over your tally.** The tally Cell has no
  signature lock. Your account signs only for the CKB that pays the fee.
- **Your secret key exists only on your computer.** If it is lost, your tally is
  frozen forever and its 200 CKB stay locked. There is no withdrawal. The tool
  backs it up after every change. Testnet only; never use mainnet.

## 1. Install the basic tools

Skip any you already have.

- **macOS** (with [Homebrew](https://brew.sh)):

  ```bash
  brew install git python node
  ```

- **Ubuntu:**

  ```bash
  sudo apt install git python3 nodejs npm build-essential pkg-config
  ```

- **Both:** install `rustup` from <https://rustup.rs>, then **open a new terminal**
  so it is found.

## 2. Get the code

```bash
git clone https://github.com/wamimi/noir-ckb-verifier.git
cd noir-ckb-verifier
```

Run the next commands from inside this `noir-ckb-verifier` folder.

## 3. Install what the tally needs

```bash
python3 -B scripts/try-private-tally.py install
```

It first lists exactly what it will do and asks once before doing it:
- install the Rust version the project is pinned to (through rustup);
- download the proving backend (a fork of Noir-Groth16 at one exact commit)
  next to this folder, as `../Noir-Groth16`;
- download the Rust libraries and snarkjs, so later steps can run offline;
- download the CKB wallet tool (`ckb-cli`) and the Noir compiler (`nargo`), each
  checked against a published hash;
- download the 4.8 MB phase 1 file the ceremony was built on, checked against the
  hash recorded in the ceremony.

Nothing touches a wallet, and nothing is installed system-wide except the Rust
version. It ends with a check of everything and `Ready.` If a line says
`MISSING`, it prints what to do.

## 4. Run it

```bash
python3 -B scripts/try-private-tally.py run
```

It works through five stages and asks you before anything is sent:

| Stage | What happens |
| --- | --- |
| 1. Checking this computer | Confirms the install. |
| 2. Proving setup | Compiles the tally circuit, checks it is exactly the circuit the ceremony was run for, verifies the ceremony key and makes test proofs. A few minutes the first time. |
| 3. Testnet deployment | Checks that the deployed contract and verification key match the public record, and that **the key on chain is exactly the one your own setup derived from the ceremony key**. |
| 4. Your account | Uses your testnet-only account, or creates one with `ckb-cli`. You choose a password; this tool never sees it. |
| 5. Your tally | Finds a faucet payment in your account (or shows your address and waits for one), creates your tally at 0, then asks how much to add. |

**Getting testnet CKB.** If your account has no CKB yet, it prints your `ckt1…`
address. Open the [CKB testnet faucet](https://faucet.nervos.org), paste that
address and request CKB. The tool notices the payment by itself within a minute.

**Every transaction** goes the same way:
1. it shows the transaction (inputs, outputs, fee) and asks
   `Sign and send this …? [y/N]`;
2. `ckb-cli` asks for your account password;
3. the proof is re-checked against the signed transaction;
4. it is sent, the tool waits until it is committed, and records it;
5. your private folder is backed up to `~/noir-ckb-tally-backups/`.

**Adding amounts.** After the creation it asks for an amount: any whole number
from 0 to 4,294,967,295 (the largest 32-bit number; the circuit limits each
addition to 32 bits so a tally can't overflow in one step). 0 gives a cover
update. Press Enter to finish. It ends by showing your tally's value, which is
read from your private folder, not the chain, and links to your transactions.

You can stop at any prompt. Running `run` again continues where you left off and
lets you add more.

## What the chain shows

Open any of the printed links on the [testnet explorer](https://testnet.explorer.nervos.org).
Your tally is the 200 CKB Cell. Its data is 33 bytes: `01` (the format version)
followed by the 32-byte commitment. An update replaces one commitment with
another, and every update has the same size and shape, so nothing shows how much
was added, or whether anything was. The "Cycles" figure (about 117 million) is
the Groth16 proof being verified on chain, in CKB-VM.

What anyone can see: that your tally exists, when and how often it was updated,
and which account paid. One tally's updates are linkable to each other.

## Where your files are

| What | Where | Share it? |
| --- | --- | --- |
| Your tally's secret key and state | `target/try-private-tally/my-tally/private` | **Never** |
| Backups | `~/noir-ckb-tally-backups/` | **Never** |
| Testnet wallet | `~/.ckb-cli-noir-ckb-tally` | **Never** |
| Transactions and proofs | `target/try-private-tally/my-tally/public` | Safe (they're on chain anyway) |

## Share how it went

Please share your computer (for example "MacBook M2" or "Ubuntu 24.04 x86_64"),
how far it got, and for anything that failed, the last 20–30 lines of output.
Open an issue on [GitHub](https://github.com/wamimi/noir-ckb-verifier/issues/new/choose)
or reply on the Nervos Talk thread. One more question, if you have a moment:
**what would you build with this, and what would you want a proof like this
bound to?**

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `MISSING` for Python, git, Node.js or rustup | Install it with step 1, open a new terminal, run `install` again. |
| `MISSING` for anything else | Run `install` again; it only does what is still missing. |
| A download stops with "timed out" | Run the same command again. |
| `the setup did not pass` | Read the lines above it. A wrong Nargo or backend version is the usual cause; run `install` again. |
| `Not signed (wrong password?)` | Type the password again at the next prompt. |
| `not committed after 10 minutes` | Run `run` again later. It continues waiting; it never sends twice. |
| `is from an unfinished run` | Add `--work target/try-private-tally-2` to `run` to start fresh in a new folder. |

Want to see or script each step yourself? The same flow, command by command, is
in [the private tally step by step](private-tally-step-by-step.md).
