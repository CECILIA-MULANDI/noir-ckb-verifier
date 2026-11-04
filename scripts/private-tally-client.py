#!/usr/bin/env python3
"""Client for noir-ckb/private-tally/v2 (docs/private-tally-v2-spec.md).

Prepares unsigned transactions; never signs or broadcasts. Signing is done with
the user's own ckb-cli account (only fee/funding inputs need a signature: the
tally Cell is held by the always-success guard Lock and authorized by the proof).

  build          build the Type Script for a network and record a release
  prepare-deploy deploy the Type Script, verification key and guard Lock code
  confirm-deploy record a committed deployment
  create         start a tally at 0 (new private folder; prints a backup warning)
  update         add a hidden amount (0 allowed) with a fresh proof
  check          re-check a prepared or signed transaction against its proof
  confirm        record a committed create/update in the private state
  status         public facts about the tally (--show-value prints the value)
  backup         copy the private folder (keeps 0700/0600 permissions)

Work folder layout: <work>/private (0700: key, blinding factors, state, pending
operation) and <work>/public (transactions, proofs, receipts). Every command
ends with a leak scan of <work>/public.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import counter_platform as cp  # noqa: E402
import owned_counter as c  # noqa: E402
import private_tally as pt  # noqa: E402

ROOT = pt.ROOT
SNARK = ["npx", "--offline", "snarkjs@0.7.5"]
DEFAULT_CAPACITY = 200 * 100_000_000
DEFAULT_FEE = 1_000_000
MAX_FEE = 100_000_000


# ------------------------------------------------------------------ helpers
def always_success():
    return next((cp.cargo_home() / "registry/src").glob("*/ckb-always-success-script-0.0.1/specs/cells/always_success")).read_bytes()


def release(path):
    r = c.read(path)
    c.require(r.get("profile") == pt.PROFILE, "release is not a private tally release")
    for name, item in r["artifacts"].items():
        c.require(c.sha(item["path"]) == item["sha256"], f"artifact changed: {name}")
    return r


def save_tx(path, tx):
    c.save_tx(path, tx)


def tally_from_tx(tx, code_hash):
    idx = [i for i, o in enumerate(tx["outputs"]) if o["type"] and o["type"]["code_hash"] == code_hash]
    c.require(len(idx) == 1, "expected exactly one tally output")
    return idx[0]


class Work:
    def __init__(self, path, create=False):
        self.path = Path(path).resolve()
        if create:
            self.path.mkdir(mode=0o700, parents=True, exist_ok=False)
            (self.path / "public").mkdir()
            self.private = pt.PrivateDir(self.path / "private", create=True)
        else:
            self.private = pt.PrivateDir(self.path / "private")
        self.public = self.path / "public"
        self.state = pt.TallyState(self.private)

    def config(self):
        return json.loads((self.public / "config.json").read_text())

    def pending(self):
        p = self.private.path / "pending.json"
        c.require(p.exists(), "no prepared operation; run create or update first")
        return json.loads(self.private.read("pending.json"))

    def secrets(self):
        values = set()
        for v in self.state.versions():
            s = json.loads(self.private.read(f"state-{v:04d}.json"))
            values |= {int(s["key"]), int(s["blinding"])}
        p = self.private.path / "pending.json"
        if p.exists():
            s = json.loads(self.private.read("pending.json"))
            values |= {int(s["key"]), int(s["blinding"])}
        return values

    def leak_scan(self):
        hits = pt.leak_scan(self.public, self.secrets())
        c.require(not hits, f"SECRET MATERIAL FOUND in public files: {hits}. Do not share this folder.")


def prove(work, cfg, name, values):
    """Fresh proof; witnesses and inputs exist only inside the private folder and are deleted."""
    r = release(cfg["release"])
    setup = Path(r["setup"])
    m = c.read(setup / "manifest.json")
    zkey = m.get("zkey", "development.zkey")
    for f in (zkey, "verification_key.json", "circuit/private_tally_v2.json"):
        c.require(c.sha(setup / f) == m["artifacts"][f], f"proving artifact changed: {f}")
    cli = setup / "backend-target/debug/noir-cli"
    c.require(c.sha(cli) == m["backend_binary_sha256"], "backend binary changed")
    scratch = work.private.path / "proving"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(mode=0o700)
    kept = work.public / "proofs" / name
    kept.mkdir(parents=True, exist_ok=False)
    try:
        fd = os.open(scratch / "inputs.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({k: str(v) for k, v in values.items()}, f)

        def run(cmd, quiet=False):
            q = subprocess.run([str(x) for x in cmd], cwd=ROOT, capture_output=True, text=True, timeout=900)
            c.require(q.returncode == 0 and "[ERROR]" not in q.stdout,
                      "proving step failed" + ("" if quiet else ": " + q.stdout[-800:] + q.stderr[-800:]))
            return q.stdout
        run([cli, "interop", setup / "circuit/private_tally_v2.json", scratch / "inputs.json", "--out", scratch / "interop"], quiet=True)
        c.require(c.sha(scratch / "interop/circuit.r1cs") == m["artifacts"]["circuit.r1cs"], "R1CS differs from setup")
        run(SNARK + ["wtns", "check", scratch / "interop/circuit.r1cs", scratch / "interop/witness.wtns"], quiet=True)
        run(SNARK + ["groth16", "prove", setup / zkey, scratch / "interop/witness.wtns",
                     kept / "proof.json", kept / "public.json"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    public = [str(values[k]) for k in ("c_old", "c_new", "ctx_lo", "ctx_hi")]
    c.require(c.read(kept / "public.json") == public, "public ordering mismatch")
    run_ok = subprocess.run(SNARK + ["groth16", "verify", str(setup / "verification_key.json"), str(kept / "public.json"),
                                     str(kept / "proof.json")], capture_output=True, text=True, timeout=120)
    c.require(run_ok.returncode == 0 and "OK!" in run_ok.stdout, "fresh proof did not verify")
    wrong = list(public)
    wrong[2] = str(int(wrong[2]) + 1)
    c.write(kept / "wrong.json", wrong)
    q = subprocess.run(["cargo", "+1.95.0", "run", "--locked", "--offline", "-p", "artifact-adapter", "--bin",
                        "noir-ckb-adapter", "--", "--vk", str(setup / "verification_key.json"), "--proof",
                        str(kept / "proof.json"), "--public", str(kept / "public.json"), "--negative-public",
                        str(kept / "wrong.json"), "--out", str(kept / "adapter")],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    c.require(q.returncode == 0, "adapter failed: " + q.stderr[-800:])
    c.require((kept / "adapter/vk.mol.bin").read_bytes() == Path(r["artifacts"]["vk"]["path"]).read_bytes(),
              "proof was made with a different verification key")
    return (kept / "adapter/witness.mol.bin").read_bytes()


def deps(r, deployment):
    out = [r["policy"]["owner_dep"]]
    for name in ("type", "vk", "guard"):
        out.append(c.dep(deployment[name]))
    return out


def check_deployment(cfg, r):
    deployment = c.read(cfg["deployment"])
    c.require(deployment["release_sha256"] == c.sha(cfg["release"]), "deployment belongs to another release")
    for name in ("type", "vk", "guard"):
        cell = c.live(cfg["rpc"], deployment[name])
        c.require(c.hx(c.h(c.raw(cell["data"]["content"]))) == r["artifacts"][name]["data_hash"],
                  f"deployed {name} bytes differ from the release")
    return deployment


def funding_cell(cfg, owner_lock, point):
    f = c.live(cfg["rpc"], point)
    c.require(f["output"]["lock"] == owner_lock and f["output"]["type"] is None and f["data"]["content"] == "0x",
              "funding must be one empty Cell owned by your account")
    return int(f["output"]["capacity"], 16)


def print_steps(work, tx_path, cfg, update):
    rel = os.path.relpath(tx_path, Path.cwd())
    w = os.path.relpath(work.path, Path.cwd())
    rpc = cfg["rpc"]
    steps = [
        ("Select the transaction file", f'export TALLY_TX="{rel}"'),
        ("Review it", f'"$COUNTER_CLI" --url {rpc} tx info --tx-file "$TALLY_TX"'),
        ("Sign the funding input with your account (password prompt)",
         f'"$COUNTER_CLI" --url {rpc} tx sign-inputs --tx-file "$TALLY_TX" --from-account "$COUNTER_OWNER" --add-signatures --skip-check'),
        ("Re-check the proof after signing", f"python3 -B scripts/private-tally-client.py check --work {w}"),
        ("Send it (only once)", f'"$COUNTER_CLI" --url {rpc} tx send --tx-file "$TALLY_TX" --skip-check'),
        ("Record it: replace 0xPASTE_THE_HASH with the hash step 5 printed",
         f"python3 -B scripts/private-tally-client.py confirm --work {w} --hash 0xPASTE_THE_HASH"),
    ]
    print(f"\nThe {'update' if update else 'creation'} transaction is prepared but NOT signed or sent.")
    print("Run these yourself, one at a time:\n")
    for i, (title, cmd) in enumerate(steps, 1):
        print(f"  {i}. {title}:\n\n     {cmd}\n")


# ------------------------------------------------------------------ commands
def cmd_build(a):
    p = c.read(a.policy)
    setup = a.setup.resolve()
    m = c.read(setup / "manifest.json")
    c.require(m.get("status") == "passed" and m.get("profile") == pt.PROFILE, "setup did not pass for this profile")
    for f, digest in m["artifacts"].items():
        c.require(c.sha(setup / f) == digest, f"setup artifact changed: {f}")
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    guard_bytes = always_success()
    (out / "guard-always-success").write_bytes(guard_bytes)
    vk = setup / "adapter/vk.mol.bin"
    shutil.copyfile(vk, out / "vk.mol.bin")
    env = os.environ.copy()
    env.update(TALLY_NETWORK_DOMAIN=p["network_domain"], TALLY_GUARD_DATA_HASH=c.hx(c.h(guard_bytes)),
               TALLY_VK_DATA_HASH=c.hx(c.h(vk.read_bytes())), CARGO_TARGET_DIR=str(out / "target"))
    compiler = cp.find_clang(env)
    if compiler:
        env.update(CLANG=compiler, CC_riscv64imac_unknown_none_elf=compiler)
    env["RUSTFLAGS"] = (f"-C target-feature=-a --remap-path-prefix={cp.cargo_home(env)}/registry/src=/cargo-registry "
                        f"--remap-path-prefix={cp.cargo_home(env)}/git/checkouts=/cargo-git "
                        f"--remap-path-prefix={cp.rustup_home(env)}/toolchains=/rustup-toolchains --remap-path-prefix={ROOT}=/build")
    cmd = ["cargo", "+1.94.1", "build", "--locked", "--offline", "--release", "--target", "riscv64imac-unknown-none-elf",
           "-p", "private-tally"]
    q = subprocess.run(cmd, cwd=ROOT / "contracts", env=env, capture_output=True, text=True)
    c.write(out / "build.json", dict(command=cmd, exit=q.returncode, stdout=q.stdout, stderr=q.stderr,
                                     env={k: v for k, v in env.items() if k.startswith("TALLY_") or k in ("RUSTFLAGS",)}))
    c.require(q.returncode == 0, q.stdout + q.stderr)
    shutil.copyfile(out / "target/riscv64imac-unknown-none-elf/release/private-tally", out / "private-tally")
    artifacts = {n: dict(path=str(f), sha256=c.sha(f), data_hash=c.hx(c.h(f.read_bytes())), bytes=f.stat().st_size)
                 for n, f in (("type", out / "private-tally"), ("vk", out / "vk.mol.bin"), ("guard", out / "guard-always-success"))}
    policy = dict(p, profile=pt.PROFILE, guard_data_hash=artifacts["guard"]["data_hash"], vk_data_hash=artifacts["vk"]["data_hash"])
    c.write(out / "release.json", dict(profile=pt.PROFILE, policy=policy, setup=str(setup), artifacts=artifacts,
                                       development_only="ceremony" not in m,
                                       ceremony=m.get("ceremony")))
    print(out / "release.json")


def cmd_prepare_deploy(a):
    r = release(a.release)
    c.network(a.rpc, r["policy"]["network_domain"])
    lock = c.owner(a.owner)
    points = [c.op(f) for f in a.funding]
    c.require(len({(p["tx_hash"], p["index"]) for p in points}) == len(points), "the same funding Cell was given twice")
    # Each funding Cell must be a plain, empty Cell of the account, so code or
    # application Cells (for example an existing deployment) are never spent.
    total = sum(funding_cell(dict(rpc=a.rpc), lock, p) for p in points)
    tx = c.base(r["policy"]["owner_dep"])
    tx["inputs"] = [dict(since="0x0", previous_output=p) for p in points]
    for name in ("type", "vk", "guard"):
        d = c.hx(Path(r["artifacts"][name]["path"]).read_bytes())
        o = c.output(0, lock)
        o["capacity"] = hex(c.minimum(o, d))
        tx["outputs"].append(o)
        tx["outputs_data"].append(d)
    change = total - sum(int(o["capacity"], 16) for o in tx["outputs"]) - a.fee
    tx["outputs"].append(c.output(change, lock))
    tx["outputs_data"].append("0x")
    c.require(change >= c.minimum(tx["outputs"][-1], "0x"), "funding Cells too small for the deployment")
    tx["witnesses"] = [c.witness()] + ["0x"] * (len(points) - 1)
    save_tx(a.out, tx)
    print(json.dumps(dict(transaction_file=str(a.out), outputs=["type", "vk", "guard", "change"], signs=False, broadcasts=False)))


def cmd_confirm_deploy(a):
    r = release(a.release)
    c.network(a.rpc, r["policy"]["network_domain"])
    expected = c.read(a.tx)["transaction"]
    q = c.rpc(a.rpc, "get_transaction", [a.hash])
    c.require(q and q["tx_status"]["status"] == "committed", "transaction not committed yet")
    c.require(all(q["transaction"][k] == expected[k] for k in expected if k != "witnesses"), "committed transaction differs")
    receipt = dict(status="committed-and-cells-checked", tx_hash=a.hash, release_sha256=c.sha(a.release))
    for i, name in enumerate(("type", "vk", "guard")):
        point = dict(tx_hash=a.hash, index=hex(i))
        cell = c.live(a.rpc, point)
        c.require(c.hx(c.h(c.raw(cell["data"]["content"]))) == r["artifacts"][name]["data_hash"], f"{name} cell mismatch")
        receipt[name] = point
    receipt["change"] = dict(tx_hash=a.hash, index="0x3")
    c.write(a.out, receipt)
    print(json.dumps(receipt, indent=2))


def build_operation(work, cfg, r, deployment, *, creation, funding, delta=0):
    lock = c.owner(cfg["owner"])
    guard = pt.guard_lock(c.raw(r["artifacts"]["guard"]["data_hash"]))
    code_hash = c.raw(r["artifacts"]["type"]["data_hash"])
    network = c.raw(r["policy"]["network_domain"])
    funding_total = funding_cell(cfg, lock, funding)
    tx = c.base(r["policy"]["owner_dep"])
    tx["cell_deps"] = deps(r, deployment)
    blinding = pt.new_secret()
    if creation:
        key, value_old, r_old, c_old = pt.new_secret(), 0, 0, 0
        tx["inputs"] = [dict(since="0x0", previous_output=funding)]
        tscript = pt.type_script(code_hash, pt.type_id(tx["inputs"][0], 0))
        capacity = cfg["capacity"]
        outpoint = bytes(36)
        total = funding_total
    else:
        st = work.state.latest()
        key, value_old, r_old, c_old = int(st["key"]), int(st["value"]), int(st["blinding"]), int(st["commitment"])
        point = json.loads(work.private.read(f"tally-{st['seq']:04d}.json"))["tally"]
        cell = c.live(cfg["rpc"], point)
        o = cell["output"]
        c.require(o["lock"] == guard and o["type"]["code_hash"] == c.hx(code_hash) and o["type"]["hash_type"] == "data1",
                  "the recorded tally Cell is not a tally under this release")
        c.require(c.raw(cell["data"]["content"]) == pt.tally_data(c_old),
                  "the live tally commitment differs from your private state (restore the right backup?)")
        tx["inputs"] = [dict(since="0x0", previous_output=point), dict(since="0x0", previous_output=funding)]
        tscript = o["type"]
        capacity = int(o["capacity"], 16)
        outpoint = c.outpoint(point)
        total = funding_total + capacity
    c.require(0 <= delta <= pt.MAX_DELTA, f"delta must be between 0 and {pt.MAX_DELTA}")
    value_new = value_old + delta
    c.require(value_new < 2**64, "tally would exceed 64 bits")
    circuit = pt.Circuit(work.private, cfg.get("nargo", "nargo"))
    try:
        circuit.compile()
        c_new = circuit.commitment(value_new, blinding, key)
    finally:
        shutil.rmtree(circuit.ws, ignore_errors=True)
    lo, hi = pt.context(network, tscript, 0 if creation else 1, outpoint, c_old, c_new, guard, capacity)
    name = "creation" if creation else f"update-{len(work.state.versions())}"
    # Only reachable for an unsent prepared operation (update --replace-pending).
    (work.public / f"{name}.json").unlink(missing_ok=True)
    shutil.rmtree(work.public / "proofs" / name, ignore_errors=True)
    payload = prove(work, cfg, name, dict(value_old=value_old, r_old=r_old, key=key, delta=delta, r_new=blinding,
                                          c_old=c_old, c_new=c_new, ctx_lo=lo, ctx_hi=hi))
    tx["outputs"] = [c.output(capacity, guard, tscript)]
    tx["outputs_data"] = [c.hx(pt.tally_data(c_new))]
    change = total - capacity - cfg["fee"]
    tx["outputs"].append(c.output(change, lock))
    tx["outputs_data"].append("0x")
    for o, d in zip(tx["outputs"], tx["outputs_data"]):
        c.require(int(o["capacity"], 16) >= c.minimum(o, d), "insufficient funding / occupied capacity")
    if creation:
        tx["witnesses"] = [pt.witness_args(output_type=payload)]
    else:
        tx["witnesses"] = [pt.witness_args(input_type=payload), c.witness()]
    tx_path = work.public / f"{name}.json"
    save_tx(tx_path, tx)
    record = dict(state_version=pt.STATE_VERSION, profile=pt.PROFILE, label=name, key=str(key), value=str(value_new),
                  blinding=str(blinding), commitment=str(c_new), tx=str(tx_path), proof=str(work.public / "proofs" / name),
                  public=[str(c_old), str(c_new), str(lo), str(hi)])
    (work.private.path / "pending.json").unlink(missing_ok=True)
    work.private.write_new("pending.json", json.dumps(record, indent=2) + "\n")
    return tx_path


def cmd_create(a):
    r = release(a.release)
    c.network(a.rpc, r["policy"]["network_domain"])
    work = Work(a.work, create=True)
    cfg = dict(release=str(a.release.resolve()), deployment=str(a.deployment.resolve()), rpc=a.rpc, owner=a.owner,
               capacity=a.capacity_ckb * 100_000_000, fee=a.fee, nargo=a.nargo)
    c.write(work.public / "config.json", cfg)
    deployment = check_deployment(cfg, r)
    c.owner(a.owner)
    print(pt.CREATION_WARNING)
    print(f"{a.capacity_ckb} CKB will be permanently locked in the tally Cell (no withdrawal).\n")
    tx_path = build_operation(work, cfg, r, deployment, creation=True, funding=c.op(a.funding))
    work.leak_scan()
    print_steps(work, tx_path, cfg, update=False)


def cmd_update(a):
    work = Work(a.work)
    cfg = work.config()
    r = release(cfg["release"])
    c.network(cfg["rpc"], r["policy"]["network_domain"])
    c.require(not (work.private.path / "pending.json").exists() or a.replace_pending,
              "an operation is already prepared; confirm it, or pass --replace-pending if it was never sent")
    deployment = check_deployment(cfg, r)
    tx_path = build_operation(work, cfg, r, deployment, creation=False, funding=c.op(a.funding), delta=a.delta)
    work.leak_scan()
    print_steps(work, tx_path, cfg, update=True)


def cmd_check(a):
    work = Work(a.work)
    cfg = work.config()
    r = release(cfg["release"])
    c.network(cfg["rpc"], r["policy"]["network_domain"])
    pend = work.pending()
    tx = c.read(pend["tx"])["transaction"]
    code_hash = r["artifacts"]["type"]["data_hash"]
    i = tally_from_tx(tx, code_hash)
    out = tx["outputs"][i]
    guard = pt.guard_lock(c.raw(r["artifacts"]["guard"]["data_hash"]))
    c.require(out["lock"] == guard, "tally output is not under the guard Lock")
    c_new = int.from_bytes(c.raw(tx["outputs_data"][i])[1:], "little")
    c.require(str(c_new) == pend["commitment"], "tally output differs from the prepared commitment")
    tally_inputs = []
    total = 0
    for k, inp in enumerate(tx["inputs"]):
        cell = c.live(cfg["rpc"], inp["previous_output"])
        total += int(cell["output"]["capacity"], 16)
        if cell["output"]["type"] and cell["output"]["type"]["code_hash"] == code_hash:
            tally_inputs.append((k, inp, cell))
        else:
            c.require(cell["output"]["lock"] == c.owner(cfg["owner"]), "a funding input is not owned by your account")
    network = c.raw(r["policy"]["network_domain"])
    if tally_inputs:
        c.require(len(tally_inputs) == 1, "more than one tally input")
        k, inp, cell = tally_inputs[0]
        c_old = int.from_bytes(c.raw(cell["data"]["content"])[1:], "little")
        c.require(cell["output"]["capacity"] == out["capacity"], "tally capacity changed")
        lo, hi = pt.context(network, out["type"], 1, c.outpoint(inp["previous_output"]), c_old, c_new, out["lock"],
                            int(out["capacity"], 16))
        payload = c.witness_parts(tx["witnesses"][k])[1][4:]
    else:
        c_old = 0
        lo, hi = pt.context(network, out["type"], 0, bytes(36), 0, c_new, out["lock"], int(out["capacity"], 16))
        payload = c.witness_parts(tx["witnesses"][i])[2][4:]
    expected = [str(c_old), str(c_new), str(lo), str(hi)]
    c.require(expected == pend["public"], "transaction no longer matches the proof's statement; prepare again")
    c.require(payload == (Path(pend["proof"]) / "adapter/witness.mol.bin").read_bytes(), "proof witness changed or misplaced")
    c.require(payload[-128:] == pt.public_bytes(*map(int, expected)), "payload public vector differs")
    q = subprocess.run(SNARK + ["groth16", "verify", str(Path(r["setup"]) / "verification_key.json"),
                                str(Path(pend["proof"]) / "public.json"), str(Path(pend["proof"]) / "proof.json")],
                       capture_output=True, text=True, timeout=120)
    c.require(q.returncode == 0 and "OK!" in q.stdout, "proof verification failed")
    fee = total - sum(int(o["capacity"], 16) for o in tx["outputs"])
    c.require(0 <= fee <= MAX_FEE, "fee outside the client limit")
    work.leak_scan()
    print(json.dumps(dict(status="checked", operation=pend["label"], commitment_old=str(c_old), commitment_new=str(c_new),
                          fee_shannons=fee, signs=False, broadcasts=False)))


def cmd_confirm(a):
    work = Work(a.work)
    cfg = work.config()
    r = release(cfg["release"])
    c.network(cfg["rpc"], r["policy"]["network_domain"])
    pend = work.pending()
    expected = c.read(pend["tx"])["transaction"]
    q = c.rpc(cfg["rpc"], "get_transaction", [a.hash])
    c.require(q and q["tx_status"]["status"] == "committed", "not committed yet; wait and run confirm again (do not resend)")
    actual = q["transaction"]
    c.require(all(actual[k] == expected[k] for k in expected if k != "witnesses"), "committed transaction differs from the prepared one")
    i = tally_from_tx(expected, r["artifacts"]["type"]["data_hash"])
    point = dict(tx_hash=a.hash, index=hex(i))
    cell = c.live(cfg["rpc"], point)
    c.require(cell["output"] == expected["outputs"][i] and c.raw(cell["data"]["content"]) == pt.tally_data(int(pend["commitment"])),
              "live tally Cell differs from the prepared one")
    record = work.state.append(key=int(pend["key"]), value=int(pend["value"]), blinding=int(pend["blinding"]),
                               commitment=int(pend["commitment"]), label=pend["label"])
    # Record where the tally now lives (state files are immutable, so a sidecar holds the OutPoint).
    work.private.write_new(f"tally-{record['seq']:04d}.json", json.dumps(dict(tally=point, tx_hash=a.hash)) + "\n")
    (work.private.path / "pending.json").unlink()
    c.write(work.public / f"{pend['label']}-receipt.json", dict(status="committed-and-cells-checked", tx_hash=a.hash,
                                                                 tally=point, operation=pend["label"]))
    work.leak_scan()
    print(f"Confirmed {pend['label']}. Tally Cell {a.hash}:{i}. Your private state is version {record['seq']}; "
          "back the folder up with the backup command.")


def cmd_status(a):
    work = Work(a.work)
    st = work.state.latest()
    loc = json.loads(work.private.read(f"tally-{st['seq']:04d}.json"))
    info = dict(profile=pt.PROFILE, state_version=st["seq"], operation=st["label"], tally=loc["tally"],
                commitment=hex(int(st["commitment"])), pending=(work.private.path / "pending.json").exists())
    if a.show_value:
        info["value"] = int(st["value"])
    print(json.dumps(info, indent=2))


def cmd_backup(a):
    work = Work(a.work)
    dest = pt.backup(work.private, a.to)
    print(f"Private state copied to {dest} (0700). Keep it offline and never share it.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build")
    s.add_argument("--policy", type=Path, required=True, help="owned_counter.py preflight output for the network")
    s.add_argument("--setup", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.set_defaults(func=cmd_build)
    s = sub.add_parser("prepare-deploy")
    for k in ("release", "out"):
        s.add_argument("--" + k, type=Path, required=True)
    for k in ("rpc", "owner"):
        s.add_argument("--" + k, required=True)
    s.add_argument("--funding", action="append", required=True,
                   help="plain empty Cell of the account as <tx_hash>:<index>; repeat to combine several")
    s.add_argument("--fee", type=int, default=DEFAULT_FEE)
    s.set_defaults(func=cmd_prepare_deploy)
    s = sub.add_parser("confirm-deploy")
    for k in ("release", "tx", "out"):
        s.add_argument("--" + k, type=Path, required=True)
    for k in ("rpc", "hash"):
        s.add_argument("--" + k, required=True)
    s.set_defaults(func=cmd_confirm_deploy)
    s = sub.add_parser("create")
    for k in ("release", "deployment", "work"):
        s.add_argument("--" + k, type=Path, required=True)
    for k in ("rpc", "owner", "funding"):
        s.add_argument("--" + k, required=True)
    s.add_argument("--capacity-ckb", type=int, default=DEFAULT_CAPACITY // 100_000_000)
    s.add_argument("--fee", type=int, default=DEFAULT_FEE)
    s.add_argument("--nargo", default="nargo")
    s.set_defaults(func=cmd_create)
    s = sub.add_parser("update")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--funding", required=True)
    s.add_argument("--delta", type=int, required=True, help=f"hidden amount to add, 0..{pt.MAX_DELTA} (0 = cover update)")
    s.add_argument("--replace-pending", action="store_true")
    s.set_defaults(func=cmd_update)
    for name, func in (("check", cmd_check), ("status", cmd_status)):
        s = sub.add_parser(name)
        s.add_argument("--work", type=Path, required=True)
        s.set_defaults(func=func)
    sub.choices["status"].add_argument("--show-value", action="store_true")
    s = sub.add_parser("confirm")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--hash", required=True)
    s.set_defaults(func=cmd_confirm)
    s = sub.add_parser("backup")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--to", type=Path, required=True)
    s.set_defaults(func=cmd_backup)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except (RuntimeError, ValueError, PermissionError, FileExistsError, c.RpcError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
