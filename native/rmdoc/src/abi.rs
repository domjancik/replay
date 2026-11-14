//! Bounded owned-buffer ABI; input bytes are separate from small JSON options.
use std::{cell::RefCell, collections::HashMap};
const MAX_RAW: usize = 128 * 1024 * 1024;
const MAX_ARGS: usize = 4 * 1024 * 1024;
#[derive(Default)]
struct State {
    allocations: HashMap<usize, Box<[u8]>>,
    output: Vec<u8>,
    error: Vec<u8>,
}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::default());}
#[no_mangle]
pub extern "C" fn rm_doc_abi_version() -> u32 {
    1
}
#[no_mangle]
pub extern "C" fn rm_doc_alloc(len: usize) -> usize {
    if len == 0 || len > MAX_RAW {
        return 0;
    }
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        if s.allocations
            .values()
            .map(|v| v.len())
            .sum::<usize>()
            .saturating_add(len)
            > MAX_RAW + MAX_ARGS
        {
            return 0;
        }
        let mut b = Vec::new();
        if b.try_reserve_exact(len).is_err() {
            return 0;
        }
        b.resize(len, 0);
        let mut b = b.into_boxed_slice();
        let p = b.as_mut_ptr() as usize;
        s.allocations.insert(p, b);
        p
    })
}
#[no_mangle]
pub extern "C" fn rm_doc_free(ptr: usize, len: usize) {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        if s.allocations.get(&ptr).is_some_and(|v| v.len() == len) {
            s.allocations.remove(&ptr);
        }
    });
}
#[no_mangle]
pub extern "C" fn rm_doc_call(ptr: usize, len: usize, args_ptr: usize, args_len: usize) -> u32 {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        s.output.clear();
        s.error.clear();
        let result: Result<Vec<u8>, String> = (|| {
            if args_len > MAX_ARGS {
                return Err("Reader options exceed 4 MiB".into());
            }
            let raw = s
                .allocations
                .get(&ptr)
                .filter(|v| len <= v.len())
                .ok_or("Invalid raw allocation")?;
            let args = s
                .allocations
                .get(&args_ptr)
                .filter(|v| args_len <= v.len())
                .ok_or("Invalid options allocation")?;
            let args = serde_json::from_slice(&args[..args_len])
                .map_err(|e| format!("Invalid options JSON: {e}"))?;
            let result = crate::bridge::execute(&raw[..len], &args)?;
            let encoded = serde_json::to_vec(&result).map_err(|e| e.to_string())?;
            if encoded.len() > MAX_RAW {
                return Err("Normalized document exceeds output budget".into());
            }
            Ok(encoded)
        })();
        match result {
            Ok(out) => {
                s.output = out;
                0
            }
            Err(e) => {
                s.error = e.into_bytes();
                1
            }
        }
    })
}
#[no_mangle]
pub extern "C" fn rm_doc_output_ptr() -> usize {
    STATE.with(|s| s.borrow().output.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_doc_output_len() -> usize {
    STATE.with(|s| s.borrow().output.len())
}
#[no_mangle]
pub extern "C" fn rm_doc_error_ptr() -> usize {
    STATE.with(|s| s.borrow().error.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_doc_error_len() -> usize {
    STATE.with(|s| s.borrow().error.len())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_allocations_fail_without_dereferencing() {
        assert_eq!(rm_doc_call(1, 4, 2, 4), 1);
        assert!(rm_doc_error_len() > 0);
        assert_eq!(rm_doc_alloc(MAX_RAW + 1), 0);
        rm_doc_free(1, 4);
    }
}
