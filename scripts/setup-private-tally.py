#!/usr/bin/env python3
"""Fresh DEVELOPMENT ONLY setup for the private tally v2 circuit (single party).

Builds the pinned backend, compiles circuits/private-tally-v2, creates the R1CS
from a throwaway witness, runs a Groth16 setup, proves a creation (0) and an
update (0 -> 7) with fresh random secrets, checks that each altered public value
is rejected, and converts the update proof and key with the Rust adapter.

Phase 1 is a local single-party Powers of Tau unless --ptau names a prepared
Perpetual Powers of Tau file: a Hermez file is checked against its published
BLAKE2b hash; any other file (for example PSE's ppot_0080_12.ptau) must pass
`snarkjs powersoftau verify`, and its hash and contribution list are recorded.
Either way phase 2 has one development contribution: this is NOT the ceremony.

With --ceremony DIR (a finalized ceremony folder such as
ceremony/private-tally-v2) the run skips the setup and uses the ceremony's final
key instead. It requires the freshly built R1CS to equal the frozen one, the
final key and verification key to match the transcript hashes, `snarkjs zkey
verify` to pass against --ptau, and the key's exported verification key to equal
the published one; then it runs the same proofs, rejections and adapter checks.

Secrets (keys, blinding factors, inputs, .wtns witnesses) exist only under
<out>/private (mode 0700), which is deleted at the end unless --keep-private.
The run fails if any secret appears in a kept file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import private_tally as pt  # noqa: E402

ROOT = pt.ROOT
BACKEND_REV = "828025f3a0090e2934940956c0f5dc8093eb5532"
# BLAKE2b-512 of the Hermez files, from the snarkjs README.
HERMEZ = {
    12: "ded2694169b7b08e898f736d5de95af87c3f1a64594013351b1a796dbee393bd825f88f9468c84505ddd11eb0b1465ac9b43b9064aa8ec97f2b73e04758b8a4a",
    13: "58efc8bf2834d04768a3d7ffcd8e1e23d461561729beaac4e3e7a47829a1c9066d5320241e124a1a8e8aa6c75be0ba66f65bc8239a0542ed38e11276f6fdb4d9",
}
# BLAKE2b-512 of PSE Perpetual Powers of Tau prepared files, recorded after a full
# `snarkjs powersoftau verify` (61 contributions plus the final beacon) on
# 16 October 2026. Anyone can re-verify the file with the same command.
PSE_PPOT = {
    12: "3ee85ae13672d1d742117566126f31d678cf72d480f0df8e2aec78d77771433392ae01bb2b11c4ea0e60b244415be0a12a02e51d3f7a4a8b5c1c982fa208c4cd",
}
CTX = ("13", "17")  # fixed test context halves; the Type Script derives real ones


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def blake2b(p):
    h = hashlib.blake2b()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ptau_power(path):
    """Read the power from a snarkjs .ptau header (section 1: n8, q, power, ceremonyPower)."""
    import struct
    with open(path, "rb") as f:
        if f.read(4) != b"ptau":
            raise RuntimeError(f"{path} is not a .ptau file")
        _version, sections = struct.unpack("<II", f.read(8))
        for _ in range(sections):
            kind, size = struct.unpack("<IQ", f.read(12))
            if kind == 1:
                (n8,) = struct.unpack("<I", f.read(4))
                f.read(n8)
                (power,) = struct.unpack("<I", f.read(4))
                return power
            f.seek(size, 1)
    raise RuntimeError(f"{path} has no header section")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--backend", type=Path, default=ROOT.parent / "Noir-Groth16")
    ap.add_argument("--nargo", default="nargo")
    ap.add_argument("--ptau", type=Path, help="prepared Perpetual Powers of Tau file (Hermez or PSE ppot_0080)")
    ap.add_argument("--keep-private", action="store_true", help="keep throwaway secrets for debugging")
    ap.add_argument("--ceremony", type=Path, help="finalized ceremony folder; use its final key instead of a new setup")
    args = ap.parse_args()
    if args.ceremony and not args.ptau:
        ap.error("--ceremony needs --ptau (the phase 1 file the ceremony used)")
    out, backend = args.out.resolve(), args.backend.resolve()
    out.mkdir(parents=True, exist_ok=False)
    log = []
    manifest = dict(status="running", profile=pt.PROFILE,
                    setup="DEVELOPMENT ONLY; single-party phase 2 (snarkjs adds OS randomness that is not "
                          "retained; the contributor could have kept it); NOT the ceremony; NOT production")
    secrets_used = set()

    def save():
        (out / "commands.json").write_text(json.dumps(log, indent=2) + "\n")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def run(cmd, cwd=ROOT, env=None, expected=0, redact=False, timeout=900):
        cmd = [str(c) for c in cmd]
        e = os.environ.copy()
        e.update(env or {})
        q = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)
        log.append(dict(command=cmd, cwd=str(cwd), env=env or {}, exit=q.returncode,
                        stdout="[redacted]" if redact else q.stdout, stderr="[redacted]" if redact else q.stderr))
        save()
        print(cmd[:3], q.returncode, flush=True)
        if q.returncode != expected or (expected == 0 and "[ERROR]" in q.stdout):
            raise RuntimeError("command failed: " + " ".join(cmd[:4]) + ("" if redact else "\n" + q.stdout[-1500:] + q.stderr[-1500:]))
        return q.stdout + q.stderr

    private = pt.PrivateDir(out / "private", create=True)
    try:
        if run(["git", "rev-parse", "HEAD"], backend).strip() != BACKEND_REV:
            raise RuntimeError(f"backend must be at {BACKEND_REV}")
        if run(["git", "status", "--porcelain"], backend).strip():
            raise RuntimeError("backend checkout must be clean")
        manifest["backend_revision"] = BACKEND_REV
        version = run([args.nargo, "--version"])
        if "1.0.0-beta.18" not in version or "99bb8b5cf33d7669adbdef096b12d80f30b4c0c9" not in version:
            raise RuntimeError("Nargo 1.0.0-beta.18 (99bb8b5c) required")
        manifest["nargo"] = version.strip()
        snark = ["npx", "--offline", "snarkjs@0.7.5"]
        if "snarkjs@0.7.5" not in run(snark + ["--version"], expected=99):
            raise RuntimeError("snarkjs 0.7.5 required (npx cache)")
        run(["cargo", "+1.95.0", "build", "--locked", "--offline", "-p", "noir-cli"], backend,
            {"CARGO_TARGET_DIR": str(out / "backend-target")})
        cli = out / "backend-target/debug/noir-cli"
        manifest["backend_binary_sha256"] = sha(cli)

        circuit = pt.Circuit(private, args.nargo)
        artifact = circuit.compile()
        deps = [Path.home() / "nargo/github.com/noir-lang/poseidon/v0.2.6"]
        if os.environ.get("NARGO_HOME"):
            deps.append(Path(os.environ["NARGO_HOME"]) / "github.com/noir-lang/poseidon/v0.2.6")
        heads = {run(["git", "-C", d, "rev-parse", "HEAD"]).strip() for d in deps if d.is_dir()}
        if heads != {pt.POSEIDON_COMMIT}:
            raise RuntimeError(f"poseidon v0.2.6 must be {pt.POSEIDON_COMMIT}; found {heads or 'none'}")
        public_dir = out / "circuit"
        public_dir.mkdir()
        shutil.copy2(artifact, public_dir / "private_tally_v2.json")
        manifest["circuit_artifact_sha256"] = sha(artifact)

        key = pt.new_secret()
        r0, r1 = pt.new_secret(), pt.new_secret()
        secrets_used |= {key, r0, r1}
        c0 = circuit.commitment(0, r0, key)
        c1 = circuit.commitment(7, r1, key)
        cases = {
            "creation": dict(value_old=0, r_old=0, key=key, delta=0, r_new=r0, c_old=0, c_new=c0),
            "update": dict(value_old=0, r_old=r0, key=key, delta=7, r_new=r1, c_old=c0, c_new=c1),
        }

        r1cs_path = None
        for name, values in cases.items():
            values = {k: str(v) for k, v in values.items()} | dict(ctx_lo=CTX[0], ctx_hi=CTX[1])
            work = private.path / name
            work.mkdir(mode=0o700)
            (work / "inputs.json").write_text(json.dumps(values) + "\n")
            run([cli, "interop", artifact, work / "inputs.json", "--out", work / "interop"], backend, redact=True)
            run(snark + ["wtns", "check", work / "interop/circuit.r1cs", work / "interop/witness.wtns"], redact=True)
            run(snark + ["wtns", "export", "json", work / "interop/witness.wtns", work / "witness.json"], redact=True)
            public = [values[k] for k in ("c_old", "c_new", "ctx_lo", "ctx_hi")]
            if json.loads((work / "witness.json").read_text())[1:5] != public:
                raise RuntimeError(f"{name}: public values are not in wires 1..4")
            if r1cs_path is None:
                r1cs_path = out / "circuit.r1cs"
                shutil.copy2(work / "interop/circuit.r1cs", r1cs_path)
            elif sha(work / "interop/circuit.r1cs") != sha(r1cs_path):
                raise RuntimeError("R1CS differs between witnesses")
            values["_public"] = public
            cases[name] = values

        run(snark + ["r1cs", "export", "json", r1cs_path, out / "r1cs.json"])
        r1cs = json.loads((out / "r1cs.json").read_text())
        (out / "r1cs.json").unlink()
        if r1cs["nPubInputs"] != 4 or r1cs["nOutputs"] != 0 or r1cs["nPrvInputs"] != 5:
            raise RuntimeError("unexpected R1CS input counts")
        manifest.update(constraints=r1cs["nConstraints"], wires=r1cs["nVars"], r1cs_sha256=sha(r1cs_path))

        if args.ceremony:
            cer = args.ceremony.resolve()
            t = json.loads((cer / "transcript.json").read_text())
            if t.get("profile") != pt.PROFILE or "final" not in t:
                raise RuntimeError("ceremony is not a finalized private tally v2 ceremony")
            if sha(r1cs_path) != t["r1cs_sha256"] or sha(cer / "circuit.r1cs") != t["r1cs_sha256"]:
                raise RuntimeError("this build's R1CS differs from the frozen ceremony circuit")
            if sha(cer / "zkeys/tally_final.zkey") != t["final"]["zkey_sha256"]:
                raise RuntimeError("tally_final.zkey differs from the transcript")
            if sha(cer / "verification_key.json") != t["final"]["vk_sha256"]:
                raise RuntimeError("verification_key.json differs from the transcript")
            phase1 = args.ptau.resolve()
            digest = blake2b(phase1)
            if digest != t["ptau"]["blake2b"]:
                raise RuntimeError("--ptau is not the ceremony's phase 1 file")
            manifest.update(phase1=f"{t['ptau']['file']} (ceremony phase 1)", phase1_blake2b=digest,
                            ptau_power=ptau_power(phase1),
                            setup=f"CEREMONY: {pt.PROFILE} phase 2 with {len(t['contributions'])} contributions and "
                                  f"the beacon of {t['beacon']['network']} block {t['beacon']['height']}; "
                                  "public testnet developer-preview ceremony, not an audited production setup",
                            ceremony=dict(freeze_commit=t["freeze_commit"], contributions=len(t["contributions"]),
                                          beacon=t["beacon"], final=t["final"]))
            zkey = "ceremony.zkey"
            shutil.copy2(cer / "zkeys/tally_final.zkey", out / zkey)
            run(snark + ["zkey", "verify", r1cs_path, phase1, out / zkey])
            run(snark + ["zkey", "export", "verificationkey", out / zkey, out / "verification_key.json"])
            if json.loads((out / "verification_key.json").read_text()) != json.loads((cer / "verification_key.json").read_text()):
                raise RuntimeError("the final key does not export the published verification key")
            shutil.copy2(cer / "verification_key.json", out / "verification_key.json")
        elif args.ptau:
            phase1 = args.ptau.resolve()
            if phase1.stat().st_size < 1_000_000:
                raise RuntimeError(f"{phase1} is too small to be a ptau file (a failed download?)")
            digest = blake2b(phase1)
            power = next((p for p, h in HERMEZ.items() if digest == h), None)
            pse = next((p for p, h in PSE_PPOT.items() if digest == h), None)
            if power is not None:
                manifest["phase1"] = f"Hermez powersOfTau28_hez_final_{power}.ptau (published BLAKE2b matched)"
            elif pse is not None:
                power = pse
                manifest["phase1"] = (f"PSE ppot_0080_{pse}.ptau (BLAKE2b matched the pinned value, recorded after "
                                      "a full powersoftau verify; re-verify with snarkjs powersoftau verify)")
            else:
                # Verifying a long contribution chain is slow (tens of minutes), so a
                # successful verification is cached next to the file, keyed by its hash.
                record_path = phase1.with_name(phase1.name + ".verified.json")
                record = json.loads(record_path.read_text()) if record_path.exists() else {}
                if record.get("blake2b") == digest and record.get("result") == "Powers of Tau Ok!":
                    contributions = record["contribution_lines"]
                    manifest["phase1_verification"] = f"cached: {record_path.name} ({record['verified_utc']})"
                else:
                    print(f"Verifying the full contribution chain of {phase1.name}; this can take 30-60 minutes "
                          "and runs only once per file.", flush=True)
                    report = run(snark + ["powersoftau", "verify", phase1], timeout=None)
                    if "powers of tau ok" not in report.lower():
                        raise RuntimeError("powersoftau verify did not confirm the file")
                    contributions = report.lower().count("contribution #")
                    import datetime
                    record = dict(file=phase1.name, blake2b=digest, result="Powers of Tau Ok!",
                                  contribution_lines=contributions, snarkjs="0.7.5",
                                  verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                  report_sha256=hashlib.sha256(report.encode()).hexdigest())
                    record_path.write_text(json.dumps(record, indent=2) + "\n")
                    manifest["phase1_verification"] = f"verified in this run; recorded in {record_path.name}"
                power = ptau_power(phase1)
                manifest["phase1"] = (f"{phase1.name}: full chain verified with snarkjs powersoftau verify, "
                                      f"{contributions} contribution lines; hash recorded, not pinned")
            manifest["phase1_blake2b"] = digest
        else:
            power = max(12, (2 * r1cs["nConstraints"]).bit_length())
            run(snark + ["powersoftau", "new", "bn128", power, out / "initial.ptau"])
            run(snark + ["powersoftau", "contribute", out / "initial.ptau", out / "contributed.ptau",
                         "--name=DEVELOPMENT ONLY", "-e=DEVELOPMENT-ONLY-private-tally-v2"])
            run(snark + ["powersoftau", "prepare", "phase2", out / "contributed.ptau", out / "phase2.ptau"])
            run(snark + ["powersoftau", "verify", out / "phase2.ptau"])
            for p in ("initial.ptau", "contributed.ptau"):
                (out / p).unlink()
            phase1 = out / "phase2.ptau"
            manifest["phase1"] = f"local single-party, power {power}"
        if not args.ceremony:
            manifest["ptau_power"] = power
            zkey = "development.zkey"
            run(snark + ["groth16", "setup", r1cs_path, phase1, out / "initial.zkey"])
            run(snark + ["zkey", "contribute", out / "initial.zkey", out / zkey,
                         "--name=DEVELOPMENT ONLY", "-e=DEVELOPMENT-ONLY-private-tally-v2-phase2"])
            (out / "initial.zkey").unlink()
            run(snark + ["zkey", "verify", r1cs_path, phase1, out / zkey])
            run(snark + ["zkey", "export", "verificationkey", out / zkey, out / "verification_key.json"])
        manifest["zkey"] = zkey

        for name, values in cases.items():
            proofs = out / "proofs" / name
            proofs.mkdir(parents=True)
            run(snark + ["groth16", "prove", out / zkey, private.path / name / "interop/witness.wtns",
                         proofs / "proof.json", proofs / "public.json"])
            if json.loads((proofs / "public.json").read_text()) != values["_public"]:
                raise RuntimeError(f"{name}: proof public values differ")
            run(snark + ["groth16", "verify", out / "verification_key.json", proofs / "public.json", proofs / "proof.json"])
            for slot in range(4):
                changed = list(values["_public"])
                changed[slot] = str((int(changed[slot]) + 1) % pt.P)
                p = proofs / f"changed-{slot}.json"
                p.write_text(json.dumps(changed) + "\n")
                if "Invalid proof" not in run(snark + ["groth16", "verify", out / "verification_key.json", p,
                                                      proofs / "proof.json"], expected=1):
                    raise RuntimeError(f"{name}: altered public value {slot} was not rejected")

        upd = out / "proofs/update"
        run(["cargo", "+1.95.0", "run", "--locked", "--offline", "-p", "artifact-adapter", "--bin", "noir-ckb-adapter",
             "--", "--vk", out / "verification_key.json", "--proof", upd / "proof.json", "--public", upd / "public.json",
             "--negative-public", upd / "changed-0.json", "--out", out / "adapter"])
        manifest["status"] = "passed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        if not args.keep_private:
            shutil.rmtree(private.path, ignore_errors=True)
        manifest["artifacts"] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*"))
                                 if p.is_file() and "backend-target" not in p.parts and "private" not in p.parts
                                 and p.name not in ("commands.json", "manifest.json")}
        leaks = pt.leak_scan(out, secrets_used, exclude=[out / "backend-target"] + ([private.path] if args.keep_private else []))
        if leaks:
            manifest["status"] = "failed"
            manifest["leak_scan"] = leaks
            print(f"FAIL: secret material found in {leaks}")
        else:
            manifest["leak_scan"] = "clean"
        save()
    print(f"{manifest['status']}: {out / 'manifest.json'}")
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
