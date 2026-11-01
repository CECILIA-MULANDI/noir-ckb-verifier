# Setup ceremony for the private tally

**Status: complete.** The circuit was frozen at tag
`private-tally-v2-circuit-freeze` (commit `774aafd`) and the ceremony opened on
17 October 2026. Four contributions were verified and accepted. Contributions
closed when CKB mainnet block 20,870,000 was produced; its hash,
`0x0734b3f08b5e78144c73a58313647a94f053223d8b71ae17ed18cf3140dbb44d`, was
applied as the beacon on 1 November 2026. The final key, verification key,
verification log and full transcript are in
[`ceremony/private-tally-v2/`](../ceremony/private-tally-v2/). Contributors can
find their hash in
[`verify-final.log`](../ceremony/private-tally-v2/verify-final.log). The rest of
this guide is kept as a record of how the ceremony ran and how to check it.

## Why a ceremony is needed

Groth16 proofs need a proving key and a verification key made for one specific
circuit. Making them requires secret random numbers. Anyone who kept those
numbers could create proofs for false statements, which for the private tally
would mean changing someone's hidden tally without their key.

A ceremony spreads that secret across many people. Each contributor mixes their
own fresh randomness into the key and then forgets it. **If at least one
contributor's randomness is never recovered, nobody can forge proofs.** Nobody
has to trust any single person, including the coordinator.

The counter example used a single-party development setup. The private tally
will not be deployed to testnet without this ceremony.

## How it works

The ceremony follows the standard snarkjs Groth16 procedure and has two phases.

