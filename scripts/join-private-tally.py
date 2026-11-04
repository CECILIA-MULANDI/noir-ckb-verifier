#!/usr/bin/env python3
"""Join the private tally v2 testnet deployment with your own hidden tally.

The deployment (Type Script, ceremony verification key and guard Lock code) is
already on testnet, so a participant only needs about 262 testnet CKB: 200 CKB
locked in their own tally Cell, plus change and a small fee.

Before this, run the ceremony setup on your own machine:

  python3 -B scripts/setup-private-tally.py --out target/<dir>/setup \\
      --backend ../Noir-Groth16 --ptau <ppot_0080_12.ptau> --ceremony ceremony/private-tally-v2

That rebuilds the circuit with your own toolchain, checks that it lowers to the
frozen R1CS, checks the ceremony's final key and verification key, and makes
test proofs. `init` then checks the live testnet deployment against the public
record and against your own setup, and writes the release and deployment files
that scripts/private-tally-client.py uses for create, update, check and confirm.

This tool reads only public chain data and local files. It never reads wallets,
keys or passwords, and never signs or broadcasts.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import counter_platform as cp  # noqa: E402
import owned_counter as c  # noqa: E402
import private_tally as pt  # noqa: E402

DEFAULT_RECORD = c.ROOT / "evidence/private-tally-testnet/deployment.json"
FILES = {"type": "private-tally", "vk": "vk.mol.bin", "guard": "guard-always-success"}
POLICY_KEYS = ("network_domain", "owner_code_hash", "owner_data_hash", "owner_dep")


def stage(n, text):
    print(f"== {n}/5 {text}", flush=True)


def init(a):
    out = a.out.resolve()
    c.require(out.is_relative_to((c.ROOT / "target").resolve()), "--out must be below this checkout's target/")
    c.require(not out.exists(), f"{out} exists; choose a new directory")
    record = c.read(a.record)
    c.require(record.get("profile") == pt.PROFILE, "the record is not a private tally deployment")

    stage(1, "your ceremony setup")
    setup = a.setup.resolve()
    m = c.read(setup / "manifest.json")
    c.require(m.get("status") == "passed" and m.get("profile") == pt.PROFILE, "setup did not pass for this profile")
    c.require("ceremony" in m and m.get("zkey") == "ceremony.zkey",
              "setup was not made with --ceremony; run setup-private-tally.py with --ceremony ceremony/private-tally-v2")
    c.require(m["ceremony"]["final"] == record["ceremony"]["final"], "your setup used a different ceremony key")
    for f, digest in m["artifacts"].items():
        c.require(c.sha(setup / f) == digest, f"setup artifact changed: {f}")

    stage(2, "network and ownership policy")
    c.network(a.rpc, record["network_domain"])
    out.mkdir(parents=True)
    c.preflight(argparse.Namespace(rpc=a.rpc, genesis=record["network_domain"], out=out / "policy.json"))
    live_policy = c.read(out / "policy.json")
    expected = dict(record["policy"], network_domain=record["network_domain"])
    for k in POLICY_KEYS:
        c.require(live_policy[k] == expected[k], f"live chain {k} differs from the record")

    stage(3, "deployed Cells")
    (out / "artifacts").mkdir()
    artifacts = {}
    for kind, name in FILES.items():
        meta = record["artifacts"][kind]
        cell = c.live(a.rpc, record["deployment"][kind])
        c.require(cell["output"]["type"] is None, f"deployed {kind} Cell has a Type")
        data = c.raw(cell["data"]["content"])
        c.require(c.hx(c.h(data)) == meta["data_hash"] and len(data) == meta["bytes"],
                  f"live {kind} Cell differs from the record")
        path = out / "artifacts" / name
        path.write_bytes(data)
        c.require(c.sha(path) == meta["sha256"], f"live {kind} bytes differ from the record")
        artifacts[kind] = dict(path=str(path), sha256=meta["sha256"], data_hash=meta["data_hash"], bytes=meta["bytes"])

    stage(4, "the deployed key is the ceremony key")
    c.require((out / "artifacts/vk.mol.bin").read_bytes() == (setup / "adapter/vk.mol.bin").read_bytes(),
              "the deployed verification key is not the one your setup derived from the ceremony key")
    try:
        local_guard = (cp.cargo_home() / "registry/src")
        guard = next(local_guard.glob("*/ckb-always-success-script-0.0.1/specs/cells/always_success")).read_bytes()
        c.require(guard == (out / "artifacts/guard-always-success").read_bytes(),
                  "the deployed guard code differs from ckb-always-success-script 0.0.1")
        guard_note = "matches the local ckb-always-success-script 0.0.1 crate"
    except StopIteration:
        guard_note = "checked against the record only (crate not in the local Cargo cache)"
    c.require(record["policy"]["vk_data_hash"] == artifacts["vk"]["data_hash"]
              and record["policy"]["guard_data_hash"] == artifacts["guard"]["data_hash"],
              "record policy does not match its own artifacts")

    stage(5, "local release files")
    policy = dict(live_policy, profile=pt.PROFILE, guard_data_hash=artifacts["guard"]["data_hash"],
                  vk_data_hash=artifacts["vk"]["data_hash"])
    c.write(out / "release.json", dict(profile=pt.PROFILE, policy=policy, setup=str(setup), artifacts=artifacts,
                                       development_only=False, ceremony=m["ceremony"], joined_deployment=True,
                                       record_sha256=c.sha(a.record)))
    c.write(out / "deployment.json", dict(status="published-deployment-checked-live", release_sha256=c.sha(out / "release.json"),
                                          **{k: record["deployment"][k] for k in ("tx_hash", "type", "vk", "guard")}))
    print(f"""
Verified. The live testnet Cells hold the published Type Script, guard code and a
verification key that your own setup derived from the ceremony key (guard code
{guard_note}).

Next, with your own testnet account (see docs/try-the-private-tally.md):
  python3 -B scripts/private-tally-client.py create --release {out / 'release.json'} \\
      --deployment {out / 'deployment.json'} --work {out / 'my-tally'} --rpc {a.rpc} \\
      --owner <your lock_arg> --funding <0xhash:index>
""")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("--setup", type=Path, required=True, help="your setup-private-tally.py --ceremony output")
    s.add_argument("--out", type=Path, required=True, help="new directory below target/")
    s.add_argument("--rpc", default="https://testnet.ckb.dev")
    s.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    s.set_defaults(func=init)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except (RuntimeError, ValueError, OSError, c.RpcError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
