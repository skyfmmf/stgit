// SPDX-License-Identifier: GPL-2.0-only

//! Parsers for patch and revision specifications using [`nom`].

mod locator;
mod name;
mod numbers;
mod range;
mod revision;

#[cfg(test)]
mod tests;

pub(super) use self::{locator::*, range::*, revision::*};

/// The sign of a number.
pub(super) enum Sign {
    Plus,
    Minus,
}
