//! Owned-buffer ABI shared by native hosts and standalone wasm32.
use std::{cell::RefCell, collections::HashMap};

const MAX_INPUT: usize = 32 * 1024 * 1024;
#[derive(Default)]
struct State {
    allocations: HashMap<usize, Box<[u8]>>,
    output: Vec<u8>,
    error: Vec<u8>,
    width: usize,
    height: usize,
}
thread_local! { static STATE:RefCell<State>=RefCell::new(State::default()); }

#[no_mangle]
pub extern "C" fn rm_core_abi_version() -> u32 {
    1
}

#[no_mangle]
pub extern "C" fn rm_core_alloc(len: usize) -> usize {
    if len == 0 || len > MAX_INPUT {
        return 0;
    }
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        let allocated: usize = state.allocations.values().map(|b| b.len()).sum();
        if allocated + len > MAX_INPUT {
            return 0;
        }
        let mut bytes = Vec::new();
        if bytes.try_reserve_exact(len).is_err() {
            return 0;
        }
        bytes.resize(len, 0);
        let mut bytes = bytes.into_boxed_slice();
        let ptr = bytes.as_mut_ptr() as usize;
        state.allocations.insert(ptr, bytes);
        ptr
    })
}

#[no_mangle]
pub extern "C" fn rm_core_free(ptr: usize, len: usize) {
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        if state.allocations.get(&ptr).is_some_and(|v| v.len() == len) {
            state.allocations.remove(&ptr);
        }
    });
}

#[no_mangle]
pub extern "C" fn rm_core_render_json(ptr: usize, len: usize) -> u32 {
    let request = STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        state.output = Vec::new();
        state.error = Vec::new();
        state.width = 0;
        state.height = 0;
        let bytes = state
            .allocations
            .get(&ptr)
            .filter(|v| len > 0 && len <= v.len())
            .ok_or_else(|| "input must be a live allocated buffer".to_string())?;
        crate::match_json(&bytes[..len])
    });
    let result = request;
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        match result {
            Ok(image) => {
                state.width = 0;
                state.height = 0;
                state.output = image;
                0
            }
            Err(message) => {
                state.error = message.into_bytes();
                1
            }
        }
    })
}

#[no_mangle]
pub extern "C" fn rm_core_output_ptr() -> usize {
    STATE.with(|s| s.borrow().output.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_core_output_len() -> usize {
    STATE.with(|s| s.borrow().output.len())
}
#[no_mangle]
pub extern "C" fn rm_core_error_ptr() -> usize {
    STATE.with(|s| s.borrow().error.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_core_error_len() -> usize {
    STATE.with(|s| s.borrow().error.len())
}
#[no_mangle]
pub extern "C" fn rm_core_width() -> usize {
    STATE.with(|s| s.borrow().width)
}
#[no_mangle]
pub extern "C" fn rm_core_height() -> usize {
    STATE.with(|s| s.borrow().height)
}
