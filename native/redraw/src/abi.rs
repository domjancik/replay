//! Owned-buffer ABI shared by native hosts and standalone wasm32.
use std::{cell::RefCell, collections::HashMap};

const MAX_INPUT: usize = 32 * 1024 * 1024;
#[derive(Default)]
struct State {
    allocations: HashMap<usize, Box<[u8]>>,
    cache: crate::render::CachedRenderer,
    output: Vec<u8>,
    error: Vec<u8>,
    width: usize,
    height: usize,
}
thread_local! { static STATE:RefCell<State>=RefCell::new(State::default()); }

#[no_mangle]
pub extern "C" fn rm_renderer_abi_version() -> u32 {
    1
}

#[no_mangle]
pub extern "C" fn rm_renderer_alloc(len: usize) -> usize {
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
pub extern "C" fn rm_renderer_free(ptr: usize, len: usize) {
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        if state.allocations.get(&ptr).is_some_and(|v| v.len() == len) {
            state.allocations.remove(&ptr);
        }
    });
}

#[no_mangle]
pub extern "C" fn rm_renderer_render_json(ptr: usize, len: usize) -> u32 {
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
        serde_json::from_slice::<crate::model::Request>(&bytes[..len])
            .map_err(|e| format!("invalid render request: {e}"))
    });
    let result = request.and_then(|r| STATE.with(|cell| cell.borrow_mut().cache.render(&r)));
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        match result {
            Ok(image) => {
                state.width = image.width;
                state.height = image.height;
                state.output = image.data;
                0
            }
            Err(message) => {
                state.cache.clear();
                state.error = message.into_bytes();
                1
            }
        }
    })
}

#[no_mangle]
pub extern "C" fn rm_renderer_output_ptr() -> usize {
    STATE.with(|s| s.borrow().output.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_renderer_output_len() -> usize {
    STATE.with(|s| s.borrow().output.len())
}
#[no_mangle]
pub extern "C" fn rm_renderer_error_ptr() -> usize {
    STATE.with(|s| s.borrow().error.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_renderer_error_len() -> usize {
    STATE.with(|s| s.borrow().error.len())
}
#[no_mangle]
pub extern "C" fn rm_renderer_width() -> usize {
    STATE.with(|s| s.borrow().width)
}
#[no_mangle]
pub extern "C" fn rm_renderer_height() -> usize {
    STATE.with(|s| s.borrow().height)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_invalid_and_freed_handles_without_dereferencing() {
        assert_ne!(rm_renderer_render_json(42, 100), 0);
        assert_eq!(rm_renderer_output_len(), 0);
        let ptr = rm_renderer_alloc(16);
        assert_ne!(ptr, 0);
        rm_renderer_free(ptr, 16);
        rm_renderer_free(ptr, 16);
        assert_ne!(rm_renderer_render_json(ptr, 16), 0);
        assert_eq!(rm_renderer_alloc(MAX_INPUT + 1), 0);
    }
    #[test]
    fn owned_request_returns_rgba_and_clears_previous_result_on_error() {
        let json=br#"{"page":{"page_id":"x","paper_size":[2,1],"groups":[],"strokes":[],"compositing_order":[]},"options":{"background":[17,23,31,128]}}"#;
        let ptr = rm_renderer_alloc(json.len());
        STATE.with(|s| {
            s.borrow_mut()
                .allocations
                .get_mut(&ptr)
                .unwrap()
                .copy_from_slice(json)
        });
        assert_eq!(rm_renderer_render_json(ptr, json.len()), 0);
        assert_eq!((rm_renderer_width(), rm_renderer_height()), (2, 1));
        STATE.with(|s| assert_eq!(s.borrow().output, vec![17, 23, 31, 128, 17, 23, 31, 128]));
        assert_ne!(rm_renderer_render_json(ptr, 1), 0);
        assert_eq!(rm_renderer_output_len(), 0);
        rm_renderer_free(ptr, json.len());
        STATE.with(|s| assert_eq!(s.borrow().output.capacity(), 0));
    }
}
