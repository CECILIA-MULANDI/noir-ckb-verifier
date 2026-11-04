#!/usr/bin/env python3
"""CKB-VM matrix for the private tally v2 Type Script (docs/private-tally-v2-spec.md, section 10).

Builds the Type Script with pins for an isolated test network, the setup's
verification key and the always-success guard Lock; generates fresh proofs for
the statements each case needs; writes every case as a transaction plus the
cells it spends and depends on; then runs them all in CKB-VM through
ckb-testtool (crates/ckb-integration-tests/tests/private_tally.rs).

Development material only. Secrets live under <out>/private (mode 0700), which is
deleted at the end unless --keep-private; the run fails if any secret appears in
a kept file. No network, wallet or chain is used.
"""
import argparse
import copy
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
TEST_NETWORK = c.h(b"noir-ckb private tally isolated VM test network")
OTHER_NETWORK = c.h(b"noir-ckb private tally some other network")
CKB = 100_000_000
TALLY_CAPACITY = 200 * CKB
FUND = 1000 * CKB
FEE = 1_000_000


def point(byte, index=0):
    return dict(tx_hash="0x" + byte * 32, index=hex(index))


class Matrix:
    def __init__(self, args):
        self.args = args
        self.out = args.out.resolve()
        if not self.out.is_relative_to((ROOT / "target").resolve()):
            raise SystemExit("--out must be below this checkout's target/")
        self.out.mkdir(parents=True, exist_ok=False)
        self.setup = args.setup.resolve()
        manifest = c.read(self.setup / "manifest.json")
        c.require(manifest.get("status") == "passed" and manifest.get("profile") == pt.PROFILE,
                  "setup did not pass for the private tally profile")
        for f, digest in manifest["artifacts"].items():
            c.require(c.sha(self.setup / f) == digest, f"setup artifact changed: {f}")
        self.private = pt.PrivateDir(self.out / "private", create=True)
        self.secrets = set()
        self.log = []
        self.cases = []

    # ------------------------------------------------------------ tooling
    def run(self, cmd, cwd=ROOT, env=None, redact=False):
        cmd = [str(x) for x in cmd]
        q = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=1800)
        self.log.append(dict(command=cmd, exit=q.returncode, stdout="[redacted]" if redact else q.stdout,
                             stderr="[redacted]" if redact else q.stderr))
        (self.out / "commands.json").write_text(json.dumps(self.log, indent=2) + "\n")  # rewritten after each command
        c.require(q.returncode == 0 and "[ERROR]" not in q.stdout,
                  "command failed: " + " ".join(cmd[:4]) + ("" if redact else "\n" + q.stdout[-1500:] + q.stderr[-1500:]))
        return q.stdout

    def build(self, contracts=None):
        always = next((cp.cargo_home() / "registry/src").glob("*/ckb-always-success-script-0.0.1/specs/cells/always_success"))
        self.always = always.read_bytes()
        self.vk_mol = (self.setup / "adapter/vk.mol.bin").read_bytes()
        env = os.environ.copy()
        env.update(TALLY_NETWORK_DOMAIN=c.hx(TEST_NETWORK), TALLY_GUARD_DATA_HASH=c.hx(c.h(self.always)),
                   TALLY_VK_DATA_HASH=c.hx(c.h(self.vk_mol)), CARGO_TARGET_DIR=str(self.out / "contract-target"))
        compiler = cp.find_clang(env)
        if compiler:
            env.update(CLANG=compiler, CC_riscv64imac_unknown_none_elf=compiler)
        self.run(["cargo", "+1.94.1", "build", "--locked", "--offline", "--release", "--target",
                  "riscv64imac-unknown-none-elf", "-p", "private-tally"], contracts or ROOT / "contracts", env)
        elf = self.out / "contract-target/riscv64imac-unknown-none-elf/release/private-tally"
        shutil.copyfile(elf, self.out / "private-tally")
        self.elf = elf.read_bytes()
        self.code_hash = c.h(self.elf)
        self.guard = pt.guard_lock(c.h(self.always))
        self.funding_lock = dict(code_hash=c.hx(c.h(self.always)), hash_type="data1", args="0x01")
        c.write(self.out / "build.json", dict(elf_sha256=c.sha(self.out / "private-tally"), elf_bytes=len(self.elf),
                                              code_hash=c.hx(self.code_hash), network_domain=c.hx(TEST_NETWORK),
                                              guard_data_hash=c.hx(c.h(self.always)),
                                              vk_data_hash=c.hx(c.h(self.vk_mol))))
        # Dependency cells: Type code, verification key, guard Lock code.
        self.dep_cells = [self.cell(point("a1"), FUND, self.funding_lock, None, self.elf),
                          self.cell(point("a2"), FUND, self.funding_lock, None, self.vk_mol),
                          self.cell(point("a3"), FUND, self.funding_lock, None, self.always)]

    @staticmethod
    def cell(out_point, capacity, lock, tscript, data):
        return dict(out_point=out_point, output=c.output(capacity, lock, tscript), data=c.hx(data))

    def secret(self):
        v = pt.new_secret()
        self.secrets.add(v)
        return v

    def prove(self, name, **values):
        """Fresh proof for the given statement; returns the wire witness payload."""
        work = self.private.path / "proofs" / name
        work.mkdir(parents=True)
        (work / "inputs.json").write_text(json.dumps({k: str(v) for k, v in values.items()}) + "\n")
        cli = self.setup / "backend-target/debug/noir-cli"
        self.run([cli, "interop", self.artifact, work / "inputs.json", "--out", work / "interop"], redact=True)
        kept = self.out / "proofs" / name
        kept.mkdir(parents=True)
        self.run(SNARK + ["groth16", "prove", self.setup / c.read(self.setup / "manifest.json").get("zkey", "development.zkey"), work / "interop/witness.wtns",
                          kept / "proof.json", kept / "public.json"])
        public = [str(values[k]) for k in ("c_old", "c_new", "ctx_lo", "ctx_hi")]
        c.require(c.read(kept / "public.json") == public, f"{name}: proof public values differ")
        wrong = list(public)
        wrong[2] = str(int(wrong[2]) + 1)
        c.write(kept / "wrong.json", wrong)
        self.run(["cargo", "+1.95.0", "run", "--locked", "--offline", "-p", "artifact-adapter", "--bin",
                  "noir-ckb-adapter", "--", "--vk", self.setup / "verification_key.json", "--proof",
                  kept / "proof.json", "--public", kept / "public.json", "--negative-public", kept / "wrong.json",
                  "--out", kept / "adapter"])
        print("proved", name, flush=True)
        return (kept / "adapter/witness.mol.bin").read_bytes()

    # ------------------------------------------------------------ base transactions
    def base_tx(self, inputs, outputs, outputs_data, witnesses):
        return dict(version="0x0", cell_deps=[c.dep(x["out_point"]) for x in self.dep_cells], header_deps=[],
                    inputs=[dict(since="0x0", previous_output=p) for p in inputs], outputs=outputs,
                    outputs_data=outputs_data, witnesses=witnesses)

    def creation(self):
        f1 = self.cell(point("f1"), FUND, self.funding_lock, None, b"")
        tid = pt.type_id(dict(since="0x0", previous_output=f1["out_point"]), 0)
        self.tscript = pt.type_script(self.code_hash, tid)
        self.key, self.r0, self.r1, self.r2 = self.secret(), self.secret(), self.secret(), self.secret()
        self.c0 = self.circuit.commitment(0, self.r0, self.key)
        lo, hi = pt.context(TEST_NETWORK, self.tscript, 0, bytes(36), 0, self.c0, self.guard, TALLY_CAPACITY)
        payload = self.prove("creation", value_old=0, r_old=0, key=self.key, delta=0, r_new=self.r0,
                             c_old=0, c_new=self.c0, ctx_lo=lo, ctx_hi=hi)
        tx = self.base_tx([f1["out_point"]],
                          [c.output(TALLY_CAPACITY, self.guard, self.tscript),
                           c.output(FUND - TALLY_CAPACITY - FEE, self.funding_lock)],
                          [c.hx(pt.tally_data(self.c0)), "0x"], [pt.witness_args(output_type=payload)])
        self.create_payload = payload
        return tx, self.dep_cells + [f1]

    def update_world(self, value_old=0, delta=5, network=TEST_NETWORK, name="update", tscript=None, c_old=None,
                     r_old=None, successor=None, out_capacity=TALLY_CAPACITY, noncanonical_new=False):
        """A tally update with a fresh proof. successor / out_capacity / noncanonical_new build a
        transition the Type must reject even though its proof is valid for exactly that transaction."""
        tscript = tscript or self.tscript
        successor = successor or self.guard
        c_old = self.c0 if c_old is None else c_old
        r_old = self.r0 if r_old is None else r_old
        tally = self.cell(point("c1"), TALLY_CAPACITY, self.guard, tscript, pt.tally_data(c_old))
        f2 = self.cell(point("f2"), FUND, self.funding_lock, None, b"")
        r_new = self.secret()
        c_new = self.circuit.commitment(value_old + delta, r_new, self.key)
        # A non-canonical encoding adds the modulus: the same field element, different bytes.
        encoded_new = c_new + pt.P if noncanonical_new else c_new
        lo, hi = pt.context(network, tscript, 1, c.outpoint(tally["out_point"]), c_old, encoded_new, successor,
                            out_capacity)
        payload = self.prove(name, value_old=value_old, r_old=r_old, key=self.key, delta=delta, r_new=r_new,
                             c_old=c_old, c_new=c_new, ctx_lo=lo, ctx_hi=hi)
        if noncanonical_new:
            payload = payload[:-128] + pt.public_bytes(c_old, encoded_new, lo, hi)
        tx = self.base_tx([tally["out_point"], f2["out_point"]],
                          [c.output(out_capacity, successor, tscript), c.output(FUND - FEE, self.funding_lock)],
                          [c.hx(pt.VERSION + pt.le32(encoded_new)), "0x"],
                          [pt.witness_args(input_type=payload), "0x"])
        return tx, self.dep_cells + [tally, f2], payload, c_new

    # ------------------------------------------------------------ cases
    def save(self, name, error, base, change=None, recompute=False):
        tx, cells = copy.deepcopy(base[0]), copy.deepcopy(base[1])
        if change:
            change(tx, cells)
        if recompute:
            self.recompute(tx, cells)
        c.write(self.out / "cases" / f"{name}.json", dict(transaction=tx, cells=cells, error=error))
        self.cases.append(f"{name}.json")

    def recompute(self, tx, cells):
        """Replace the payload's public vector with the one the Type will derive (old proof bytes kept)."""
        o = next(i for i, x in enumerate(tx["outputs"]) if x["type"] and x["type"]["code_hash"] == c.hx(self.code_hash))
        out = tx["outputs"][o]
        c_new = int.from_bytes(c.raw(tx["outputs_data"][o])[1:], "little")
        tally_in = [(i, x) for i, x in enumerate(tx["inputs"])
                    for cell in cells if cell["out_point"] == x["previous_output"] and cell["output"]["type"]]
        if tally_in:
            i, inp = tally_in[0]
            cell = next(x for x in cells if x["out_point"] == inp["previous_output"])
            c_old = int.from_bytes(c.raw(cell["data"])[1:], "little")
            lo, hi = pt.context(TEST_NETWORK, out["type"], 1, c.outpoint(inp["previous_output"]), c_old, c_new,
                                out["lock"], int(out["capacity"], 16))
            parts = c.witness_parts(tx["witnesses"][i])
            payload = parts[1][4:]
            tx["witnesses"][i] = pt.witness_args(input_type=payload[:-128] + pt.public_bytes(c_old, c_new, lo, hi))
        else:
            lo, hi = pt.context(TEST_NETWORK, out["type"], 0, bytes(36), 0, c_new, out["lock"],
                                int(out["capacity"], 16))
            parts = c.witness_parts(tx["witnesses"][o])
            payload = parts[2][4:]
            tx["witnesses"][o] = pt.witness_args(output_type=payload[:-128] + pt.public_bytes(0, c_new, lo, hi))

    def build_cases(self):
        (self.out / "cases").mkdir()
        create = self.creation()
        upd_tx, upd_cells, upd_payload, c1 = self.update_world()
        update = (upd_tx, upd_cells)
        cover = self.update_world(delta=0, name="cover-update")[:2]
        other_net = self.update_world(network=OTHER_NETWORK, name="other-network")[:2]
        fresh_capacity = self.update_world(name="capacity-fresh", out_capacity=TALLY_CAPACITY - CKB)[:2]
        fresh_lock = self.update_world(name="successor-fresh", successor=self.funding_lock)[:2]
        fresh_noncanonical = self.update_world(name="noncanonical-fresh", noncanonical_new=True)[:2]
        P = pt.P

        def data(tx, value):
            tx["outputs_data"][0] = c.hx(value)

        # Creation
        self.save("create-valid", None, create)
        self.save("create-zero-commitment", 54, create, lambda t, cs: data(t, pt.tally_data(0)))
        self.save("create-noncanonical-commitment", 54, create, lambda t, cs: data(t, pt.VERSION + pt.le32(P)))
        self.save("create-wrong-data-version", 43, create, lambda t, cs: data(t, b"\x02" + pt.le32(self.c0)))
        self.save("create-short-data", 43, create, lambda t, cs: data(t, pt.tally_data(self.c0)[:-1]))
        self.save("create-not-guard-lock", 45, create, lambda t, cs: t["outputs"][0].__setitem__("lock", self.funding_lock))
        self.save("create-guard-with-args", 45, create,
                  lambda t, cs: t["outputs"][0].__setitem__("lock", dict(self.guard, args="0x00")))
        self.save("create-wrong-type-id", 44, create,
                  lambda t, cs: t["outputs"][0]["type"].__setitem__("args", "0x01" + "11" * 32))
        self.save("create-unknown-args-version", 41, create,
                  lambda t, cs: t["outputs"][0]["type"].__setitem__("args", "0x02" + t["outputs"][0]["type"]["args"][4:]))
        self.save("create-proof-in-input-type", 48, create,
                  lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args(input_type=self.create_payload)))
        self.save("create-missing-proof", 48, create, lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args()))
        self.save("create-other-commitment", 49, create, lambda t, cs: data(t, pt.tally_data(c1)))
        self.save("create-capacity-changed", 49, create,
                  lambda t, cs: t["outputs"][0].__setitem__("capacity", hex(TALLY_CAPACITY + CKB)))
        self.save("create-other-commitment-recomputed", 51, create, lambda t, cs: data(t, pt.tally_data(c1)), recompute=True)

        def dup_out(t, cs):
            t["outputs"].insert(1, copy.deepcopy(t["outputs"][0]))
            t["outputs_data"].insert(1, t["outputs_data"][0])
        self.save("create-duplicate-output", 42, create, dup_out)
        self.save("create-update-proof-as-creation", 49, create,
                  lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args(output_type=upd_payload)))

        def vk_cell(cs):
            return next(x for x in cs if c.raw(x["data"]) == self.vk_mol)

        def missing_vk(t, cs):
            point_ = vk_cell(cs)["out_point"]
            t["cell_deps"] = [d for d in t["cell_deps"] if d["out_point"] != point_]

        def wrong_vk(t, cs):
            v = vk_cell(cs)
            v["data"] = c.hx(self.vk_mol[:-1] + bytes([self.vk_mol[-1] ^ 1]))

        def duplicate_vk(t, cs):
            v = copy.deepcopy(vk_cell(cs))
            v["out_point"] = point("66")
            cs.append(v)
            t["cell_deps"].append(c.dep(v["out_point"]))
        self.save("create-missing-vk", 50, create, missing_vk)
        self.save("create-wrong-vk", 50, create, wrong_vk)
        self.save("create-duplicate-vk", 50, create, duplicate_vk)

        # Update
        self.save("update-valid", None, update)
        self.save("update-cover-delta-zero", None, cover)
        self.save("update-dependency-order", None, update, lambda t, cs: t["cell_deps"].reverse())

        def positions(t, cs):
            for k in ("inputs", "witnesses", "outputs", "outputs_data"):
                t[k].reverse()
        self.save("update-application-at-index-one", None, update, positions)
        self.save("update-unrelated-change", None, update,
                  lambda t, cs: t["outputs"][1].__setitem__("capacity", hex(FUND - 2 * FEE)))

        def tally_cell(cs):
            return next(x for x in cs if x["output"]["type"])
        self.save("update-wrong-input-commitment", 49, update,
                  lambda t, cs: tally_cell(cs).__setitem__("data", c.hx(pt.tally_data(c1))))

        def other_outpoint(t, cs):
            new = point("73")
            tally_cell(cs)["out_point"] = new
            t["inputs"][0]["previous_output"] = new
        self.save("update-replayed-on-other-outpoint", 49, update, other_outpoint)
        self.save("update-replayed-on-other-outpoint-recomputed", 51, update, other_outpoint, recompute=True)

        def swapped(t, cs):
            tally_cell(cs)["data"] = c.hx(pt.tally_data(c1))
            data(t, pt.tally_data(self.c0))
        self.save("update-swapped-commitments-recomputed", 51, update, swapped, recompute=True)
        self.save("update-proof-for-other-network", 49, other_net)

        def other_cell(t, cs):
            args = "0x01" + "21" * 32
            tally_cell(cs)["output"]["type"]["args"] = args
            t["outputs"][0]["type"]["args"] = args
        self.save("update-replayed-on-other-cell", 49, update, other_cell)
        # Proofs made for exactly these transactions: only the Type's own rules can reject them.
        self.save("update-capacity-changed-fresh-proof", 47, fresh_capacity)
        self.save("update-successor-not-guard-fresh-proof", 45, fresh_lock)
        self.save("update-noncanonical-successor-fresh-proof", 54, fresh_noncanonical)
        self.save("update-capacity-changed", 47, update,
                  lambda t, cs: t["outputs"][0].__setitem__("capacity", hex(TALLY_CAPACITY - CKB)))
        self.save("update-successor-not-guard", 45, update,
                  lambda t, cs: t["outputs"][0].__setitem__("lock", self.funding_lock))
        self.save("update-input-not-guard", 45, update,
                  lambda t, cs: tally_cell(cs)["output"].__setitem__("lock", self.funding_lock))

        def destroy(t, cs):
            t["outputs"].pop(0)
            t["outputs_data"].pop(0)
        self.save("update-destruction", 42, update, destroy)

        def dup_input(t, cs):
            v = copy.deepcopy(tally_cell(cs))
            v["out_point"] = point("81")
            cs.append(v)
            t["inputs"].append(dict(since="0x0", previous_output=v["out_point"]))
            t["witnesses"].append("0x")
        self.save("update-duplicate-input-group", 42, update, dup_input)
        self.save("update-zero-successor", 54, update, lambda t, cs: data(t, pt.tally_data(0)))
        self.save("update-noncanonical-input", 54, update,
                  lambda t, cs: tally_cell(cs).__setitem__("data", c.hx(pt.VERSION + pt.le32(P + 5))))
        w = lambda payload: (lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args(input_type=payload)))
        self.save("update-missing-proof", 48, update, lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args()))
        self.save("update-truncated-proof", 48, update, w(upd_payload[:-1]))
        self.save("update-trailing-proof", 48, update, w(upd_payload + b"\0"))
        self.save("update-proof-in-output-type", 48, update,
                  lambda t, cs: t["witnesses"].__setitem__(0, pt.witness_args(output_type=upd_payload)))
        self.save("update-oversized-witness", 48, update, w(bytes(600)))
        self.save("update-wrong-wire-version", 48, update, w(upd_payload[:12] + b"\x02\x00" + upd_payload[14:]))
        self.save("update-invalid-proof", 51, update, w(self.create_payload[:-128] + upd_payload[-128:]))
        self.save("update-creation-proof-as-update", 49, update, w(self.create_payload))

        def too_many_outputs(t, cs):
            while len(t["outputs"]) < 65:
                t["outputs"].append(c.output(61 * CKB, self.funding_lock))
                t["outputs_data"].append("0x")
        self.save("update-output-limit", 52, update, too_many_outputs)
        c.write(self.out / "cases" / "cases.json", self.cases)

    def execute(self):
        env = os.environ.copy()
        env.update(TALLY_CASES=str(self.out / "cases"))
        cmd = ["cargo", "+1.95.0", "test", "--locked", "--offline", "-p", "ckb-integration-tests", "--test",
               "private_tally", "--", "--ignored", "--nocapture"]
        q = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
        c.write(self.out / "run.json", dict(command=cmd, exit=q.returncode, stdout=q.stdout, stderr=q.stderr))
        print(q.stdout[-6000:], q.stderr[-3000:])
        return q.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", type=Path, required=True, help="a passed scripts/setup-private-tally.py output")
    ap.add_argument("--out", type=Path, required=True, help="new directory below target/")
    ap.add_argument("--nargo", default="nargo")
    ap.add_argument("--keep-private", action="store_true")
    m = Matrix(ap.parse_args())
    ok = False
    try:
        m.circuit = pt.Circuit(m.private, m.args.nargo)
        m.artifact = m.circuit.compile()
        # The artifact embeds source paths, so compare the compiled program and ABI only.
        mine, theirs = c.read(m.artifact), c.read(m.setup / "circuit/private_tally_v2.json")
        c.require(mine["bytecode"] == theirs["bytecode"] and mine["abi"] == theirs["abi"],
                  "circuit differs from the one the setup was made for")
        m.build()
        m.build_cases()
        ok = m.execute()
    finally:
        if not m.args.keep_private:
            shutil.rmtree(m.private.path, ignore_errors=True)
        exclude = [m.out / "contract-target"] + ([m.private.path] if m.args.keep_private else [])
        leaks = pt.leak_scan(m.out, m.secrets, exclude=exclude)
        summary = dict(status="passed" if ok and not leaks else "failed", cases=len(m.cases),
                       leak_scan=leaks or "clean")
        results = m.out / "cases/results.json"
        if results.exists():
            summary["results"] = c.read(results)
        c.write(m.out / "summary.json", summary)
        print(f"{summary['status']}: {len(m.cases)} cases, leak scan {summary['leak_scan']}. {m.out / 'summary.json'}")
    return 0 if ok and not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
