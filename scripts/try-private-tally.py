#!/usr/bin/env python3
"""Try the private tally on CKB testnet with two commands.

  install   set up everything this needs on this computer (lists it first, asks once)
  run       create your own hidden tally on the testnet deployment and add to it

`run` guides you through each step and asks before anything is sent:
  1. rebuilds the proving setup from the ceremony key on your computer,
  2. checks the live testnet deployment against the public record,
  3. uses (or creates) a testnet-only ckb-cli account,
  4. finds a faucet payment to pay with (or waits for one),
  5. creates your tally at 0, then adds hidden amounts you choose.

Each transaction is shown for review; after you type "y", ckb-cli asks for your
account password (this tool never sees it), the proof is re-checked, the
transaction is sent and recorded, and your private folder is backed up.
Running `run` again continues where you left off. Testnet only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import counter_platform as cp  # noqa: E402
import owned_counter as c  # noqa: E402

ROOT = cp.ROOT
PINS = cp.load()["versions"]
BACKEND_REV = PINS["backend_revision"]
BACKEND_URL = "https://github.com/wamimi/Noir-Groth16.git"
RUST = PINS["rust_host"]
SNARKJS = f"snarkjs@{PINS['snarkjs']}"
CEREMONY = ROOT / "ceremony/private-tally-v2"
PTAU_URL = "https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_12.ptau"
PTAU = ROOT / "target/ppot_0080_12.ptau"
RPC = "https://testnet.ckb.dev"
EXPLORER = "https://testnet.explorer.nervos.org/transaction/"
FAUCET = "https://faucet.nervos.org"
WALLET = Path.home() / ".ckb-cli-noir-ckb-tally"
BACKUPS = Path.home() / "noir-ckb-tally-backups"
TALLY_CKB = 200
MIN_FUNDING = (TALLY_CKB + 61 + 1) * 100_000_000
MAX_DELTA = 2**32 - 1


# ------------------------------------------------------------------ small helpers
def say(text=""):
    print(text, flush=True)


def stage(n, total, text):
    say(f"\n== {n}/{total} {text}")


def ask(question):
    if not sys.stdin.isatty():
        raise RuntimeError("this step needs an interactive terminal")
    return input(question).strip()


def yes(question):
    return ask(question + " [y/N] ").lower() in ("y", "yes")


def run(cmd, env, capture=True, cwd=ROOT, timeout=None):
    """Run a command; with capture=False it uses this terminal (prompts, progress)."""
    cmd = [str(x) for x in cmd]
    if capture:
        q = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return q.returncode, q.stdout + q.stderr
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout).returncode, ""


def script(name, *args):
    return [sys.executable, "-B", ROOT / "scripts" / name, *args]


def blake2b(path):
    h = hashlib.blake2b()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ptau_hash():
    return json.loads((CEREMONY / "transcript.json").read_text())["ptau"]["blake2b"]


def host_env(tools):
    key, entry = cp.detect()
    return key, entry, cp.tool_environment(os.environ, tools, key, entry)


def has_toolchain(version, env):
    code, out = run(["rustup", "toolchain", "list"], env)
    return code == 0 and any(line.split()[0].startswith(version + "-") for line in out.splitlines() if line.strip())


# ------------------------------------------------------------------ checks
def checks(a, env, key, entry):
    """(label, ok, fix) for everything `run` needs. Reads only."""
    def ok(cmd, contains=None, expected=0):
        try:
            code, out = run(cmd, env, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return code == expected and (contains is None or contains in out)

    backend = a.backend
    rust = shutil.which("rustup", path=env.get("PATH")) is not None and has_toolchain(RUST, env)
    return [
        ("Python 3.9 or newer", sys.version_info >= (3, 9), "Install Python 3.9 or newer."),
        ("git", ok(["git", "--version"]), "Install git."),
        ("Node.js and npm", ok(["node", "--version"]) and ok(["npm", "--version"]), "Install Node.js (includes npm)."),
        ("rustup", shutil.which("rustup", path=env.get("PATH")) is not None, "Install rustup from https://rustup.rs, then open a new terminal."),
        (f"Rust {RUST}", rust, "run: python3 -B scripts/try-private-tally.py install"),
        (f"proving backend at {backend}", backend.is_dir() and ok(["git", "-C", backend, "rev-parse", "HEAD"], BACKEND_REV)
         and ok(["git", "-C", backend, "status", "--porcelain"]) and not run(["git", "-C", backend, "status", "--porcelain"], env)[1].strip(),
         "run: python3 -B scripts/try-private-tally.py install"),
        ("Rust libraries downloaded", rust and backend.is_dir()
         and all(ok(["cargo", f"+{RUST}", "metadata", "--locked", "--offline", "--format-version", "1", "--manifest-path", m])
                 for m in (ROOT / "Cargo.toml", backend / "Cargo.toml")),
         "run: python3 -B scripts/try-private-tally.py install"),
        (SNARKJS, ok(["npx", "--offline", SNARKJS, "--version"], SNARKJS, expected=99), "run: python3 -B scripts/try-private-tally.py install"),
        ("Nargo 1.0.0-beta.18", ok(["nargo", "--version"], "1.0.0-beta.18"), "run: python3 -B scripts/try-private-tally.py install"),
        ("ckb-cli", cp.find_tool(a.tools, key, entry, "ckb-cli") is not None, "run: python3 -B scripts/try-private-tally.py install"),
        ("phase 1 file", PTAU.is_file() and blake2b(PTAU) == ptau_hash(), "run: python3 -B scripts/try-private-tally.py install"),
    ]


def report(results):
    for label, good, fix in results:
        say(f"  {'OK     ' if good else 'MISSING'} {label}" + ("" if good else f"\n          {fix}"))
    return all(good for _, good, _ in results)


# ------------------------------------------------------------------ install
def install(a):
    key, entry, env = host_env(a.tools)
    say(f"Computer: {key}")
    base = [r for r in checks(a, env, key, entry)[:4] if not r[1]]
    if base:
        say("\nInstall these first, then run this command again:")
        report(base)
        say("\n  macOS:  brew install git python node\n  Ubuntu: sudo apt install git python3 nodejs npm build-essential pkg-config"
            "\n  Both:   rustup from https://rustup.rs (then open a new terminal)")
        return 1

    def done(cmd, contains=None, expected=0):
        try:
            code, out = run(cmd, env, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return code == expected and (contains is None or contains in out)

    steps = []
    rust = has_toolchain(RUST, env)
    if not rust:
        steps.append((f"install Rust {RUST} with rustup", ["rustup", "toolchain", "install", RUST, "--profile", "minimal"]))
    if not a.backend.exists():
        steps.append((f"clone {BACKEND_URL} into {a.backend}", ["git", "clone", BACKEND_URL, a.backend]))
    if not (a.backend.exists() and done(["git", "-C", a.backend, "rev-parse", "HEAD"], BACKEND_REV)):
        steps.append((f"check out the pinned backend commit {BACKEND_REV[:12]}", ["git", "-C", a.backend, "checkout", "--detach", BACKEND_REV]))
    for manifest in (ROOT / "Cargo.toml", a.backend / "Cargo.toml"):
        if not (rust and manifest.exists() and done(["cargo", f"+{RUST}", "metadata", "--locked", "--offline",
                                                    "--format-version", "1", "--manifest-path", manifest])):
            steps.append((f"download Rust libraries for {manifest.parent.name}",
                          ["cargo", f"+{RUST}", "fetch", "--locked", "--manifest-path", manifest]))
    if not done(["npx", "--offline", SNARKJS, "--version"], SNARKJS, expected=99):
        steps.append((f"download {SNARKJS} into the npm cache", ["npm", "exec", "--yes", f"--package={SNARKJS}", "--", "node", "-e", "0"]))
    missing = [n for n in ("ckb-cli", "nargo") if cp.find_tool(a.tools, key, entry, n) is None]
    if missing:
        steps.append((f"download pinned {' and '.join(missing)} (checked against published hashes)",
                      script("fetch-counter-tools.py", "--out", a.tools, "--tools", ",".join(missing), "--yes")))
    need_ptau = not (PTAU.is_file() and blake2b(PTAU) == ptau_hash())
    if need_ptau:
        steps.append(("download the phase 1 file (4.8 MB, checked against the ceremony's hash)", None))
    if not steps:
        say("\nEverything is already installed.")
        report(checks(a, env, key, entry))
        say("\nReady. Next: python3 -B scripts/try-private-tally.py run")
        return 0

    say("\nThis will:")
    for i, (text, _) in enumerate(steps, 1):
        say(f"  {i}. {text}")
    say("\nNothing is installed system-wide except the Rust toolchain (by rustup), and nothing touches a wallet.")
    if not a.yes and not yes("Continue?"):
        say("Cancelled; nothing changed.")
        return 0
    for i, (text, cmd) in enumerate(steps, 1):
        stage(i, len(steps), text)
        if cmd is None:
            PTAU.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(PTAU_URL, headers={"User-Agent": "noir-ckb/try-private-tally"})
            with urllib.request.urlopen(request, timeout=300) as response:
                data = response.read()
            c.require(hashlib.blake2b(data).hexdigest() == ptau_hash(), "the downloaded phase 1 file has the wrong hash; nothing saved")
            PTAU.write_bytes(data)
            continue
        code, _ = run(cmd, env, capture=False)
        c.require(code == 0, f"step failed: {text}")
    key, entry, env = host_env(a.tools)
    say("\nChecking everything:")
    if not report(checks(a, env, key, entry)):
        return 1
    say("\nReady. Next: python3 -B scripts/try-private-tally.py run")
    return 0


# ------------------------------------------------------------------ run: accounts and funding
def ckb_cli(a, key, entry):
    path = cp.find_tool(a.tools, key, entry, "ckb-cli")
    c.require(path is not None, "ckb-cli is missing; run: python3 -B scripts/try-private-tally.py install")
    return path


def accounts(cli, env):
    code, out = run([cli, "--output-format", "json", "account", "list"], env)
    c.require(code == 0, "ckb-cli account list failed: " + out[-400:])
    return [dict(lock_arg=x["lock_arg"], address=x["address"]["testnet"]) for x in json.loads(out or "[]")]


def choose_account(cli, env, session):
    if session.get("lock_arg"):
        return session["lock_arg"], session["address"]
    found = accounts(cli, env)
    if not found:
        say(f"No account in {env['CKB_CLI_HOME']} yet. ckb-cli will now create a testnet-only one.")
        say("Choose a password and keep it to yourself. This tool never sees it.\n")
        for attempt in range(3):
            run([cli, "account", "new"], env, capture=False)
            found = accounts(cli, env)
            if found:
                break
            if attempt < 2:
                say("The account was not created (the two passwords must match). Try again.\n")
        c.require(found, "account creation did not finish; run this command again")
    if len(found) == 1:
        return found[0]["lock_arg"], found[0]["address"]
    for i, x in enumerate(found, 1):
        say(f"  {i}. {x['address']}")
    pick = ask(f"Which account should pay (1-{len(found)})? ")
    c.require(pick.isdigit() and 1 <= int(pick) <= len(found), "no such account")
    x = found[int(pick) - 1]
    return x["lock_arg"], x["address"]


def funding_cells(lock_arg):
    """Plain, empty Cells of the account with enough CKB, largest first."""
    key = dict(script=c.owner(lock_arg), script_type="lock",
               filter=dict(output_data_len_range=["0x0", "0x1"], script_len_range=["0x0", "0x1"]))
    cells = c.rpc(RPC, "get_cells", [key, "asc", "0x64"])["objects"]
    good = [x for x in cells if x["output"]["type"] is None and int(x["output"]["capacity"], 16) >= MIN_FUNDING]
    good.sort(key=lambda x: -int(x["output"]["capacity"], 16))
    return [f"{x['out_point']['tx_hash']}:{int(x['out_point']['index'], 16)}" for x in good]


def wait_for_funding(lock_arg, address, exclude=()):
    shown = False
    while True:
        cells = [p for p in funding_cells(lock_arg) if p not in exclude]
        if cells:
            return cells[0]
        if not shown:
            say(f"\nThis account needs a payment of at least {MIN_FUNDING // 100_000_000} testnet CKB.")
            say(f"  1. Open {FAUCET}\n  2. Paste this address and request CKB:\n\n     {address}\n")
            say("Waiting for it to arrive (checking every 15 seconds; press Ctrl+C to stop and continue later).")
            shown = True
        time.sleep(15)


# ------------------------------------------------------------------ run: one transaction
def transact(a, env, cli, owner, work, tx_path, label, session, save):
    """Review, sign (ckb-cli password prompt), re-check, send once, confirm, back up."""
    if session.get("sent"):
        tx_hash = session["sent"]
        say(f"Resuming: {label} was already sent as {tx_hash}; waiting for it to be recorded.")
    else:
        say(f"\nReview the {label} transaction:\n")
        code, _ = run([cli, "--url", RPC, "tx", "info", "--tx-file", tx_path], env, capture=False)
        c.require(code == 0, "could not show the transaction")
        if not yes(f"\nSign and send this {label}?"):
            raise KeyboardInterrupt
        for attempt in range(3):
            run([cli, "--url", RPC, "tx", "sign-inputs", "--tx-file", tx_path, "--from-account", owner,
                 "--add-signatures", "--skip-check"], env, capture=False)
            if c.read(tx_path).get("signatures"):
                break
            say("Not signed (wrong password?). Try again." if attempt < 2 else "")
        c.require(c.read(tx_path).get("signatures"), "the transaction was not signed; run this command again to retry")
        code, out = run(script("private-tally-client.py", "check", "--work", work), env)
        c.require(code == 0 and '"status": "checked"' in out, "the signed transaction failed its proof check; it was not sent:\n" + out[-600:])
        say("Proof re-checked after signing. Sending ...")
        code, out = run([cli, "--url", RPC, "tx", "send", "--tx-file", tx_path, "--skip-check"], env)
        hashes = [t for t in out.split() if t.startswith("0x") and len(t) == 66]
        c.require(code == 0 and hashes, "sending failed; nothing was recorded:\n" + out[-600:])
        tx_hash = hashes[-1]
        session["sent"] = tx_hash
        save()
        say(f"Sent: {EXPLORER}{tx_hash}")
    say("Waiting for the transaction to be committed ...")
    for _ in range(60):
        code, out = run(script("private-tally-client.py", "confirm", "--work", work, "--hash", tx_hash), env)
        if code == 0:
            break
        c.require("not committed yet" in out, "recording failed:\n" + out[-600:])
        time.sleep(10)
    else:
        raise RuntimeError(f"not committed after 10 minutes; run this command again later (do not send again). Transaction: {tx_hash}")
    session.pop("sent", None)
    session.setdefault("history", []).append(dict(operation=label, tx_hash=tx_hash))
    save()
    versions = len(list((work / "private").glob("state-*.json")))
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    dest = BACKUPS / f"{work.parent.name}-v{versions}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    code, out = run(script("private-tally-client.py", "backup", "--work", work, "--to", dest), env)
    c.require(code == 0, "backup failed: " + out[-400:])
    say(f"Recorded. Private state version {versions}, backed up to {dest}")
    return tx_hash


def pending_tx(work):
    p = work / "private" / "pending.json"
    return Path(json.loads(p.read_text())["tx"]) if p.exists() else None


# ------------------------------------------------------------------ run
def run_flow(a):
    key, entry, env = host_env(a.tools)
    env.setdefault("CKB_CLI_HOME", str(WALLET))
    w = a.work.resolve()
    c.require(w.is_relative_to((ROOT / "target").resolve()), "--work must be below this checkout's target/")
    w.mkdir(parents=True, exist_ok=True)
    session_path = w / "session.json"
    session = json.loads(session_path.read_text()) if session_path.exists() else {}

    def save():
        session_path.write_text(json.dumps(session, indent=2) + "\n")

    stage(1, 5, "checking this computer")
    if not report(checks(a, env, key, entry)):
        say("\nRun: python3 -B scripts/try-private-tally.py install")
        return 1
    cli = ckb_cli(a, key, entry)

    stage(2, 5, "proving setup from the ceremony key (a few minutes the first time)")
    setup = w / "setup"
    manifest = setup / "manifest.json"
    if not (manifest.exists() and c.read(manifest).get("status") == "passed"):
        c.require(not setup.exists(), f"{setup} is from an unfinished run; choose a new --work folder")
        code, _ = run(script("setup-private-tally.py", "--out", setup, "--backend", a.backend, "--ptau", PTAU,
                             "--ceremony", CEREMONY), env, capture=False)
        c.require(code == 0, "the setup did not pass; see the output above")
    say("Setup passed: the circuit matches the ceremony, and the ceremony key verified.")

    stage(3, 5, "checking the live testnet deployment")
    join = w / "join"
    if not (join / "deployment.json").exists():
        c.require(not join.exists(), f"{join} is from an unfinished run; choose a new --work folder")
        code, out = run(script("join-private-tally.py", "init", "--setup", setup, "--out", join, "--rpc", RPC), env)
        c.require(code == 0, "the deployment check failed:\n" + out[-800:])
    say("Verified: the deployed verification key is the one your setup derived from the ceremony key.")

    stage(4, 5, "your testnet account")
    owner, address = choose_account(cli, env, session)
    session.update(lock_arg=owner, address=address, wallet=env["CKB_CLI_HOME"])
    save()
    say(f"Account: {address}\nWallet folder: {env['CKB_CLI_HOME']} (keep it private)")

    stage(5, 5, "your tally")
    tally = w / "my-tally"
    if not (tally / "private").exists():
        funding = wait_for_funding(owner, address)
        say(f"\nPaying with {funding}. {TALLY_CKB} CKB will be locked in your tally permanently (no withdrawal).")
        say("Your secret key is created only on this computer. If it is lost, the tally is frozen forever.")
        code, out = run(script("private-tally-client.py", "create", "--release", join / "release.json",
                               "--deployment", join / "deployment.json", "--work", tally, "--rpc", RPC,
                               "--owner", owner, "--funding", funding), env)
        c.require(code == 0, "preparing the creation failed:\n" + out[-800:])
        say("Proof made on this computer: your new tally starts at 0.")
    tx = pending_tx(tally)
    if tx is not None:
        transact(a, env, cli, owner, tally, tx, tx.stem, session, save)

    while True:
        say("")
        answer = ask(f"Add a hidden amount? Type a whole number from 0 to {MAX_DELTA:,} (0 = cover update), or press Enter to finish: ")
        if not answer:
            break
        answer = answer.replace(",", "")
        if not answer.isdigit() or int(answer) > MAX_DELTA:
            say("That is not a whole number in range.")
            continue
        used = [h["tx_hash"] for h in session.get("history", [])]
        funding = wait_for_funding(owner, address, exclude=[f"{h}:0" for h in used])
        code, out = run(script("private-tally-client.py", "update", "--work", tally, "--funding", funding,
                               "--delta", answer, "--replace-pending"), env)
        c.require(code == 0, "preparing the update failed:\n" + out[-800:])
        say("Proof made on this computer: new hidden value = old hidden value + your amount.")
        transact(a, env, cli, owner, tally, pending_tx(tally), pending_tx(tally).stem, session, save)

    code, out = run(script("private-tally-client.py", "status", "--work", tally, "--show-value"), env)
    status = json.loads(out) if code == 0 else {}
    say("\nDone.")
    say(f"Your tally's value (read from your private folder, not the chain): {status.get('value')}")
    say("On chain, anyone sees only commitments and proofs:")
    for h in session.get("history", []):
        say(f"  {h['operation']:10} {EXPLORER}{h['tx_hash']}")
    say(f"\nPrivate folder: {tally / 'private'}  Backups: {BACKUPS}\nNever share these, your password or {env['CKB_CLI_HOME']}.")
    say("Run this command again any time to add more.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("install", "run"))
    p.add_argument("--backend", type=Path, default=ROOT.parent / "Noir-Groth16")
    p.add_argument("--tools", type=Path, default=ROOT / "target/counter-tools")
    p.add_argument("--work", type=Path, default=ROOT / "target/try-private-tally")
    p.add_argument("--yes", action="store_true", help="install without asking")
    a = p.parse_args(argv)
    a.backend, a.tools = a.backend.resolve(), a.tools.resolve()
    try:
        return install(a) if a.command == "install" else run_flow(a)
    except KeyboardInterrupt:
        say("\nStopped. Nothing more was sent. Run the same command again to continue.")
        return 1
    except (RuntimeError, ValueError, OSError, cp.PlatformError, c.RpcError) as error:
        say(f"\nerror: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
