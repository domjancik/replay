#![doc = include_str!("../README.md")]
//! reMarkable archive decoding and normalization, independent of rasterization.
pub mod abi;
pub mod archive;
pub mod bridge;
pub mod legacy;
pub mod normalize;
pub mod v6;

/// Version of this crate's normalized JSON contract.
pub const NORMALIZATION_SCHEMA_VERSION: u32 = 1;
pub use normalize::{parse as parse_page, project as project_page};
pub use serde_json::Value;
