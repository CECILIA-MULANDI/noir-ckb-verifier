// noir-ckb/private-tally/range: prove a bound on a tally's hidden value without
// revealing it. Reuses the v2 commitment library unchanged.
//
// This circuit authorizes nothing. Unlike private-tally-v2 it carries no
// transaction context, so a proof here is a reusable bearer attestation about a
// commitment, never permission to update a Cell.
//
// A verifier must check two things the circuit cannot:
//   1. that `c` is the commitment the tally Cell holds now. Every update
//      rerandomizes the commitment, so a proof about an old `c` says nothing
//      about the current value.
//   2. that `(lo, hi)` is the range it asked about. `lo = 0, hi = 2^64 - 1`
//      proves only that the value is some u64, which the commitment already
//      implies.

use private_tally_commitment::commit;

fn main(value: Field, blinding: Field, key: Field, c: pub Field, lo: pub Field, hi: pub Field) {
    assert(c != 0, "zero is reserved as the creation sentinel");
    assert(commit(value, blinding, key) == c, "commitment does not open");

    value.assert_max_bit_size::<64>();
    lo.assert_max_bit_size::<64>();
    hi.assert_max_bit_size::<64>();

    (value - lo).assert_max_bit_size::<64>();
    (hi - value).assert_max_bit_size::<64>();
}

global KEY: Field = 0x1f2e3d4c5b6a79880123456789abcdef;
global R: Field = 0x11111111111111111111;
global U64_MAX: Field = 0xffffffffffffffff;
global NEG_ONE: Field = 0 - 1;
#[test]
fn value_inside_the_range() {
    main(5, R, KEY, commit(5, R, KEY), 3, 9);
}

#[test]
fn at_least_n() {
    main(5, R, KEY, commit(5, R, KEY), 3, U64_MAX);
}

#[test]
fn at_most_n() {
    main(5, R, KEY, commit(5, R, KEY), 0, 9);
}

#[test]
fn exact_value_when_bounds_meet() {
    main(5, R, KEY, commit(5, R, KEY), 5, 5);
}

#[test]
fn freshly_created_tally_proves_a_bound() {
    main(0, R, KEY, commit(0, R, KEY), 0, 9);
}

#[test]
fn value_at_the_top_of_the_u64_range() {
    main(U64_MAX, R, KEY, commit(U64_MAX, R, KEY), U64_MAX, U64_MAX);
}

#[test(should_fail)]
fn value_below_the_lower_bound() {
    main(5, R, KEY, commit(5, R, KEY), 6, 9);
}

#[test(should_fail)]
fn value_above_the_upper_bound() {
    main(5, R, KEY, commit(5, R, KEY), 0, 4);
}

#[test(should_fail_with = "commitment does not open")]
fn wrong_claimed_value() {
    main(6, R, KEY, commit(5, R, KEY), 3, 9);
}

#[test(should_fail_with = "commitment does not open")]
fn commitment_of_a_different_tally() {
    main(5, R, KEY, commit(5, R, KEY + 1), 3, 9);
}

#[test(should_fail_with = "commitment does not open")]
fn wrong_blinding() {
    main(5, R + 1, KEY, commit(5, R, KEY), 3, 9);
}

#[test(should_fail_with = "commitment does not open")]
fn wrong_key() {
    main(5, R, KEY + 1, commit(5, R, KEY), 3, 9);
}

#[test(should_fail_with = "zero is reserved as the creation sentinel")]
fn zero_commitment() {
    main(0, R, KEY, 0, 0, U64_MAX);
}

#[test(should_fail)]
fn inverted_bounds_are_unsatisfiable() {
    main(5, R, KEY, commit(5, R, KEY), 9, 3);
}

#[test(should_fail)]
fn value_above_u64() {
    let v = U64_MAX + 1;
    main(v, R, KEY, commit(v, R, KEY), 0, U64_MAX);
}

#[test(should_fail)]
fn upper_bound_above_u64() {
    main(5, R, KEY, commit(5, R, KEY), 0, U64_MAX + 1);
}

#[test(should_fail)]
fn lower_bound_near_the_field_modulus() {
    main(5, R, KEY, commit(5, R, KEY), NEG_ONE, U64_MAX);
}

#[test(should_fail)]
fn upper_bound_near_the_field_modulus() {
    main(5, R, KEY, commit(5, R, KEY), 0, NEG_ONE);
}