**Phase 1 (universal) is reused, not repeated.** It comes from the public
[Perpetual Powers of Tau](https://github.com/privacy-ethereum/perpetualpowersoftau#prepared-and-truncated-files)
transcript: the prepared file `ppot_0080_12.ptau`, which PSE built from the
transcript's response 0080 and finished with a beacon from an Ethereum
beacon-chain slot. `snarkjs powersoftau verify` lists 61 contributions plus that
beacon (iteration exponent 31) and confirms the whole chain; on a laptop this
check takes about 40 minutes. The file's BLAKE2b-512 hash is
`3ee85ae13672d1d742117566126f31d678cf72d480f0df8e2aec78d77771433392ae01bb2b11c4ea0e60b244415be0a12a02e51d3f7a4a8b5c1c982fa208c4cd`. The circuit has
3,338 constraints, so the degree-12 file (4,096 points) is enough. The coordinator
checks the whole contribution chain with `snarkjs powersoftau verify` and
publishes the file's BLAKE2b hash. (The older Hermez files linked from the
snarkjs README are no longer downloadable;
[snarkjs issue #636](https://github.com/iden3/snarkjs/issues/636).)

**Phase 2 (circuit-specific) is this ceremony.** It is a relay, one contributor
at a time:

1. The coordinator freezes the circuit, publishes its R1CS file and hash, the
   phase 1 file name and hash, and the initial key `tally_0000.zkey`.
2. Before the first contribution, the coordinator announces the **beacon**: the
   hash of a CKB mainnet block at a stated future height. Nobody can know that
   hash in advance, so nobody can choose it to suit them.
3. Each contributor downloads the latest key, adds their randomness with one
   `snarkjs` command, and returns the new key plus the **contribution hash** it
   prints. The coordinator contributes first, under the same rules,
   so the chain never starts from an uncontributed key.
4. The coordinator checks every new key with `snarkjs zkey verify` before
   passing it on. A broken or malicious key is rejected, so files can travel
   over any channel.
5. After the last contribution and once the beacon block exists, the coordinator
   applies the beacon, verifies the final key, exports the verification key and
   publishes the full transcript.
6. Each contributor checks that their contribution hash appears in the final
   transcript.

## Contributing (about 10–15 minutes)

You need a Mac or Linux computer with Node.js 18 or newer (`node --version`).
You do not need Rust, Noir, CKB tools, a wallet or any money. Nothing in this
process asks for keys or passwords.

**Why there are turns.** Each contribution is built on top of the previous
key. If two people download the same key and contribute at the same time, they
make two different next keys, and only one of them can go into the chain; the
other person's work is thrown away. So contributions happen one at a time, and
a turn just means "the next key number is reserved for you".

**Asking for a turn.** Open an issue on this repository titled
`Turn request: <your name>`, or reply on the Nervos Talk thread or in the CKB
Telegram group. Turns go in the order they were asked for. You will get a
reply when the key before yours has been accepted.

When your turn comes, the coordinator renames your turn request issue (or, if
you asked elsewhere, opens one) to `Contribution N: <your name>` and posts a
link to the latest key and its SHA-256 hash. You have 48 hours; after that the turn passes to the next contributor and
you can be added at the end.

The issue gives you three lines to paste: the input file name, the output file
name and the input file's link. **Open a new terminal window** (on a Mac:
Terminal, from Spotlight with Cmd+Space) and paste them there. It does not
matter which folder the terminal is in. The lines only store the three values
for the commands below, and they last only in that window, so **do every
following step in the same window**. If you close it, paste the three lines
again. For example:

```bash
export IN=tally_0002.zkey
export OUT=tally_0003.zkey
export URL=https://...the link from the issue...
```

**Step 1. Make an empty folder and download the key.**

```bash
mkdir -p ~/tally-ceremony
cd ~/tally-ceremony
curl -L -o "$IN" "$URL"
```

curl shows a progress table while it downloads. A finished download looks like
this (speed and time vary; the size is about 1.7 MB):

```text
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100 1724k  100 1724k    0     0   408k      0  0:00:04  0:00:04 --:--:--  408k
```

Both percentage columns should read `100`. If the size is only a few hundred
bytes, the link was wrong and you saved an error page; step 2 catches this too.

**Step 2. Check you got exactly the right file.** Compare the output with the
SHA-256 hash in the issue. They must match character for character.

On a Mac:

```bash
shasum -a 256 "$IN"
```

On Linux:

```bash
sha256sum "$IN"
```

**Step 3. Contribute.** Replace the name with how you want to appear in the
transcript:

```bash
npx -y snarkjs@0.7.5 zkey contribute "$IN" "$OUT" --name="Your name or handle"
```

It asks: `Enter a random text. (Entropy):`. Type a long string of random keys
and press Enter. You don't need to remember it, and don't save it anywhere.
snarkjs also mixes in 64 random bytes from your operating system. Typing it at
the prompt, rather than passing it with `-e`, keeps it out of your shell history.

It finishes by printing `Contribution Hash:` followed by four lines of
hexadecimal. **Copy those four lines.**

**Step 4. Close that terminal window.** The secret only ever existed in that
command's memory. Neither file contains it. Then open a new terminal window,
go back to the folder, and paste the `IN` and `OUT` lines from your issue again
(the `URL` line is not needed any more). For example, for contribution 3:

```bash
cd ~/tally-ceremony
export IN=tally_0002.zkey
export OUT=tally_0003.zkey
```

Use the two lines from your own issue, not this example.

**Step 5. Send your result.** Zip the new key:

```bash
zip "${OUT%.zkey}.zip" "$OUT"
```

Attach the zip in a comment on your issue (drag it into the comment box),
together with this text:

```text
I contributed to the noir-ckb private tally ceremony as <your name>.
Input: <IN file name> (sha256 <hash from step 2>)
Contribution hash:
<the four lines from step 3>
```

**Step 6 (recommended). Post your contribution hash publicly on your own
account**, then paste the post's link as a comment on your issue. An X post is
ideal; a GitHub Gist or your blog also works. The issue lives in the
coordinator's repository, where the coordinator could edit comments; a post on
your own account cannot be changed by anyone else, so it lets anyone check later
that the hash in the transcript is the one you produced. Don't edit or delete it
afterwards. A post that fits in one X post (under 280 characters):

```text
I contributed to the noir-ckb private tally setup ceremony as <your name> 🔐

Contribution hash:
<your four lines>
```

That's it. You can delete the folder.

### Good practice (optional)

- Use your own computer, not a shared or cloud machine.
- Close other programs while you contribute.
- For extra assurance, verify the key you received before contributing (see
  below). The coordinator does this too, but checking yourself means you don't
  have to trust them.

## Verifying the ceremony yourself

Anyone can check the chain of contributions. With this repository checked out
and the phase 1 file downloaded to `target/ppot_0080_12.ptau`, one command
re-checks every recorded key, every contribution hash and the beacon:

```bash
python3 -B scripts/ceremony-private-tally.py check
```

The same check by hand, with the frozen R1CS file and the phase 1 file named in
`ceremony/private-tally-v2/`:

```bash
npx -y snarkjs@0.7.5 zkey verify circuit.r1cs ppot_0080_12.ptau tally_final.zkey
```

It lists every contribution with its name and hash, then the beacon, and ends
with `ZKey Ok!`. Compare the hashes with the contributors' own posts. To confirm
the phase 1 file itself, run `npx -y snarkjs@0.7.5 powersoftau verify
ppot_0080_12.ptau` (it checks every contribution in the chain) and compare its
BLAKE2b-512 hash with the one published in `ceremony/private-tally-v2/`:

```bash
python3 -c "import hashlib,sys;h=hashlib.blake2b();f=open(sys.argv[1],'rb');[h.update(c) for c in iter(lambda:f.read(1<<20),b'')];print(h.hexdigest())" ppot_0080_12.ptau
```

To confirm the beacon, look up the announced CKB mainnet block height on the
[CKB explorer](https://explorer.nervos.org) and check that its hash is the
beacon value in the transcript.

## What the ceremony does and does not guarantee

- It guarantees that nobody can forge private tally proofs, **as long as at
  least one contributor's randomness was really discarded**.
- It does not make the circuit correct. A bug in the circuit is a bug whatever
  the setup; the circuit's tests and review are separate.
- It covers this one circuit only. Any change to the circuit after it is frozen
  voids the ceremony, and a new one is needed.
- This is a public ceremony for a testnet developer preview, not an audited
  production ceremony.

## Questions

Open an issue on this repository or reply on the
[Nervos Talk update](https://talk.nervos.org/t/noir-ckb-update-what-i-decided-after-the-direction-check-what-you-can-try-today-and-where-this-is-going/10968).
